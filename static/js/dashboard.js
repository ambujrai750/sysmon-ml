/**
 * dashboard.js
 * ─────────────────────────────────────────────────────────────────
 * Handles all frontend logic for the SysMon-ML dashboard:
 *
 *  1. WebSocket connection (real-time updates via Socket.IO)
 *  2. HTTP polling fallback (if WebSocket fails)
 *  3. Chart.js time-series charts (CPU, Memory, Disk, Network)
 *  4. Anomaly table rendering
 *  5. ML status panel updates
 *  6. Stat card updates with animated values
 * ─────────────────────────────────────────────────────────────────
 */

// ================================================================
// CONFIGURATION
// ================================================================
const CONFIG = {
  HISTORY_LIMIT:        150,    // Number of data points to show on charts
  POLLING_INTERVAL_MS:  4000,   // Fallback polling every 4 seconds
  MAX_TABLE_ROWS:       20,     // Max rows to show in anomaly table
  ANOMALY_REFRESH_MS:   8000,   // Refresh anomaly table every 8 seconds
};

// ================================================================
// CHART.JS GLOBAL DEFAULTS
// Register the needed components explicitly (Chart.js v4 tree-shaking)
// ================================================================
Chart.defaults.color           = '#7a9bb5';
Chart.defaults.borderColor     = '#1e2d3d';
Chart.defaults.font.family     = "'JetBrains Mono', monospace";
Chart.defaults.font.size       = 11;
Chart.defaults.plugins.legend.display = false;
Chart.defaults.animation.duration = 300;

// ================================================================
// STATE
// ================================================================
const state = {
  charts:          {},          // { cpu: Chart, memory: Chart, ... }
  historyData:     [],          // Array of metric objects from /api/history
  socket:          null,
  isConnected:     false,
  pollingTimer:    null,
  anomalyTimer:    null,
  totalRecords:    0,
  totalAnomalies:  0,
};

// ================================================================
// DOM ELEMENT REFERENCES
// ================================================================
const el = {
  cpuVal:       document.getElementById('cpu-val'),
  memVal:       document.getElementById('mem-val'),
  diskVal:      document.getElementById('disk-val'),
  netVal:       document.getElementById('net-val'),

  cpuBar:       document.getElementById('cpu-bar'),
  memBar:       document.getElementById('mem-bar'),
  diskBar:      document.getElementById('disk-bar'),

  cpuCurrent:   document.getElementById('cpu-current'),
  memCurrent:   document.getElementById('mem-current'),
  diskCurrent:  document.getElementById('disk-current'),
  netCurrent:   document.getElementById('net-current'),

  statusDot:    document.getElementById('status-dot'),
  statusText:   document.getElementById('status-text'),
  headerTime:   document.getElementById('header-time'),

  alertBanner:  document.getElementById('alert-banner'),
  alertMsg:     document.getElementById('alert-msg'),

  anomalyBody:  document.getElementById('anomaly-tbody'),
  anomalyBadge: document.getElementById('anomaly-badge'),

  mlTrained:    document.getElementById('ml-trained'),
  mlTotalRec:   document.getElementById('ml-total-rec'),
  mlTotalAnom:  document.getElementById('ml-total-anom'),
  mlIfReady:    document.getElementById('ml-if-ready'),
  mlSvmReady:   document.getElementById('ml-svm-ready'),

  retrainBtn:   document.getElementById('retrain-btn'),

  cpuCard:      document.getElementById('card-cpu'),
  memCard:      document.getElementById('card-memory'),
  diskCard:     document.getElementById('card-disk'),
  netCard:      document.getElementById('card-network'),
};

