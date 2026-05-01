# app/database.py
# Handles everything related to the SQLite database:
#   - Creating the database and table
#   - Inserting new metric readings
#   - Fetching data for the API and ML engine

import sqlite3
import os

# -----------------------------------------------------------------
# Database file path — stored in the 'data/' folder of the project
# -----------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "metrics.db")


def get_connection():
    """
    Opens and returns a connection to the SQLite database.
    'check_same_thread=False' is needed because Flask can call
    this from multiple threads.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # lets us access columns by name like a dict
    return conn


def init_db():
    """
    Creates the 'system_metrics' table if it does not already exist.
    Call this once when the application starts.

    TABLE SCHEMA:
    ┌─────────────────┬──────────────────────────────────────────────────────┐
    │ Column          │ Description                                          │
    ├─────────────────┼──────────────────────────────────────────────────────┤
    │ id              │ Auto-incrementing primary key                        │
    │ timestamp       │ When the reading was taken (ISO format string)       │
    │ cpu_percent     │ CPU usage 0-100%                                     │
    │ memory_percent  │ RAM usage 0-100%                                     │
    │ disk_percent    │ Disk usage 0-100%                                    │
    │ net_bytes_sent  │ Total bytes sent since boot (bytes)                  │
    │ net_bytes_recv  │ Total bytes received since boot (bytes)              │
    │ is_anomaly      │ 1 = anomaly detected, 0 = normal (set by ML engine) │
    │ anomaly_score   │ Raw anomaly score from ML model (float)              │
    │ anomaly_method  │ Which ML model flagged it ('isolation_forest', etc.) │
    └─────────────────┴──────────────────────────────────────────────────────┘
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_metrics (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT    NOT NULL,
            cpu_percent     REAL    NOT NULL,
            memory_percent  REAL    NOT NULL,
            disk_percent    REAL    NOT NULL,
            net_bytes_sent  REAL    NOT NULL,
            net_bytes_recv  REAL    NOT NULL,
            is_anomaly      INTEGER DEFAULT 0,
            anomaly_score   REAL    DEFAULT 0.0,
            anomaly_method  TEXT    DEFAULT 'none'
        )
    """)

    conn.commit()
    conn.close()
    print("[DB] Database initialized successfully.")


def insert_metric(metric: dict):
    """
    Inserts one row of system metrics into the database.

    Args:
        metric (dict): Keys must match the column names:
            timestamp, cpu_percent, memory_percent,
            disk_percent, net_bytes_sent, net_bytes_recv
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO system_metrics
            (timestamp, cpu_percent, memory_percent,
             disk_percent, net_bytes_sent, net_bytes_recv)
        VALUES
            (:timestamp, :cpu_percent, :memory_percent,
             :disk_percent, :net_bytes_sent, :net_bytes_recv)
    """, metric)

    conn.commit()
    conn.close()


def update_anomaly_flag(record_id: int, is_anomaly: int,
                        score: float, method: str):
    """
    After the ML engine processes a batch of records, we call this
    to mark which ones are anomalies.

    Args:
        record_id  : The primary key (id) of the row to update
        is_anomaly : 1 if anomaly, 0 if normal
        score      : The raw anomaly score from the model
        method     : Name of the ML model used
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE system_metrics
        SET is_anomaly = ?, anomaly_score = ?, anomaly_method = ?
        WHERE id = ?
    """, (is_anomaly, score, method, record_id))

    conn.commit()
    conn.close()


def fetch_latest(limit: int = 1):
    """
    Returns the most recent 'limit' rows from the database.
    Used by /api/data endpoint.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM system_metrics
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def fetch_history(limit: int = 200):
    """
    Returns the last 'limit' records in chronological order.
    Used by /api/history endpoint to populate the dashboard charts.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM system_metrics
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    # Reverse so oldest is first (for correct chart ordering)
    return list(reversed(rows))


def fetch_anomalies(limit: int = 50):
    """
    Returns only rows that were flagged as anomalies.
    Used by /api/anomalies endpoint.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM system_metrics
        WHERE is_anomaly = 1
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def fetch_unprocessed(batch_size: int = 50):
    """
    Returns rows where the ML engine hasn't run yet
    (anomaly_method = 'none'). Used by the ML engine to
    grab new data for processing.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM system_metrics
        WHERE anomaly_method = 'none'
        ORDER BY id ASC
        LIMIT ?
    """, (batch_size,))

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def fetch_training_data(limit: int = 500):
    """
    Returns a large batch of recent records for training/retraining
    the ML models. We need enough data to learn 'normal' behaviour.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT cpu_percent, memory_percent, disk_percent,
               net_bytes_sent, net_bytes_recv
        FROM system_metrics
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def count_records():
    """Returns total number of rows in the table."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM system_metrics")
    result = cursor.fetchone()
    conn.close()
    return result["cnt"] if result else 0
