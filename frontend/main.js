let activeUPlots = [];
let chartCanvasRefs = []; // [{canvas, title}]
let compareSources = [];
let lastData = null;
let isBusy = false;
let activeAbort = null;
let lastSource = null;
let lastDuration = null;

const TRACK_COLORS = [
  "#1976D2", "#D32F2F", "#388E3C", "#F57C00", "#7B1FA2", "#00838F"
];

// Dark mode colors (brighter for dark backgrounds)
const TRACK_COLORS_DARK = [
  "#64b5f6", "#ef5350", "#66bb6a", "#ffa726", "#ce93d8", "#4dd0e1"
];

// Theme management: "light" | "dark" | "auto" (follows system)
// _themeMode stores the user's preference, _appliedTheme is what's active
var _themeMode = "auto";

function _systemDark() {
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function isDark() {
  return document.documentElement.getAttribute("data-theme") === "dark";
}

function getThemeColors() {
  var dark = isDark();
  return {
    text: dark ? "#e0e0e0" : "#333",
    textSecondary: dark ? "#aaa" : "#666",
    textMuted: dark ? "#777" : "#999",
    grid: dark ? "#2a2a4a" : "#eee",
    gridStrong: dark ? "#333355" : "#ddd",
    zero: dark ? "#666" : "#999",
    bg: dark ? "#16213e" : "#fff",
    trackColors: dark ? TRACK_COLORS_DARK : TRACK_COLORS,
  };
}

var _THEME_ICONS = { light: "\u2600", dark: "\u263E", auto: "\u25D0" };
var _THEME_TITLES = { light: "Light (click: Dark)", dark: "Dark (click: Auto)", auto: "Auto (click: Light)" };

function _applyTheme() {
  var resolved = _themeMode === "auto" ? (_systemDark() ? "dark" : "light") : _themeMode;
  document.documentElement.setAttribute("data-theme", resolved);
  var btn = document.getElementById("theme-toggle");
  btn.textContent = _THEME_ICONS[_themeMode];
  btn.title = _THEME_TITLES[_themeMode];
}

function setThemeMode(mode) {
  _themeMode = mode;
  localStorage.setItem("spectrum-theme", mode);
  var wasDark = isDark();
  _applyTheme();
  if (isDark() !== wasDark) _reRenderCharts();
}

function _reRenderCharts() {
  if (lastData) {
    var data = lastData;
    clearResults();
    if (data.tracks) {
      renderCompare(data);
    } else {
      renderSingle(data);
    }
  }
}

// Init theme
(function() {
  var saved = localStorage.getItem("spectrum-theme");
  _themeMode = (saved === "light" || saved === "dark") ? saved : "auto";
  _applyTheme();
})();

// Cycle: light -> dark -> auto -> light
document.getElementById("theme-toggle").addEventListener("click", function() {
  var next = { light: "dark", dark: "auto", auto: "light" };
  setThemeMode(next[_themeMode]);
});

// Follow system changes when in auto mode
if (window.matchMedia) {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function() {
    if (_themeMode === "auto") {
      var wasDark = isDark();
      _applyTheme();
      if (isDark() !== wasDark) _reRenderCharts();
    }
  });
}

const form = document.getElementById("analyze-form");
const urlInput = document.getElementById("url-input");
const browseBtn = document.getElementById("browse-btn");
const submitBtn = document.getElementById("submit-btn");
const addBtn = document.getElementById("add-btn");
const loadBtn = document.getElementById("load-btn");
const trackList = document.getElementById("track-list");
const compareBar = document.getElementById("compare-bar");
const clearBtn = document.getElementById("clear-btn");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");

// Context menu for text input (right-click paste/cut/copy/select all)
(function() {
  var menu = null;
  function closeMenu() { if (menu) { menu.remove(); menu = null; } }
  document.addEventListener("click", closeMenu);
  document.addEventListener("contextmenu", (e) => {
    closeMenu();
    var el = e.target;
    if (el.tagName !== "INPUT" || el.type !== "text") return;
    e.preventDefault();
    menu = document.createElement("div");
    menu.className = "ctx-menu";
    var items = [
      { label: "Cut", fn: () => { document.execCommand("cut"); } },
      { label: "Copy", fn: () => { document.execCommand("copy"); }, disabled: el.selectionStart === el.selectionEnd },
      { label: "Paste", fn: () => { navigator.clipboard.readText().then((t) => { document.execCommand("insertText", false, t); }).catch(() => {}); } },
      { label: "Select All", fn: () => { el.select(); } },
    ];
    items.forEach((it) => {
      var btn = document.createElement("button");
      btn.textContent = it.label;
      if (it.disabled) btn.disabled = true;
      btn.addEventListener("mousedown", (ev) => { ev.preventDefault(); el.focus(); it.fn(); closeMenu(); });
      menu.appendChild(btn);
    });
    menu.style.left = e.clientX + "px";
    menu.style.top = e.clientY + "px";
    document.body.appendChild(menu);
    var rect = menu.getBoundingClientRect();
    if (rect.right > window.innerWidth) menu.style.left = (window.innerWidth - rect.width - 4) + "px";
    if (rect.bottom > window.innerHeight) menu.style.top = (window.innerHeight - rect.height - 4) + "px";
  });
})();