// ================================================================
// CHART FACTORY
// Creates a Chart.js line chart with the SysMon style
// ================================================================
function createChart(canvasId, color, label, unit) {
  const ctx = document.getElementById(canvasId).getContext('2d');

  // Gradient fill under the line
  const gradient = ctx.createLinearGradient(0, 0, 0, 180);
  gradient.addColorStop(0,   hexToRgba(color, 0.3));
  gradient.addColorStop(1,   hexToRgba(color, 0.0));

  return new Chart(ctx, {
    type: 'line',
    data: {
      labels:   [],
      datasets: [{
        label:            label,
        data:             [],
        borderColor:      color,
        backgroundColor:  gradient,
        borderWidth:      2,
        pointRadius:      0,          // No dots by default
        pointHoverRadius: 5,
        pointHoverBackgroundColor: color,
        fill:             true,
        tension:          0.4,        // Smooth curves
      },
      // Anomaly overlay dataset — shows red dots where anomalies occurred
      {
        label:           'Anomaly',
        data:            [],
        borderColor:     'transparent',
        backgroundColor: '#ff3366',
        pointRadius:     6,
        pointStyle:      'circle',
        pointBorderColor: '#ff3366',
        pointBorderWidth: 2,
        pointBackgroundColor: 'rgba(255,51,102,0.3)',
        showLine:        false,
        fill:            false,
      }]
    },
    options: {
      responsive:          true,
      maintainAspectRatio: false,
      interaction: {
        intersect: false,
        mode:      'index',
      },
      scales: {
        x: {
          grid:   { display: false },
          ticks:  { maxTicksLimit: 8, maxRotation: 0 },
        },
        y: {
          grid: {
            color: 'rgba(30, 45, 61, 0.7)',
            drawBorder: false,
          },
          ticks: { callback: v => v + (unit || '') },
          beginAtZero: true,
        }
      },
      plugins: {
        tooltip: {
          callbacks: {
            label: ctx => ` ${ctx.parsed.y.toFixed(1)}${unit || ''}`,
          },
          backgroundColor: '#111820',
          borderColor:     '#1e2d3d',
          borderWidth:     1,
          titleColor:      '#e0eaf5',
          bodyColor:       '#7a9bb5',
          padding:         10,
        }
      }
    }
  });
}

// ================================================================
// INITIALIZE ALL CHARTS
// ================================================================
function initCharts() {
  state.charts.cpu    = createChart('chart-cpu',    '#00aaff', 'CPU',    '%');
  state.charts.memory = createChart('chart-memory', '#00ff9d', 'Memory', '%');
  state.charts.disk   = createChart('chart-disk',   '#ffd700', 'Disk',   '%');
  state.charts.net    = createChart('chart-net',    '#c084fc', 'Network', ' MB');
}

// ================================================================
// UPDATE CHARTS with new history data
// ================================================================
function updateCharts(historyData) {
  if (!historyData || historyData.length === 0) return;

  // Extract labels (formatted time strings)
  const labels = historyData.map(d => formatTime(d.timestamp));

  // Extract metric arrays
  const cpuData    = historyData.map(d => d.cpu_percent);
  const memData    = historyData.map(d => d.memory_percent);
  const diskData   = historyData.map(d => d.disk_percent);
  // Convert bytes → megabytes for readability
  const netData    = historyData.map(d =>
    ((d.net_bytes_sent + d.net_bytes_recv) / 1e6).toFixed(2)
  );

  // Anomaly scatter points — only add a value where is_anomaly == 1
  const cpuAnom    = historyData.map(d => d.is_anomaly ? d.cpu_percent    : null);
  const memAnom    = historyData.map(d => d.is_anomaly ? d.memory_percent : null);
  const diskAnom   = historyData.map(d => d.is_anomaly ? d.disk_percent   : null);
  const netAnom    = historyData.map(d => d.is_anomaly
    ? ((d.net_bytes_sent + d.net_bytes_recv) / 1e6).toFixed(2) : null);

  function applyData(chart, mainData, anomData) {
    chart.data.labels               = labels;
    chart.data.datasets[0].data     = mainData;
    chart.data.datasets[1].data     = anomData;
    chart.update('none');  // 'none' = skip animation for continuous updates
  }

  applyData(state.charts.cpu,    cpuData,  cpuAnom);
  applyData(state.charts.memory, memData,  memAnom);
  applyData(state.charts.disk,   diskData, diskAnom);
  applyData(state.charts.net,    netData,  netAnom);
}

// ================================================================
// UPDATE STAT CARDS
// ================================================================
function updateStatCards(metric) {
  if (!metric) return;

  const cpu  = metric.cpu_percent   ?? 0;
  const mem  = metric.memory_percent ?? 0;
  const disk = metric.disk_percent  ?? 0;
  const net  = ((metric.net_bytes_sent + metric.net_bytes_recv) / 1e6).toFixed(1);

  // Update displayed values
  animateValue(el.cpuVal,  cpu.toFixed(1));
  animateValue(el.memVal,  mem.toFixed(1));
  animateValue(el.diskVal, disk.toFixed(1));
  el.netVal.textContent = net;

  // Update progress bars
  el.cpuBar.style.width  = `${Math.min(cpu, 100)}%`;
  el.memBar.style.width  = `${Math.min(mem, 100)}%`;
  el.diskBar.style.width = `${Math.min(disk, 100)}%`;

  // Update current value labels on chart panels
  if (el.cpuCurrent)  el.cpuCurrent.textContent  = cpu.toFixed(1)  + '%';
  if (el.memCurrent)  el.memCurrent.textContent  = mem.toFixed(1)  + '%';
  if (el.diskCurrent) el.diskCurrent.textContent = disk.toFixed(1) + '%';
  if (el.netCurrent)  el.netCurrent.textContent  = net + ' MB';

  // Flash anomaly highlight on cards
  const isAnom = metric.is_anomaly === 1;
  [el.cpuCard, el.memCard, el.diskCard, el.netCard].forEach(card => {
    card?.classList.toggle('anomaly-active', isAnom);
  });

  // Show alert banner for anomalies
  if (isAnom) {
    showAlert(`⚠ Anomaly detected at ${formatTime(metric.timestamp)} — Score: ${metric.anomaly_score?.toFixed(4)}`);
  }
}

