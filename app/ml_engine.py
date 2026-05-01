# app/ml_engine.py
# This module implements the Machine Learning anomaly detection engine.
#
# Two algorithms are used:
#
# 1. ISOLATION FOREST
#    ─────────────────
#    Works by randomly isolating data points using decision trees.
#    Anomalies are data points that are easy to isolate (require
#    fewer splits). Think of it as: "normal data hides in crowds;
#    anomalies stand out."
#    → Great for: high-dimensional data, fast, no need for normal data only
#
# 2. ONE-CLASS SVM (Support Vector Machine)
#    ───────────────────────────────────────
#    Learns a boundary around the "normal" data. Anything outside
#    the boundary is flagged as an anomaly. Uses the RBF (Radial
#    Basis Function) kernel to handle non-linear boundaries.
#    → Great for: stable normal behaviour, very precise boundary
#
# Both models are trained on historical data. After training, they
# run continuously, scoring new incoming metrics.

import os
import pickle
import threading
import time

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.svm import OneClassSVM
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

from app.database import (
    fetch_training_data,
    fetch_unprocessed,
    update_anomaly_flag,
    count_records,
)

# -----------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------
MODELS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models"
)
IF_MODEL_PATH  = os.path.join(MODELS_DIR, "isolation_forest.pkl")
SVM_MODEL_PATH = os.path.join(MODELS_DIR, "one_class_svm.pkl")

# We need at least this many records before we can train the models
MIN_TRAINING_RECORDS = 30

# How often (in seconds) the ML engine checks for new data to process
ML_INTERVAL_SECONDS = 10

# contamination = estimated fraction of anomalies in the data
# 0.05 means we expect ~5% of readings to be anomalies
CONTAMINATION = 0.05

_ml_thread = None
_stop_event = threading.Event()

# In-memory references to the loaded/trained models
_if_model  = None   # Isolation Forest pipeline
_svm_model = None   # One-Class SVM pipeline
_models_trained = False


# -----------------------------------------------------------------
# Feature Extraction
# -----------------------------------------------------------------

FEATURE_COLUMNS = [
    "cpu_percent",
    "memory_percent",
    "disk_percent",
    "net_bytes_sent",
    "net_bytes_recv",
]


def _records_to_matrix(records: list) -> np.ndarray:
    """
    Converts a list of database row dicts into a NumPy 2D array
    (matrix) where each row = one time-step, each column = one feature.

    Example output shape: (200, 5)
    → 200 time-steps × 5 features (cpu, mem, disk, net_sent, net_recv)
    """
    matrix = []
    for r in records:
        row = [float(r.get(col, 0)) for col in FEATURE_COLUMNS]
        matrix.append(row)
    return np.array(matrix)


# -----------------------------------------------------------------
# Model Training
# -----------------------------------------------------------------

def train_models():
    """
    Trains both ML models on historical data fetched from the DB.

    Pipeline = StandardScaler → Model
    StandardScaler normalizes each feature to mean=0, std=1.
    This is important because features have very different scales:
      - cpu_percent:   0–100
      - net_bytes_sent: 0–billions
    Without scaling, the model would over-focus on large-value features.
    """
    global _if_model, _svm_model, _models_trained

    records = fetch_training_data(limit=500)

    if len(records) < MIN_TRAINING_RECORDS:
        print(
            f"[ML] Not enough data to train "
            f"({len(records)}/{MIN_TRAINING_RECORDS} records). "
            f"Waiting for more data..."
        )
        return False

    X = _records_to_matrix(records)
    print(f"[ML] Training on {X.shape[0]} records, {X.shape[1]} features...")

    # ── Isolation Forest ──────────────────────────────────────────
    # n_estimators: number of trees (more = better but slower)
    # contamination: expected fraction of outliers
    # random_state: for reproducibility
    _if_model = Pipeline([
        ("scaler", StandardScaler()),
        ("model",  IsolationForest(
            n_estimators=100,
            contamination=CONTAMINATION,
            random_state=42,
        ))
    ])
    _if_model.fit(X)

    # ── One-Class SVM ──────────────────────────────────────────────
    # nu: upper bound on fraction of anomalies (similar to contamination)
    # kernel: 'rbf' (Radial Basis Function) handles non-linear patterns
    # gamma: 'scale' auto-adjusts based on feature variance
    _svm_model = Pipeline([
        ("scaler", StandardScaler()),
        ("model",  OneClassSVM(
            nu=CONTAMINATION,
            kernel="rbf",
            gamma="scale",
        ))
    ])
    _svm_model.fit(X)

    # Save models to disk so they survive server restarts
    _save_models()
    _models_trained = True

    print("[ML] Models trained and saved successfully.")
    return True


def _save_models():
    """Persists trained models to .pkl files using pickle."""
    os.makedirs(MODELS_DIR, exist_ok=True)
    with open(IF_MODEL_PATH,  "wb") as f:
        pickle.dump(_if_model, f)
    with open(SVM_MODEL_PATH, "wb") as f:
        pickle.dump(_svm_model, f)
    print("[ML] Models saved to disk.")