function clearResults() {
  activeUPlots.forEach(u => u.destroy());
  activeUPlots = [];
  chartCanvasRefs = [];
  resultsEl.className = "";
  resultsEl.innerHTML = "";
  lastData = null;
}

function safeName(label) {
  return (label || "untitled").replace(/[\\/:*?"<>|]/g, "_").slice(0, 80);
}

function _tryAddTrack(src) {
  if (src && compareSources.indexOf(src) === -1 && compareSources.length < 6) {
    compareSources.push(src);
    return true;
  }
  return false;
}

function _effectiveTrackCount() {
  var n = compareSources.length;
  var pending = urlInput.value.trim();
  if (pending && compareSources.indexOf(pending) === -1) n++;
  return n;
}

function _submitLabel() {
  return _effectiveTrackCount() >= 2 ? "Compare" : "Analyze";
}

function setBusy(busy) {
  isBusy = busy;
  browseBtn.disabled = busy;
  loadBtn.disabled = busy;
  addBtn.disabled = busy;
  clearBtn.disabled = busy;
  if (busy) {
    submitBtn.textContent = "Cancel";
    submitBtn.classList.add("cancelling");
  } else {
    submitBtn.textContent = _submitLabel();
    submitBtn.classList.remove("cancelling");
    activeAbort = null;
  }
  submitBtn.disabled = false;
  // Update track remove buttons (disabled during processing)
  document.querySelectorAll(".remove-track").forEach((btn) => {
    btn.disabled = busy;
  });
}


function updateCompareUI() {
  trackList.innerHTML = "";
  for (let i = 0; i < compareSources.length; i++) {
    const item = document.createElement("div");
    item.className = "track-item";
    const swatch = document.createElement("span");
    swatch.className = "legend-swatch";
    swatch.style.background = getThemeColors().trackColors[i % TRACK_COLORS.length];
    swatch.style.width = "20px";
    swatch.style.height = "10px";
    swatch.style.borderRadius = "2px";
    item.appendChild(swatch);
    const label = document.createElement("span");
    label.className = "track-label";
    label.textContent = compareSources[i];
    item.appendChild(label);
    const removeBtn = document.createElement("button");
    removeBtn.className = "remove-track";
    removeBtn.textContent = "\u00d7";
    removeBtn.disabled = isBusy;
    removeBtn.addEventListener("click", () => {
      compareSources.splice(i, 1);
      if (compareSources.length === 1 && !urlInput.value.trim()) {
        urlInput.value = compareSources[0];
        compareSources.length = 0;
      }
      updateCompareUI();
    });
    item.appendChild(removeBtn);
    trackList.appendChild(item);
  }
  compareBar.style.display = compareSources.length > 0 ? "flex" : "none";
  if (!isBusy) submitBtn.textContent = _submitLabel();
}

urlInput.addEventListener("input", () => {
  if (isBusy) return;
  var label = _submitLabel();
  if (submitBtn.textContent !== label) submitBtn.textContent = label;
});

function cancelActive() {
  if (activeAbort) {
    activeAbort.abort();
    activeAbort = null;
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (isBusy) { cancelActive(); return; }

  // Unify sources: compareSources + pending urlInput value
  var pending = urlInput.value.trim();
  if (_tryAddTrack(pending)) {
    urlInput.value = "";
    updateCompareUI();
  } else if (pending && compareSources.length >= 6) {
    showError("Maximum 6 tracks for comparison");
    return;
  }

  // Determine mode from effective source count
  var isCompare = compareSources.length >= 2;
  var singleSource = null;
  if (!isCompare) {
    singleSource = compareSources.length === 1 ? compareSources[0] : pending;
    if (!singleSource) return;
  }

  statusEl.textContent = isCompare ? "Starting comparison..." : "Starting...";
  statusEl.className = "";
  setBusy(true);
  clearResults();

  activeAbort = new AbortController();
  try {
    var endpoint = isCompare ? "/compare" : "/analyze";
    var body = isCompare
      ? { sources: compareSources }
      : { url: singleSource };
    var resultType = isCompare ? "compare_result" : "result";

    const resp = await fetch(window.location.origin + endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: activeAbort.signal,
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${resp.status}`);
    }

    const data = await readNdjsonStream(resp, resultType, activeAbort.signal);
    statusEl.textContent = "";
    if (isCompare) {
      lastDuration = body.duration || null;
      lastSource = null;
      renderCompare(data);
    } else {
      lastSource = body.url;
      lastDuration = body.duration || null;
      renderSingle(data);
    }
  } catch (err) {
    if (err.name === "AbortError") {
      statusEl.textContent = "Cancelled.";
      statusEl.className = "";
    } else {
      showError(err.message);
    }
  } finally {
    setBusy(false);
  }
});

// Browse local audio file
browseBtn.addEventListener("click", async () => {
  if (isBusy) return;
  try {
    const resp = await fetch(window.location.origin + "/browse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const result = await resp.json();
    if (result.selected) {
      urlInput.value = result.path;
      urlInput.focus();
    }
  } catch (err) {
    showError(err.message);
  }
});

addBtn.addEventListener("click", () => {
  const url = urlInput.value.trim();
  if (!url) return;
  if (compareSources.length >= 6) {
    showError("Maximum 6 tracks for comparison");
    return;
  }
  if (compareSources.indexOf(url) !== -1) {
    showError("This track is already added");
    return;
  }
  compareSources.push(url);
  urlInput.value = "";
  urlInput.focus();
  updateCompareUI();
});

// Clear all tracks
clearBtn.addEventListener("click", () => {
  compareSources.length = 0;
  updateCompareUI();
  clearResults();
  statusEl.textContent = "";
  statusEl.className = "";
});

// Load JSON
loadBtn.addEventListener("click", async () => {
  if (isBusy) return;
  setBusy(true);
  statusEl.textContent = "Opening file...";
  statusEl.className = "";

  try {
    const resp = await fetch(window.location.origin + "/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const result = await resp.json();

    if (result.error) {
      showError(result.error);
      return;
    }
    if (!result.loaded) {
      statusEl.textContent = "";
      return;
    }

    // Schema version check — offer re-analysis for outdated single files
    if (result.schema_outdated) {
      var src = result.source || "";
      if (!result.source_available) {
        showError("旧バージョンのデータです。元のファイルが見つからないため再解析できません: " + src);
        return;
      }
      if (!window.confirm(
        "旧形式のデータです。最新形式で再解析しますか?\n\nSource: " + src
      )) {
        // User declined — display as-is (best effort), fall through
      } else {
        // Add source as track — outdated data is not cached, so
        // next Analyze/Compare will re-analyze fresh.
        var pending = urlInput.value.trim();
        if (pending) _tryAddTrack(pending);
        var added = _tryAddTrack(src);
        if (compareSources.length >= 2) {
          urlInput.value = "";
          updateCompareUI();
          var msg = compareSources.length + " tracks ready for comparison";
          if (!added && src) msg += " (max 6 tracks)";
          statusEl.textContent = msg;
          statusEl.className = "";
        } else if (compareSources.length === 1) {
          urlInput.value = compareSources.pop();
          updateCompareUI();
        }
        return;
      }
    }

    // Preserve any pending source in urlInput before Load overwrites it
    var pending = urlInput.value.trim();
    if (_tryAddTrack(pending)) {
      urlInput.value = "";
    }

    if (result.type === "multi") {
      var skipped = 0;
      for (var i = 0; i < result.items.length; i++) {
        var item = result.items[i];
        var s = item.meta && item.meta.source;
        if (s && !_tryAddTrack(s)) skipped++;
      }
      urlInput.value = "";
      updateCompareUI();
      var msg = `${compareSources.length} tracks ready for comparison`;
      if (skipped > 0) msg += ` (${skipped} skipped: max 6 tracks)`;
      statusEl.textContent = msg;
      statusEl.className = "";
    } else {
      // Single file loaded: add its source to track list for comparison
      var src = result.data.meta && result.data.meta.source;
      var added = _tryAddTrack(src);
      if (compareSources.length >= 2) {
        urlInput.value = "";
        updateCompareUI();
        var msg = `${compareSources.length} tracks ready for comparison`;
        if (!added && src) msg += " (max 6 tracks)";
        statusEl.textContent = msg;
        statusEl.className = "";
      } else {
        clearResults();
        if (src) {
          urlInput.value = src;
          lastSource = src;
        }
        // Restore pending to urlInput if it was the only track
        if (compareSources.length === 1) {
          urlInput.value = compareSources[0];
          compareSources.length = 0;
        }
        lastDuration = null;
        statusEl.textContent = "";
        renderSingle(result.data);
      }
    }
  } catch (err) {
    showError(err.message);
  } finally {
    setBusy(false);
  }
});

async function readNdjsonStream(resp, resultType, signal) {
  resultType = resultType || "result";
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = null;

  if (signal) {
    signal.addEventListener("abort", () => reader.cancel(), { once: true });
  }

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.trim()) continue;
        var event;
        try { event = JSON.parse(line); } catch (_) { continue; }

        if (event.type === "progress") {
          statusEl.textContent = event.message;
        } else if (event.type === resultType) {
          result = event.data;
        } else if (event.type === "error") {
          throw new Error(event.error);
        }
      }
    }
  } catch (err) {
    if (err.name === "AbortError" || (signal && signal.aborted)) {
      throw new DOMException("Aborted", "AbortError");
    }
    throw err;
  }

  if (!result) throw new Error("No result received from server");
  return result;
}

function _addCanvasChart(title, height, renderFn, renderArg) {
  const div = document.createElement("div");
  div.className = "chart-row";
  _chartTitle(div, title);
  const canvas = document.createElement("canvas");
  canvas.style.height = height;
  div.appendChild(canvas);
  resultsEl.appendChild(div);
  renderFn(canvas, renderArg);
  chartCanvasRefs.push({canvas: canvas, title: title});
}

function _addSpectrumChart(title, tracks) {
  const div = document.createElement("div");
  div.className = "chart-row";
  _chartTitle(div, title);
  resultsEl.appendChild(div);
  const uplot = renderSpectrum(div, tracks);
  activeUPlots.push(uplot);
  if (uplot.ctx) chartCanvasRefs.push({canvas: uplot.ctx.canvas, title: title});
}

function renderSingle(data) {
  lastData = data;
  resultsEl.className = "visible";
  chartCanvasRefs = [];

  const titleRow = document.createElement("div");
  titleRow.className = "title-row";

  const titleEl = document.createElement("div");
  titleEl.className = "result-title";
  titleEl.textContent = data.label || "Analysis Result";
  titleRow.appendChild(titleEl);

  appendSaveButtons(titleRow, data);
  resultsEl.appendChild(titleRow);

  renderMeta(data.meta);
  renderSingleSummary(data);

  _addSpectrumChart("PSD Spectrum", [data]);
  _addCanvasChart("1/3 Octave Band Analysis", "300px", renderOctave, [data]);
  _addCanvasChart("Low-End Detail", "280px", renderLowEnd, [data]);
  _addCanvasChart("Mid-High Detail", "280px", renderMidHigh, [data]);
}

function renderCompare(data) {
  lastData = data;
  resultsEl.className = "visible";
  chartCanvasRefs = [];

  const titleRow = document.createElement("div");
  titleRow.className = "title-row";

  const titleEl = document.createElement("div");
  titleEl.className = "result-title";
  titleEl.textContent = "Comparison Result";
  titleRow.appendChild(titleEl);

  // Save Image only (no JSON save for compare mode)
  const saveImgBtn = document.createElement("button");
  saveImgBtn.className = "save-btn";
  saveImgBtn.textContent = "Save Image";
  saveImgBtn.addEventListener("click", () => saveImage(data));
  titleRow.appendChild(saveImgBtn);

  resultsEl.appendChild(titleRow);

  renderMeta(data.meta);
  renderCompareSummary(data.tracks);
  renderLegend(data.tracks);

  _addSpectrumChart("PSD Spectrum", data.tracks);
  _addCanvasChart("1/3 Octave Band Analysis", "300px", renderOctave, data.tracks);

  if (data.transfer_functions && data.transfer_functions.length > 0) {
    _addCanvasChart("Transfer Function", "280px", renderTransfer, data.transfer_functions);
  }

  _addCanvasChart("Low-End Detail", "280px", renderLowEnd, data.tracks);
  _addCanvasChart("Mid-High Detail", "280px", renderMidHigh, data.tracks);
}

function renderMeta(meta) {
  if (!meta) return;
  const el = document.createElement("div");
  el.className = "meta-info";
  const parts = [];
  if (meta.analyzed_at) {
    const d = new Date(meta.analyzed_at);
    parts.push(d.toLocaleString());
  }
  if (meta.source) parts.push(meta.source);
  if (meta.sources) parts.push(meta.sources.length + " tracks");
  el.textContent = parts.join(" | ");
  resultsEl.appendChild(el);
}

var METRIC_TIPS = {
  "Duration": "分析対象音声の長さ (秒)。",
  "RMS": "実効値 (Root Mean Square) を dBFS で表示。音声全体の平均的な音量レベル。0 dBFS がデジタルフルスケール。",
  "True Peak": "ITU-R BS.1770 準拠の True Peak (dBTP)。4 倍オーバーサンプリングによりサンプル間ピークを検出する。0 dBTP を超えると DA 変換時にクリッピングが発生しうる。",
  "Crest": "クレストファクター (True Peak \u2212 RMS)。ダイナミクスの指標。値が大きいほどダイナミックレンジが広い。コンプレッサーで潰されたソースは値が小さくなる。",
  "Low/Intel Ratio": "低域 (20\u2013200Hz) と明瞭度帯域 (1\u20135kHz) のエネルギー比 (dB)。ANSI S3.5 に基づき、1\u20135kHz は音声明瞭度の約 72% を担う。0 dB 付近が理想。正の値は低域過多、負は低域不足を示す。",
  "Low/Intel": "低域 (20\u2013200Hz) と明瞭度帯域 (1\u20135kHz) のエネルギー比 (dB)。ANSI S3.5 に基づき、1\u20135kHz は音声明瞭度の約 72% を担う。0 dB 付近が理想。正の値は低域過多、負は低域不足を示す。",
  "Spectral Centroid": "スペクトル重心 (80\u20138000Hz)。エネルギーで重み付けした平均周波数。値が高いほど明るい音色、低いほど暗い・こもった音色を示す。",
  "Centroid": "スペクトル重心 (80\u20138000Hz)。エネルギーで重み付けした平均周波数。値が高いほど明るい音色、低いほど暗い・こもった音色を示す。",
  "HPF -3dB": "ハイパスフィルターの推定カットオフ周波数。300\u2013600Hz の平均レベルをパスバンド基準とし、そこから \u22123dB 下がる低域側の周波数を探索する。N/A は明確な HPF が検出されない場合。",
  "Tilt": "スペクトル傾斜 (dB/oct)。80Hz\u201310kHz の PSD を log2 周波数で線形回帰した傾き。負の値は高域減衰を示す。プロのミックスは概ね \u22123\u301c\u22124 dB/oct。",
  "Pres/Mid": "プレゼンス (2\u20135kHz) とミッド (500\u20132kHz) のエネルギー比 (dB)。正の値はボーカルや楽器が「前に出る」音像、負の値は引っ込んだ音像を示す。",
  "Bright": "高域の相対的な輝き。エアー (5\u201310kHz) と中高域 (500\u20135kHz) のエネルギー比 (dB)。De-esser やリバーブの高域減衰の確認に有用。",
  "HF Rolloff": "高域ロールオフ周波数。ミッド帯域 (500\u20132kHz) の平均レベルから \u221210dB 下がる高域側の周波数。LPF やコーデック (MP3/AAC) による高域カットの検出に使う。N/A は検出されない場合。",
  "Sub (20-80)": "サブベース帯域のエネルギー (dB)。体感的な低音の圧力を担う帯域。過多だとこもり、不足だと薄い低音になる。",
  "Low (80-200)": "ベース帯域のエネルギー (dB)。キックやベースの基音が集中する、楽曲の土台となる帯域。",
  "Low-Mid (200-500)": "ローミッド帯域のエネルギー (dB)。ボーカルの胸声やギターのボディ感。過多になると音の「こもり」の原因になる。",
  "Mid (500-2k)": "ミッド帯域のエネルギー (dB)。ボーカルの基本周波数や楽器の存在感を担う中核帯域。",
  "Presence (2-5k)": "プレゼンス帯域のエネルギー (dB)。子音の明瞭度や楽器のアタック感。この帯域が音を「前に出す」役割を果たす。",
  "Air (5-10k)": "エアー帯域のエネルギー (dB)。高域の空気感やシンバルの輝きを担う帯域。",
};

var CHART_TIPS = {
  "PSD Spectrum": "Welch 法による PSD (Power Spectral Density) 推定。nperseg=4096 / 48kHz で周波数分解能 11.7Hz。横軸は対数周波数、縦軸はパワー (dB)。全体的なスペクトル形状の確認に使う。",
  "1/3 Octave Band Analysis": "1/3 オクターブバンドごとのエネルギー (25Hz\u201310kHz, 27 bands)。人間の聴覚特性に近い対数的な周波数分割で、帯域ごとのバランスを直感的に比較できる。",
  "Transfer Function": "リファレンストラック (最初に追加したトラック) に対する各トラックの PSD 差分 (\u0394dB)。EQ 処理の効果を周波数ごとに可視化する。0dB ラインが変化なし。",
  "Low-End Detail": "20\u2013500Hz を線形周波数軸で拡大表示。HPF のカットオフ特性やベース帯域の詳細な形状を確認する。破線は HPF \u22123dB 推定位置。",
  "Mid-High Detail": "500Hz\u201320kHz を対数周波数軸で拡大表示。プレゼンス・エアー帯域の形状やコーデックによる高域カットの確認に使う。破線は HF Rolloff 推定位置。",
};

function _chartTitle(parent, text) {
  var el = document.createElement("div");
  el.className = "chart-title";
  el.textContent = text;
  if (CHART_TIPS[text]) _addTip(el, CHART_TIPS[text]);
  parent.appendChild(el);
}

// Tooltip system — positions dynamically to stay within viewport
var _tipEl = null;
var _tipTimer = null;
function _showTip(anchor, text) {
  _hideTip();
  _tipTimer = setTimeout(() => {
    _tipEl = document.createElement("div");
    _tipEl.className = "tip-popup";
    _tipEl.textContent = text;
    document.body.appendChild(_tipEl);
    var r = anchor.getBoundingClientRect();
    var tw = 300, th = _tipEl.offsetHeight;
    var left = r.left + r.width / 2 - tw / 2;
    var top = r.bottom + 6;
    if (left < 4) left = 4;
    if (left + tw > window.innerWidth - 4) left = window.innerWidth - tw - 4;
    if (top + th > window.innerHeight - 4) top = r.top - th - 6;
    _tipEl.style.left = left + "px";
    _tipEl.style.top = top + "px";
  }, 200);
}
function _hideTip() {
  clearTimeout(_tipTimer);
  if (_tipEl) { _tipEl.remove(); _tipEl = null; }
}

function _addTip(cell, text) {
  cell.className = (cell.className ? cell.className + " " : "") + "has-tip";
  cell.addEventListener("mouseenter", () => _showTip(cell, text));
  cell.addEventListener("mouseleave", _hideTip);
}

function _addRow(table, cells, isHeader) {
  const row = document.createElement("tr");
  for (const text of cells) {
    const cell = document.createElement(isHeader ? "th" : "td");
    cell.textContent = text;
    if (isHeader && METRIC_TIPS[text]) {
      _addTip(cell, METRIC_TIPS[text]);
    }
    row.appendChild(cell);
  }
  table.appendChild(row);
}

function _fmtHz(val) {
  return val != null ? "~" + fmt(val, 0) + " Hz" : "N/A";
}

function _formatTrackMetrics(t) {
  var s = t.summary;
  return {
    rms: fmt(t.rms_dbfs, 1) + " dBFS",
    peak: fmt(t.true_peak_dbtp, 1) + " dBTP",
    crest: fmt(s.crest_factor_db, 1) + " dB",
    lowIntel: fmtSign(s.low_intel_ratio_db, 1) + " dB",
    centroid: fmt(s.spectral_centroid_hz, 0) + " Hz",
    tilt: fmt(s.spectral_tilt_db_oct, 1) + " dB/oct",
    presMid: fmtSign(s.presence_mid_ratio_db, 1) + " dB",
    bright: fmtSign(s.brightness_db, 1) + " dB",
    hpf: _fmtHz(s.hpf_3db_hz),
    hfRolloff: _fmtHz(s.hf_rolloff_hz),
    sub: fmt(s.band_energy.sub_20_80, 1) + " dB",
    low: fmt(s.band_energy.low_80_200, 1) + " dB",
    lowMid: fmt(s.band_energy.low_mid_200_500, 1) + " dB",
    mid: fmt(s.band_energy.mid_500_2k, 1) + " dB",
    presence: fmt(s.band_energy.presence_2k_5k, 1) + " dB",
    air: fmt(s.band_energy.air_5k_10k, 1) + " dB",
  };
}

function renderSingleSummary(data) {
  var m = _formatTrackMetrics(data);
  const table = document.createElement("table");
  table.className = "summary-table";

  _addRow(table, ["Duration", "RMS", "True Peak", "Crest",
    "Low/Intel Ratio", "Spectral Centroid"], true);
  _addRow(table, [
    fmt(data.duration_sec, 2) + "s",
    m.rms, m.peak, m.crest, m.lowIntel, m.centroid,
  ], false);
  _addRow(table, ["Tilt", "Pres/Mid", "Bright",
    "HPF -3dB", "HF Rolloff", ""], true);
  _addRow(table, [
    m.tilt, m.presMid, m.bright, m.hpf, m.hfRolloff, "",
  ], false);
  _addRow(table, ["Sub (20-80)", "Low (80-200)", "Low-Mid (200-500)",
    "Mid (500-2k)", "Presence (2-5k)", "Air (5-10k)"], true);
  _addRow(table, [
    m.sub, m.low, m.lowMid, m.mid, m.presence, m.air,
  ], false);

  resultsEl.appendChild(table);
}

function renderCompareSummary(tracks) {
  const table = document.createElement("table");
  table.className = "summary-table";

  _addRow(table, ["Track", "RMS", "True Peak", "Crest",
    "Low/Intel", "Centroid", "Tilt", "Pres/Mid", "Bright",
    "HPF -3dB", "HF Rolloff"], true);

  for (const t of tracks) {
    var m = _formatTrackMetrics(t);
    const row = document.createElement("tr");
    const labelCell = document.createElement("td");
    labelCell.className = "label-cell";
    labelCell.textContent = t.label;
    row.appendChild(labelCell);
    for (const text of [
      m.rms, m.peak, m.crest, m.lowIntel, m.centroid,
      m.tilt, m.presMid, m.bright, m.hpf, m.hfRolloff,
    ]) {
      const cell = document.createElement("td");
      cell.textContent = text;
      row.appendChild(cell);
    }
    table.appendChild(row);
  }

  resultsEl.appendChild(table);
}

function renderLegend(tracks) {
  const bar = document.createElement("div");
  bar.className = "legend-bar";
  for (let i = 0; i < tracks.length; i++) {
    const item = document.createElement("div");
    item.className = "legend-item";
    const swatch = document.createElement("span");
    swatch.className = "legend-swatch";
    swatch.style.background = getThemeColors().trackColors[i % TRACK_COLORS.length];
    item.appendChild(swatch);
    const label = document.createElement("span");
    label.textContent = tracks[i].label;
    item.appendChild(label);
    bar.appendChild(item);
  }
  resultsEl.appendChild(bar);
}

function appendSaveButtons(container, data) {
  const saveBtn = document.createElement("button");
  saveBtn.className = "save-btn";
  saveBtn.textContent = "Save JSON";
  saveBtn.addEventListener("click", () => saveResult(data));
  container.appendChild(saveBtn);

  const saveImgBtn = document.createElement("button");
  saveImgBtn.className = "save-btn";
  saveImgBtn.textContent = "Save Image";
  saveImgBtn.addEventListener("click", () => saveImage(data));
  container.appendChild(saveImgBtn);
}

function fmt(val, decimals) {
  if (val == null) return "?";
  return val.toFixed(decimals);
}

function fmtSign(val, decimals) {
  if (val == null) return "?";
  const s = val.toFixed(decimals);
  return val > 0 ? `+${s}` : s;
}

async function saveResult(data) {
  const label = data.label || "spectrum";
  const filename = `spectrum_${safeName(label)}.json`;
  try {
    const body = { data, filename };
    if (lastSource) body.source = lastSource;
    if (lastDuration != null) body.duration = lastDuration;
    const resp = await fetch(window.location.origin + "/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const result = await resp.json();
    if (result.saved) {
      statusEl.textContent = `Saved: ${result.path}`;
      statusEl.className = "";
    } else if (result.error) {
      showError(`Save failed: ${result.error}`);
    }
  } catch (err) {
    showError(`Save failed: ${err.message}`);
  }
}

function _buildSummaryTables(data) {
  if (data.tracks) {
    var table1 = {
      header: ["Track", "RMS", "True Peak", "Crest", "Low/Intel", "Centroid"],
      rows: data.tracks.map((t) => {
        var m = _formatTrackMetrics(t);
        return [t.label, m.rms, m.peak, m.crest, m.lowIntel, m.centroid];
      }),
    };
    var table2 = {
      header: ["Track", "Tilt", "Pres/Mid", "Bright", "HPF -3dB", "HF Rolloff"],
      rows: data.tracks.map((t) => {
        var m = _formatTrackMetrics(t);
        return [t.label, m.tilt, m.presMid, m.bright, m.hpf, m.hfRolloff];
      }),
    };
    return [table1, table2];
  }
  var m = _formatTrackMetrics(data);
  var t1 = {
    header: ["Duration", "RMS", "True Peak", "Crest", "Low/Intel Ratio", "Spectral Centroid"],
    rows: [[fmt(data.duration_sec, 2) + "s", m.rms, m.peak, m.crest, m.lowIntel, m.centroid]],
  };
  var t2 = {
    header: ["Tilt", "Pres/Mid", "Bright", "HPF -3dB", "HF Rolloff", ""],
    rows: [[m.tilt, m.presMid, m.bright, m.hpf, m.hfRolloff, ""]],
  };
  var t3 = {
    header: ["Sub (20-80)", "Low (80-200)", "Low-Mid (200-500)", "Mid (500-2k)", "Presence (2-5k)", "Air (5-10k)"],
    rows: [[m.sub, m.low, m.lowMid, m.mid, m.presence, m.air]],
  };
  return [t1, t2, t3];
}

function _calcColWidths(header, w) {
  // Give "Track" column 30% of width, rest share equally
  if (header[0] === "Track") {
    const trackW = Math.round(w * 0.30);
    const rest = (w - trackW) / (header.length - 1);
    return [trackW, ...Array(header.length - 1).fill(rest)];
  }
  const colW = w / header.length;
  return Array(header.length).fill(colW);
}

function _truncText(ctx, text, maxW) {
  if (ctx.measureText(text).width <= maxW) return text;
  var t = text;
  while (t.length > 0 && ctx.measureText(t + "...").width > maxW) {
    t = t.slice(0, -1);
  }
  return t + "...";
}

function _drawTable(ctx, x0, y, w, header, rows, dark) {
  const colWidths = _calcColWidths(header, w);
  const ROW_H = 26;
  const CELL_PAD = 6;
  const FONT = "13px 'Segoe UI', 'Meiryo', sans-serif";
  const BOLD = "bold " + FONT;
  const lineColor = dark ? "#2a4a6a" : "#90CAF9";
  const totalH = ROW_H * (1 + rows.length);

  // Header background
  ctx.fillStyle = dark ? "#1e3a5f" : "#BBDEFB";
  ctx.fillRect(x0, y, w, ROW_H);

  // Header text
  ctx.font = BOLD;
  ctx.fillStyle = dark ? "#90caf9" : "#0D47A1";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  var cx = x0;
  for (let i = 0; i < header.length; i++) {
    ctx.fillText(header[i], cx + colWidths[i] / 2, y + ROW_H / 2);
    cx += colWidths[i];
  }
  y += ROW_H;

  // Data rows
  ctx.font = FONT;
  for (let r = 0; r < rows.length; r++) {
    ctx.fillStyle = r % 2 === 0
      ? (dark ? "#16213e" : "#E3F2FD")
      : (dark ? "#1a1a2e" : "#fff");
    ctx.fillRect(x0, y, w, ROW_H);

    ctx.fillStyle = dark ? "#e0e0e0" : "#333";
    cx = x0;
    for (let i = 0; i < rows[r].length; i++) {
      const maxTextW = colWidths[i] - CELL_PAD * 2;
      const text = _truncText(ctx, rows[r][i], maxTextW);
      ctx.textAlign = "center";
      ctx.fillText(text, cx + colWidths[i] / 2, y + ROW_H / 2);
      cx += colWidths[i];
    }
    y += ROW_H;
  }

  // Outer border
  ctx.strokeStyle = lineColor;
  ctx.lineWidth = 1;
  const topY = y - totalH;
  ctx.strokeRect(x0, topY, w, totalH);

  // Column dividers
  cx = x0;
  for (let i = 0; i < colWidths.length - 1; i++) {
    cx += colWidths[i];
    ctx.beginPath();
    ctx.moveTo(cx, topY);
    ctx.lineTo(cx, topY + totalH);
    ctx.stroke();
  }
  // Header divider
  ctx.beginPath();
  ctx.moveTo(x0, topY + ROW_H);
  ctx.lineTo(x0 + w, topY + ROW_H);
  ctx.stroke();

  return y;
}

function captureImage(data) {
  const dpr = window.devicePixelRatio || 1;
  const SCALE = 2;
  const W = 1100;
  const PAD = 24;

  // Build summary tables
  const tables = _buildSummaryTables(data);
  const TABLE_ROW_H = 26;
  var tablesH = 0;
  for (var ti = 0; ti < tables.length; ti++) {
    tablesH += TABLE_ROW_H * (1 + tables[ti].rows.length) + 12;
  }

  let totalH = PAD + 32 + tablesH; // title + tables

  // Chart heights (each entry has canvas + title)
  const TITLE_H = 24;
  const chartSizes = [];
  for (const ref of chartCanvasRefs) {
    var c = ref.canvas;
    if (!c || !c.width) continue;
    const h = c.height / dpr;
    const w = c.width / dpr;
    chartSizes.push({ canvas: c, w, h, title: ref.title });
    totalH += TITLE_H + h + 16;
  }
  totalH += PAD;

  const comp = document.createElement("canvas");
  comp.width = W * SCALE;
  comp.height = totalH * SCALE;
  const ctx = comp.getContext("2d");
  ctx.scale(SCALE, SCALE);

  var dark = isDark();
  ctx.fillStyle = dark ? "#1a1a2e" : "#fff";
  ctx.fillRect(0, 0, W, totalH);

  let y = PAD;

  const title = data.label || (data.tracks ? "Comparison" : "Analysis");
  ctx.fillStyle = dark ? "#64b5f6" : "#1565C0";
  ctx.font = "bold 18px 'Segoe UI', 'Meiryo', sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(title, W / 2, y + 18);

  // App version in top-right
  var ver = (data.meta && data.meta.version) || "";
  if (ver) {
    ctx.fillStyle = dark ? "#555" : "#bbb";
    ctx.font = "11px 'Segoe UI', 'Meiryo', sans-serif";
    ctx.textAlign = "right";
    ctx.fillText("analyze-spectrum v" + ver, W - PAD, y + 14);
  }
  y += 32;

  // Summary tables
  for (var ti = 0; ti < tables.length; ti++) {
    y = _drawTable(ctx, PAD, y, W - PAD * 2, tables[ti].header, tables[ti].rows, dark);
    y += 12;
  }

  for (const { canvas, w, h, title } of chartSizes) {
    // Draw chart title
    ctx.fillStyle = dark ? "#e0e0e0" : "#333";
    ctx.font = "bold 14px 'Segoe UI', 'Meiryo', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(title, W / 2, y + 16);
    y += TITLE_H;

    const drawW = Math.min(w, W - PAD * 2);
    const drawH = h * (drawW / w);
    const x = (W - drawW) / 2;
    ctx.drawImage(canvas, x, y, drawW, drawH);
    y += drawH + 16;
  }

  return comp.toDataURL("image/png");
}

async function saveImage(data) {
  const label = data.label || data.tracks?.[0]?.label || "eq";
  const filename = `spectrum_${safeName(label)}.png`;
  try {
    statusEl.textContent = "Generating image...";
    statusEl.className = "";
    const dataUrl = captureImage(data);
    const resp = await fetch(window.location.origin + "/save-image", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dataUrl, filename }),
    });
    const result = await resp.json();
    if (result.saved) {
      statusEl.textContent = `Saved: ${result.path}`;
      statusEl.className = "";
    } else if (result.error) {
      showError(`Save failed: ${result.error}`);
    } else {
      statusEl.textContent = "";
    }
  } catch (err) {
    showError(`Save failed: ${err.message}`);
  }
}

// Drag & drop — use capture phase on window to intercept before WebView2
// native handling can navigate to the dropped file URL.
window.addEventListener("dragover", (e) => {
  e.preventDefault();
  e.stopImmediatePropagation();
  e.dataTransfer.dropEffect = "copy";
  document.body.classList.add("drag-over");
}, true);

window.addEventListener("dragenter", (e) => {
  e.preventDefault();
  e.stopImmediatePropagation();
}, true);

window.addEventListener("dragleave", (e) => {
  if (!e.relatedTarget) {
    document.body.classList.remove("drag-over");
  }
}, true);

window.addEventListener("drop", async (e) => {
  e.preventDefault();
  e.stopImmediatePropagation();
  document.body.classList.remove("drag-over");
  if (isBusy) return;

  const file = e.dataTransfer.files[0];
  if (!file) return;

  statusEl.textContent = "Uploading: " + file.name;
  statusEl.className = "";
  try {
    const resp = await fetch(window.location.origin + "/upload", {
      method: "POST",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Filename": file.name,
      },
      body: file,
    });
    const result = await resp.json();
    if (result.uploaded) {
      urlInput.value = result.path;
      urlInput.focus();
      statusEl.textContent = "File loaded: " + file.name;
    } else if (result.error) {
      showError(result.error);
    }
  } catch (err) {
    showError(err.message);
  }
}, true);

function showError(message) {
  statusEl.className = "error";
  statusEl.innerHTML = "";
  const text = document.createElement("span");
  text.textContent = `Error: ${message}`;
  statusEl.appendChild(text);
  const btn = document.createElement("button");
  btn.className = "copy-btn";
  btn.textContent = "Copy";
  btn.addEventListener("click", () => {
    navigator.clipboard.writeText(message).then(() => {
      btn.textContent = "Copied";
      setTimeout(() => { btn.textContent = "Copy"; }, 1500);
    }).catch(() => {});
  });
  statusEl.appendChild(btn);
}