// ================================================================
// ANOMALY TABLE
// ================================================================
function renderAnomalyTable(anomalies) {
  if (!el.anomalyBody) return;

  const count = anomalies?.length ?? 0;
  if (el.anomalyBadge) el.anomalyBadge.textContent = count;

  if (count === 0) {
    el.anomalyBody.innerHTML = `
      <tr>
        <td colspan="6" class="no-anomalies">
          ✅  No anomalies detected yet
        </td>
      </tr>`;
    return;
  }

  const rows = anomalies.slice(0, CONFIG.MAX_TABLE_ROWS).map((a, idx) => `
    <tr class="${idx === 0 ? 'row-flash' : ''}">
      <td>${formatTime(a.timestamp)}</td>
      <td class="anomaly-cpu">${a.cpu_percent?.toFixed(1)}%</td>
      <td class="anomaly-mem">${a.memory_percent?.toFixed(1)}%</td>
      <td class="anomaly-disk">${a.disk_percent?.toFixed(1)}%</td>
      <td>${((a.net_bytes_sent + a.net_bytes_recv) / 1e6).toFixed(2)} MB</td>
      <td><span class="anomaly-flag">ANOMALY</span></td>
    </tr>
  `).join('');

  el.anomalyBody.innerHTML = rows;
}

// ================================================================
// ML STATUS PANEL
// ================================================================
function updateMLStatus(status) {
  if (!status) return;

  const setVal = (el, val, cls) => {
    if (!el) return;
    el.textContent = val;
    el.className = `ml-status-val ${cls}`;
  };

  const trained = status.ml?.trained;
  setVal(el.mlTrained,  trained ? 'ACTIVE'  : 'TRAINING…', trained ? 'ready' : 'waiting');
  setVal(el.mlIfReady,  status.ml?.if_model_ready  ? 'READY' : 'NOT READY',
         status.ml?.if_model_ready  ? 'ready' : 'waiting');
  setVal(el.mlSvmReady, status.ml?.svm_model_ready ? 'READY' : 'NOT READY',
         status.ml?.svm_model_ready ? 'ready' : 'waiting');

  if (el.mlTotalRec)  el.mlTotalRec.textContent  = status.total_records   ?? '—';
  if (el.mlTotalAnom) el.mlTotalAnom.textContent = status.total_anomalies ?? '—';
}

// ================================================================
// DATA FETCHING
// ================================================================
async function fetchHistory() {
  try {
    const res  = await fetch(`/api/history?limit=${CONFIG.HISTORY_LIMIT}`);
    const json = await res.json();
    if (json.status === 'ok') {
      state.historyData = json.data;
      updateCharts(json.data);
      if (json.data.length > 0) {
        updateStatCards(json.data[json.data.length - 1]);
      }
    }
  } catch (e) {
    console.warn('[Dashboard] fetchHistory error:', e);
  }
}

async function fetchAnomalies() {
  try {
    const res  = await fetch('/api/anomalies?limit=50');
    const json = await res.json();
    if (json.status === 'ok') {
      renderAnomalyTable(json.anomalies);
    }
  } catch (e) {
    console.warn('[Dashboard] fetchAnomalies error:', e);
  }
}

async function fetchStatus() {
  try {
    const res  = await fetch('/api/status');
    const json = await res.json();
    if (json.status === 'ok') {
      updateMLStatus(json);
    }
  } catch (e) {
    console.warn('[Dashboard] fetchStatus error:', e);
  }
}

