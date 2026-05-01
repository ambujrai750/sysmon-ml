# app/routes.py
# Defines all HTTP API endpoints (routes) for the Flask application.
#
# API Endpoints:
# ┌────────────────────┬────────────────────────────────────────────────────┐
# │ Endpoint           │ Description                                        │
# ├────────────────────┼────────────────────────────────────────────────────┤
# │ GET /              │ Serves the main dashboard HTML page                │
# │ GET /api/data      │ Latest 1 metric reading (JSON)                     │
# │ GET /api/history   │ Last N readings in chronological order (JSON)      │
# │ GET /api/anomalies │ All anomaly records (JSON)                         │
# │ GET /api/status    │ ML engine status + record counts (JSON)            │
# │ POST /api/retrain  │ Force retrain the ML models (JSON)                 │
# └────────────────────┴────────────────────────────────────────────────────┘

from flask import Blueprint, jsonify, render_template, request
from app.database import (
    fetch_latest,
    fetch_history,
    fetch_anomalies,
    count_records,
)
from app.ml_engine import get_model_status, train_models

# Blueprint = a mini-app within Flask. Helps organize routes.
main_bp = Blueprint("main", __name__)


# -----------------------------------------------------------------
# Dashboard Page
# -----------------------------------------------------------------

@main_bp.route("/")
def index():
    """
    Serves the main HTML dashboard.
    Flask looks for 'index.html' in the 'templates/' folder.
    """
    return render_template("index.html")


# -----------------------------------------------------------------
# API: Latest Data
# -----------------------------------------------------------------

@main_bp.route("/api/data")
def api_latest_data():
    """
    Returns the single most recent metric reading.

    Query params:
        limit (int): How many recent records to return. Default = 1.

    Response example:
    {
        "status": "ok",
        "data": [{
            "id": 42,
            "timestamp": "2024-12-01T14:30:00+00:00",
            "cpu_percent": 34.5,
            "memory_percent": 61.2,
            "disk_percent": 45.0,
            "net_bytes_sent": 1234567,
            "net_bytes_recv": 9876543,
            "is_anomaly": 0,
            "anomaly_score": -0.12,
            "anomaly_method": "isolation_forest"
        }]
    }
    """
    limit = request.args.get("limit", 1, type=int)
    data = fetch_latest(limit=limit)
    return jsonify({"status": "ok", "data": data})


# -----------------------------------------------------------------
# API: History
# -----------------------------------------------------------------

@main_bp.route("/api/history")
def api_history():
    """
    Returns the last N metric readings in chronological order.
    Used by the dashboard to draw time-series charts.

    Query params:
        limit (int): Number of records to return. Default = 200.
    """
    limit = request.args.get("limit", 200, type=int)
    # Cap at 1000 to prevent huge payloads
    limit = min(limit, 1000)
    data = fetch_history(limit=limit)
    return jsonify({"status": "ok", "count": len(data), "data": data})


# -----------------------------------------------------------------
# API: Anomalies
# -----------------------------------------------------------------

@main_bp.route("/api/anomalies")
def api_anomalies():
    """
    Returns records that were flagged as anomalies by the ML engine.

    Query params:
        limit (int): Number of anomaly records to return. Default = 50.
    """
    limit = request.args.get("limit", 50, type=int)
    data = fetch_anomalies(limit=limit)
    return jsonify({
        "status": "ok",
        "count": len(data),
        "anomalies": data,
    })


# -----------------------------------------------------------------
# API: System Status
# -----------------------------------------------------------------

@main_bp.route("/api/status")
def api_status():
    """
    Returns the current status of the monitoring system, including:
    - Total records stored
    - ML model readiness
    - Number of anomalies detected
    """
    ml_status = get_model_status()
    anomalies = fetch_anomalies(limit=1000)

    return jsonify({
        "status": "ok",
        "total_records": count_records(),
        "total_anomalies": len(anomalies),
        "ml": ml_status,
    })


# -----------------------------------------------------------------
# API: Force Retrain
# -----------------------------------------------------------------

@main_bp.route("/api/retrain", methods=["POST"])
def api_retrain():
    """
    Forces the ML models to retrain immediately using the latest data.
    Useful after the system has collected a lot of new data, or
    if you want to reset the 'normal' baseline.
    """
    success = train_models()
    if success:
        return jsonify({"status": "ok", "message": "Models retrained successfully."})
    else:
        total = count_records()
        from app.ml_engine import MIN_TRAINING_RECORDS
        return jsonify({
            "status": "error",
            "message": (
                f"Not enough data. Have {total} records, "
                f"need {MIN_TRAINING_RECORDS}."
            )
        }), 400
