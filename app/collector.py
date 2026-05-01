# app/collector.py
# This module collects real-time system metrics using the 'psutil' library
# and saves them to the SQLite database every few seconds.
#
# psutil (Process and System UTILities) is a cross-platform library for
# retrieving information on running processes and system utilization
# (CPU, memory, disks, network, sensors).

import psutil
import threading
import time
from datetime import datetime, timezone

from app.database import insert_metric

# -----------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------
COLLECTION_INTERVAL_SECONDS = 3   # Collect metrics every 3 seconds
_collector_thread = None           # Reference to background thread
_stop_event = threading.Event()    # Signal to stop the thread


def collect_metrics() -> dict:
    """
    Reads current system metrics using psutil and returns them as a dict.

    Metrics collected:
    ┌──────────────────┬────────────────────────────────────────────────────┐
    │ Metric           │ What it means                                      │
    ├──────────────────┼────────────────────────────────────────────────────┤
    │ cpu_percent      │ % of CPU being used right now (0–100)              │
    │ memory_percent   │ % of RAM being used right now (0–100)              │
    │ disk_percent     │ % of disk space used on root partition (0–100)     │
    │ net_bytes_sent   │ Cumulative bytes sent since system boot            │
    │ net_bytes_recv   │ Cumulative bytes received since system boot        │
    └──────────────────┴────────────────────────────────────────────────────┘
    """
    # --- CPU ---
    # interval=1 means psutil waits 1 second to give an accurate reading.
    # Without interval, it returns 0.0 on the first call.
    cpu = psutil.cpu_percent(interval=1)

    # --- Memory ---
    memory = psutil.virtual_memory()
    mem_percent = memory.percent

    # --- Disk ---
    # We check the root partition ('/') on Linux/Mac; on Windows use 'C:\\'
    try:
        disk = psutil.disk_usage("/")
        disk_percent = disk.percent
    except Exception:
        try:
            disk = psutil.disk_usage("C:\\")
            disk_percent = disk.percent
        except Exception:
            disk_percent = 0.0

    # --- Network ---
    net = psutil.net_io_counters()
    net_sent = float(net.bytes_sent)
    net_recv = float(net.bytes_recv)

    # --- Timestamp ---
    # ISO 8601 format: "2024-12-01T14:30:00+00:00"
    timestamp = datetime.now(timezone.utc).isoformat()

    return {
        "timestamp":      timestamp,
        "cpu_percent":    cpu,
        "memory_percent": mem_percent,
        "disk_percent":   disk_percent,
        "net_bytes_sent": net_sent,
        "net_bytes_recv": net_recv,
    }


def _collection_loop():
    """
    Background loop that runs in a separate thread.
    Every COLLECTION_INTERVAL_SECONDS it:
      1. Collects metrics
      2. Saves them to the database
      3. Emits a WebSocket event so the browser updates instantly
    """
    print(f"[Collector] Started — collecting every {COLLECTION_INTERVAL_SECONDS}s")

    # Import here to avoid circular imports
    from app import socketio

    while not _stop_event.is_set():
        try:
            metrics = collect_metrics()
            insert_metric(metrics)

            # Emit to all connected WebSocket clients
            # The browser's JavaScript listens for 'new_metrics' events
            socketio.emit("new_metrics", metrics)

            print(
                f"[Collector] CPU={metrics['cpu_percent']:.1f}% "
                f"MEM={metrics['memory_percent']:.1f}% "
                f"DISK={metrics['disk_percent']:.1f}%"
            )

        except Exception as e:
            print(f"[Collector] Error: {e}")

        # Wait before next collection.
        # We use _stop_event.wait() instead of time.sleep() so we can
        # interrupt the wait immediately when stopping.
        _stop_event.wait(timeout=COLLECTION_INTERVAL_SECONDS)

    print("[Collector] Stopped.")


def start_collector():
    """
    Starts the background data collection thread.
    Called once when the Flask application starts.
    """
    global _collector_thread

    if _collector_thread and _collector_thread.is_alive():
        print("[Collector] Already running.")
        return

    _stop_event.clear()
    _collector_thread = threading.Thread(
        target=_collection_loop,
        daemon=True,       # daemon=True means it stops when main program exits
        name="MetricsCollector"
    )
    _collector_thread.start()


def stop_collector():
    """
    Signals the collection loop to stop.
    Called when the application shuts down.
    """
    _stop_event.set()
    if _collector_thread:
        _collector_thread.join(timeout=5)
    print("[Collector] Shutdown complete.")
