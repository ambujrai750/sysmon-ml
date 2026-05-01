# 🖥️ SysMon-ML
### Real-Time System Resource Monitoring & Anomaly Detection

A production-grade Python web application that monitors your computer's CPU, Memory, Disk, and Network in real time — and uses Machine Learning to automatically detect unusual behaviour.

---

## 🗂️ Project Structure

```
sysmon-ml/
├── app/
│   ├── __init__.py        # Flask app factory + SocketIO setup
│   ├── collector.py       # psutil data collection (background thread)
│   ├── database.py        # SQLite DB: schema, insert, fetch
│   ├── ml_engine.py       # Isolation Forest + One-Class SVM
│   └── routes.py          # Flask API endpoints
├── static/
│   ├── css/style.css      # Dark-theme dashboard styles
│   └── js/dashboard.js   # Chart.js charts + WebSocket client
├── templates/
│   └── index.html         # Dashboard HTML page
├── data/
│   └── metrics.db         # SQLite database (auto-created)
├── models/
│   └── *.pkl              # Saved ML models (auto-created)
├── main.py                # Entry point — run this!
├── requirements.txt       # Python dependencies
├── .gitignore
└── README.md
```

---

## ⚙️ Setup & Installation (Windows, beginner-friendly)

### Prerequisites
- Python 3.9 or higher → https://www.python.org/downloads/
- Check by opening Command Prompt and typing: `python --version`

### Step 1 — Clone or Download the project
```bash
git clone https://github.com/YOUR_USERNAME/sysmon-ml.git
cd sysmon-ml
```

### Step 2 — Create a Virtual Environment
A virtual environment keeps this project's packages separate from your system Python.

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Mac / Linux
python3 -m venv venv
source venv/bin/activate
```

You'll see `(venv)` at the start of your prompt — that means it's active.

### Step 3 — Install Dependencies
```bash
pip install -r requirements.txt
```
This installs: Flask, Flask-SocketIO, psutil, scikit-learn, numpy, pandas, eventlet.

### Step 4 — Run the Application
```bash
python main.py
```

Open your browser and go to: **http://localhost:5000**

---

## 📊 API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Dashboard web page |
| `/api/data` | GET | Latest 1 metric reading |
| `/api/history?limit=200` | GET | Historical metrics (JSON) |
| `/api/anomalies?limit=50` | GET | All detected anomalies |
| `/api/status` | GET | ML engine status |
| `/api/retrain` | POST | Force model retraining |

---

## 🧠 How the ML Works

### Isolation Forest
- Builds 100 random decision trees
- Data points that are easy to isolate (few splits needed) = anomalies
- Best for: catching sudden spikes or unusual patterns

### One-Class SVM
- Learns the "normal" boundary around your data
- Anything outside the boundary = anomaly
- Best for: stable systems with consistent normal behaviour

### Ensemble (Both Together)
The system flags a reading as an anomaly **only if BOTH models agree**.
This reduces false positives significantly.

---

## 🧪 Testing — How to Simulate Anomalies

### Method 1: Stress your CPU
```bash
# Windows PowerShell
while ($true) { [System.Math]::Sqrt(999999) }

# Linux/Mac
stress --cpu 4 --timeout 30
# or
yes > /dev/null &
```

### Method 2: Fill RAM temporarily
Open many browser tabs, run a video, open large files.

### Method 3: Inject a fake anomaly directly into the database
```python
# Run this in a Python shell
import sqlite3
conn = sqlite3.connect('data/metrics.db')
conn.execute("""
    INSERT INTO system_metrics
    (timestamp, cpu_percent, memory_percent, disk_percent,
     net_bytes_sent, net_bytes_recv)
    VALUES (datetime('now'), 99.9, 98.5, 95.0, 9999999999, 9999999999)
""")
conn.commit()
conn.close()
```

Wait ~10 seconds for the ML engine to process it. It should appear in the Anomalies table.

---

## 🚀 Deployment

### Run Locally
```bash
python main.py
```

### Upload to GitHub
```bash
git init
git add .
git commit -m "Initial commit: SysMon-ML dashboard"
git remote add origin https://github.com/YOUR_USERNAME/sysmon-ml.git
git push -u origin main
```

### Deploy to Render (free hosting)
1. Push your code to GitHub
2. Go to https://render.com → New → Web Service
3. Connect your GitHub repo
4. Set:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python main.py`
   - Environment: `DEBUG=false`
5. Click Deploy

**Note:** On cloud deployment, psutil will monitor the cloud server's resources, not your local machine.

---

## 🛠️ Configuration

You can adjust these values in the source files:

| Setting | File | Default | Description |
|---|---|---|---|
| `COLLECTION_INTERVAL_SECONDS` | `collector.py` | 3 | How often to collect metrics |
| `ML_INTERVAL_SECONDS` | `ml_engine.py` | 10 | How often ML runs |
| `MIN_TRAINING_RECORDS` | `ml_engine.py` | 30 | Records needed before training |
| `CONTAMINATION` | `ml_engine.py` | 0.05 | Expected anomaly fraction (5%) |
| `HISTORY_LIMIT` | `dashboard.js` | 150 | Chart data points shown |

---

## 🤝 Contributing
Pull requests welcome! Open an issue for bugs or feature suggestions.

---

*Built with Flask · psutil · scikit-learn · Chart.js · Socket.IO*
