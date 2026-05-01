# main.py
# ─────────────────────────────────────────────────────────────────
# APPLICATION ENTRY POINT
# Run this file to start the entire system:
#   python main.py
#
# What happens when you run this:
#   1. Flask app is created
#   2. SQLite database is initialized
#   3. Data collection thread starts (psutil, every 3s)
#   4. ML engine thread starts (anomaly detection, every 10s)
#   5. Web server starts on http://localhost:5000
# ─────────────────────────────────────────────────────────────────

import os
from app import create_app, socketio
from app.database import init_db
from app.collector import start_collector
from app.ml_engine import start_ml_engine

# Create the Flask application using the factory function
app = create_app()


def main():
    print("=" * 60)
    print("  🖥️  SysMon-ML  |  Real-Time Anomaly Detection")
    print("=" * 60)

    # ── Step 1: Initialize the database ───────────────────────────
    print("\n[1/4] Initializing database...")
    init_db()

    # ── Step 2: Start the data collector ──────────────────────────
    print("\n[2/4] Starting data collector (psutil)...")
    start_collector()

    # ── Step 3: Start the ML engine ───────────────────────────────
    print("\n[3/4] Starting ML anomaly detection engine...")
    start_ml_engine()

    # ── Step 4: Start the web server ──────────────────────────────
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("DEBUG", "true").lower() == "true"

    print(f"\n[4/4] Starting web server on http://localhost:{port}")
    print("\n" + "=" * 60)
    print(f"  ✅  Dashboard: http://localhost:{port}")
    print(f"  📊  API Data:  http://localhost:{port}/api/data")
    print(f"  📜  History:   http://localhost:{port}/api/history")
    print(f"  🚨  Anomalies: http://localhost:{port}/api/anomalies")
    print(f"  ℹ️   Status:    http://localhost:{port}/api/status")
    print("=" * 60 + "\n")

    # Use socketio.run() instead of app.run() to enable WebSockets
    socketio.run(
        app,
        host="0.0.0.0",    # Accept connections from any IP
        port=port,
        debug=debug,
        use_reloader=False, # Disable reloader (it would start two collector threads)
    )


if __name__ == "__main__":
    main()