def _load_models():
    """
    Loads pre-trained models from disk if they exist.
    Returns True if both models loaded successfully.
    """
    global _if_model, _svm_model, _models_trained

    if os.path.exists(IF_MODEL_PATH) and os.path.exists(SVM_MODEL_PATH):
        try:
            with open(IF_MODEL_PATH,  "rb") as f:
                _if_model = pickle.load(f)
            with open(SVM_MODEL_PATH, "rb") as f:
                _svm_model = pickle.load(f)
            _models_trained = True
            print("[ML] Pre-trained models loaded from disk.")
            return True
        except Exception as e:
            print(f"[ML] Failed to load models: {e}")
    return False


# -----------------------------------------------------------------
# Anomaly Scoring & Detection
# -----------------------------------------------------------------

def _score_isolation_forest(X: np.ndarray) -> tuple:
    """
    Runs Isolation Forest on a feature matrix X.

    Returns:
        labels: array of +1 (normal) or -1 (anomaly)
        scores: array of raw anomaly scores (more negative = more anomalous)
    """
    labels = _if_model.predict(X)          # +1 or -1
    # decision_function gives the raw score; more negative = more anomalous
    scores = _if_model.decision_function(X)
    return labels, scores


def _score_svm(X: np.ndarray) -> tuple:
    """
    Runs One-Class SVM on a feature matrix X.

    Returns:
        labels: array of +1 (normal) or -1 (anomaly)
        scores: array of raw decision function scores
    """
    labels = _svm_model.predict(X)         # +1 or -1
    scores = _svm_model.decision_function(X)
    return labels, scores


def process_new_records():
    """
    Main detection function — called periodically by the ML loop.

    Steps:
      1. Fetch unprocessed records from DB (those with method='none')
      2. Run both models
      3. ENSEMBLE: a record is an anomaly if EITHER model flags it
      4. Update DB with results
    """
    global _models_trained

    if not _models_trained:
        # Try loading saved models first; train if not available
        if not _load_models():
            train_models()
        return

    records = fetch_unprocessed(batch_size=50)
    if not records:
        return

    X = _records_to_matrix(records)

    try:
        if_labels, if_scores   = _score_isolation_forest(X)
        svm_labels, svm_scores = _score_svm(X)
    except Exception as e:
        print(f"[ML] Scoring error: {e}. Retraining...")
        train_models()
        return

    for i, record in enumerate(records):
        rid = record["id"]

        if_flag  = 1 if if_labels[i]  == -1 else 0
        svm_flag = 1 if svm_labels[i] == -1 else 0

        # Ensemble: anomaly if BOTH models agree (more conservative)
        # Change to (if_flag OR svm_flag) if you want more sensitivity
        is_anomaly = 1 if (if_flag == 1 and svm_flag == 1) else 0

        # Combine scores: average of the two (both normalized similarly)
        combined_score = float((if_scores[i] + svm_scores[i]) / 2.0)

        if is_anomaly:
            method = "isolation_forest+svm"
        else:
            method = "isolation_forest"   # still processed, just normal

        update_anomaly_flag(rid, is_anomaly, combined_score, method)

    anomaly_count = sum(
        1 for i in range(len(records))
        if if_labels[i] == -1 and svm_labels[i] == -1
    )
    print(
        f"[ML] Processed {len(records)} records. "
        f"Anomalies found: {anomaly_count}"
    )


def get_model_status() -> dict:
    """Returns current status of the ML engine for the API."""
    return {
        "trained":        _models_trained,
        "if_model_ready": _if_model  is not None,
        "svm_model_ready": _svm_model is not None,
        "models_path":    MODELS_DIR,
        "min_records_needed": MIN_TRAINING_RECORDS,
        "current_records": count_records(),
    }


# -----------------------------------------------------------------
# Background ML Loop
# -----------------------------------------------------------------

def _ml_loop():
    """
    Background thread that periodically:
      1. Checks if we have enough data to (re)train models
      2. Runs anomaly detection on new unprocessed records
    """
    print(f"[ML] Engine started — running every {ML_INTERVAL_SECONDS}s")

    # Try loading existing models on startup
    _load_models()

    retrain_counter = 0

    while not _stop_event.is_set():
        try:
            total = count_records()

            # Train (or retrain every 100 cycles) when we have enough data
            if total >= MIN_TRAINING_RECORDS:
                if not _models_trained or retrain_counter >= 100:
                    train_models()
                    retrain_counter = 0
                else:
                    retrain_counter += 1

            # Process any new, unscored records
            if _models_trained:
                process_new_records()

        except Exception as e:
            print(f"[ML] Loop error: {e}")

        _stop_event.wait(timeout=ML_INTERVAL_SECONDS)

    print("[ML] Engine stopped.")


def start_ml_engine():
    """Starts the ML background thread. Called once at app startup."""
    global _ml_thread

    if _ml_thread and _ml_thread.is_alive():
        return

    _stop_event.clear()
    _ml_thread = threading.Thread(
        target=_ml_loop,
        daemon=True,
        name="MLEngine"
    )
    _ml_thread.start()


def stop_ml_engine():
    """Stops the ML background thread."""
    _stop_event.set()
    if _ml_thread:
        _ml_thread.join(timeout=5)