// ================================================================
// WEBSOCKET (Socket.IO)
// ================================================================
function initWebSocket() {
  try {
    // Socket.IO is loaded from the CDN in index.html
    // It auto-connects to the same host/port as the page
    state.socket = io({
      transports: ['websocket', 'polling'],
      reconnectionAttempts: 10,
    });

    state.socket.on('connect', () => {
      console.log('[WS] Connected:', state.socket.id);
      state.isConnected = true;
      setConnectionStatus(true);

      // Stop the polling fallback
      clearInterval(state.pollingTimer);
      state.pollingTimer = null;
    });

    state.socket.on('disconnect', () => {
      console.warn('[WS] Disconnected.');
      state.isConnected = false;
      setConnectionStatus(false);

      // Fall back to polling
      startPolling();
    });

    // ── Listen for real-time metric events ─────────────────────
    state.socket.on('new_metrics', (metric) => {
      console.debug('[WS] new_metrics:', metric);

      // Add to history array (keep last HISTORY_LIMIT items)
      state.historyData.push(metric);
      if (state.historyData.length > CONFIG.HISTORY_LIMIT) {
        state.historyData.shift();
      }

      updateCharts(state.historyData);
      updateStatCards(metric);
    });

  } catch (e) {
    console.error('[WS] Socket.IO unavailable:', e);
    startPolling();
  }
}

// ================================================================
// POLLING FALLBACK (when WebSocket is not available)
// ================================================================
function startPolling() {
  if (state.pollingTimer) return;  // Already polling

  console.log('[Dashboard] Starting HTTP polling fallback...');
  state.pollingTimer = setInterval(() => {
    fetchHistory();
  }, CONFIG.POLLING_INTERVAL_MS);
}

// ================================================================
// RETRAIN BUTTON
// ================================================================
if (el.retrainBtn) {
  el.retrainBtn.addEventListener('click', async () => {
    el.retrainBtn.disabled = true;
    el.retrainBtn.textContent = 'RETRAINING…';

    try {
      const res  = await fetch('/api/retrain', { method: 'POST' });
      const json = await res.json();
      el.retrainBtn.textContent = json.status === 'ok' ? '✓ RETRAINED' : '✗ FAILED';
      setTimeout(() => {
        el.retrainBtn.textContent = 'RETRAIN MODELS';
        el.retrainBtn.disabled = false;
      }, 3000);
      fetchStatus();
    } catch (e) {
      el.retrainBtn.textContent = '✗ ERROR';
      setTimeout(() => {
        el.retrainBtn.textContent = 'RETRAIN MODELS';
        el.retrainBtn.disabled = false;
      }, 3000);
    }
  });
}

// ================================================================
// UTILITY FUNCTIONS
// ================================================================

/** Formats an ISO timestamp to a short HH:MM:SS string */
function formatTime(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString('en-US', { hour12: false });
  } catch { return iso; }
}

/** Converts a hex color + alpha to rgba() string */
function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/** Smoothly updates a number display (simple replace for now) */
function animateValue(element, newVal) {
  if (!element) return;
  element.textContent = newVal;
}

/** Shows the connection status indicator in the header */
function setConnectionStatus(online) {
  if (el.statusDot)  el.statusDot.className  = `status-dot${online ? '' : ' offline'}`;
  if (el.statusText) el.statusText.textContent = online ? 'LIVE' : 'OFFLINE';
}

/** Shows a dismissable alert banner at the top of the dashboard */
function showAlert(message) {
  if (!el.alertBanner || !el.alertMsg) return;
  el.alertMsg.textContent = message;
  el.alertBanner.classList.add('show');
  // Auto-hide after 6 seconds
  setTimeout(() => el.alertBanner.classList.remove('show'), 6000);
}

/** Updates the live clock in the header */
function updateClock() {
  if (el.headerTime) {
    el.headerTime.textContent = new Date().toLocaleTimeString('en-US', {
      hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
  }
}

// ================================================================
// BOOTSTRAP — runs when the page loads
// ================================================================
document.addEventListener('DOMContentLoaded', () => {
  console.log('[Dashboard] Initializing SysMon-ML Dashboard...');

  // 1. Build all Chart.js charts
  initCharts();

  // 2. Load initial data from REST API
  fetchHistory();
  fetchAnomalies();
  fetchStatus();

  // 3. Connect WebSocket for real-time updates
  initWebSocket();

  // 4. Periodically refresh anomaly table + ML status
  state.anomalyTimer = setInterval(() => {
    fetchAnomalies();
    fetchStatus();
  }, CONFIG.ANOMALY_REFRESH_MS);

  // 5. Start the header clock
  setInterval(updateClock, 1000);
  updateClock();

  console.log('[Dashboard] Ready.');
});
