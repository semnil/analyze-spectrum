let activeUPlots = [];
let chartCanvasRefs = []; // [{canvas, title}]
let compareSources = [];
let lastData = null;
let isBusy = false;
let activeAbort = null;
let lastSource = null;
let lastDuration = null;
// Sources reflected by the currently rendered lastData (single = [src],
// compare = [...track sources]).  Compared against compareSources to detect
// when track edits or loads make the visible chart inconsistent.
let _displayedSources = [];

// Color-blind friendly hues (blue / orange / purple / cyan) first so the
// first four tracks remain distinguishable for deuteranopia / protanopia
// viewers; red / green come last.
const TRACK_COLORS = [
  "#1976D2", "#F57C00", "#7B1FA2", "#00838F", "#D32F2F", "#388E3C"
];

// Dark mode colors (brighter for dark backgrounds), same ordering rationale.
const TRACK_COLORS_DARK = [
  "#64b5f6", "#ffa726", "#ce93d8", "#4dd0e1", "#ef5350", "#66bb6a"
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
    textMuted: dark ? "#a0a0b0" : "#666",
    grid: dark ? "#2a2a4a" : "#eee",
    gridStrong: dark ? "#333355" : "#ddd",
    zero: dark ? "#666" : "#999",
    bg: dark ? "#16213e" : "#fff",
    trackColors: dark ? TRACK_COLORS_DARK : TRACK_COLORS,
  };
}

var _THEME_ICONS = { light: "\u2600", dark: "\u263E", auto: "\u25D0" };

function _applyTheme() {
  var resolved = _themeMode === "auto" ? (_systemDark() ? "dark" : "light") : _themeMode;
  document.documentElement.setAttribute("data-theme", resolved);
  var btn = document.getElementById("theme-toggle");
  if (!btn) return;
  btn.textContent = "";
  var icon = document.createElement("span");
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = _THEME_ICONS[_themeMode];
  btn.appendChild(icon);
  btn.title = window.i18n.t("theme.title." + _themeMode);
  btn.setAttribute("aria-label", window.i18n.t("theme.aria_state." + _themeMode));
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

// Resize uPlot + Canvas charts on window resize.  uPlot needs an explicit
// setSize; Canvas charts (octave / lowend / midhigh / transfer) render once
// at a fixed width so we re-run the full renderer against lastData.
let _resizeTimer = null;
window.addEventListener("resize", function() {
  clearTimeout(_resizeTimer);
  _resizeTimer = setTimeout(function() {
    activeUPlots.forEach(function(u) {
      var wrap = u.root.parentElement;
      if (wrap) u.setSize({width: wrap.clientWidth, height: u.height});
    });
    if (lastData) _reRenderCharts();
  }, 200);
});

// Init theme
(function() {
  var saved = localStorage.getItem("spectrum-theme");
  _themeMode = (saved === "light" || saved === "dark") ? saved : "auto";
  _applyTheme();
})();

// Cycle: light -> dark -> auto -> light
function _attachThemeToggle() {
  var btn = document.getElementById("theme-toggle");
  if (!btn) return;
  btn.addEventListener("click", function() {
    var next = { light: "dark", dark: "auto", auto: "light" };
    setThemeMode(next[_themeMode]);
  });
  _applyTheme();
}
if (document.getElementById("theme-toggle")) {
  _attachThemeToggle();
} else {
  document.addEventListener("DOMContentLoaded", _attachThemeToggle);
}

// Language toggle (EN <-> JA)
function _applyLangButton() {
  var btn = document.getElementById("lang-toggle");
  if (!btn) return;
  var cur = window.i18n.lang();
  btn.textContent = window.i18n.t("lang.label." + cur);
  btn.title = window.i18n.t("lang.title." + cur);
}
function _attachLangToggle() {
  var btn = document.getElementById("lang-toggle");
  if (!btn) return;
  btn.addEventListener("click", function () {
    var next = window.i18n.lang() === "ja" ? "en" : "ja";
    window.i18n.setLang(next);
  });
  _applyLangButton();
}
if (document.getElementById("lang-toggle")) {
  _attachLangToggle();
} else {
  document.addEventListener("DOMContentLoaded", _attachLangToggle);
}
function _applyDropText() {
  document.body.setAttribute("data-drop-text", window.i18n.t("drop.overlay"));
}
_applyDropText();

window.i18n.onChange(function () {
  _applyLangButton();
  _applyTheme();
  _applyDropText();
  if (!isBusy && submitBtn) submitBtn.textContent = _submitLabel();
  // Re-emit the active error so "Error: " prefix and Copy button follow
  // the new language without waiting for the next failure.
  if (_lastErrorMessage != null) showError(_lastErrorMessage);
  _reRenderCharts();
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
    menu.setAttribute("role", "menu");
    var start = el.selectionStart;
    var end = el.selectionEnd;
    var hasSelection = start !== end;
    var hasClipboard = !!navigator.clipboard;
    var items = [
      { label: window.i18n.t("ctx.cut"), fn: () => {
          if (start === end) return;
          var sel = el.value.slice(start, end);
          navigator.clipboard.writeText(sel);
          el.setRangeText("", start, end, "end");
        }, disabled: !hasSelection || !hasClipboard },
      { label: window.i18n.t("ctx.copy"), fn: () => {
          navigator.clipboard.writeText(el.value.slice(start, end));
        }, disabled: !hasSelection || !hasClipboard },
      { label: window.i18n.t("ctx.paste"), fn: () => {
          navigator.clipboard.readText().then((t) => {
            el.setRangeText(t, start, end, "end");
          }).catch((e) => { console.warn("Clipboard read failed:", e); });
        }, disabled: !hasClipboard },
      { label: window.i18n.t("ctx.select_all"), fn: () => { el.select(); } },
    ];
    items.forEach((it, i) => {
      var btn = document.createElement("button");
      btn.textContent = it.label;
      btn.setAttribute("role", "menuitem");
      btn.dataset.idx = String(i);
      if (it.disabled) btn.disabled = true;
      btn.addEventListener("mousedown", (ev) => { ev.preventDefault(); el.focus(); it.fn(); closeMenu(); });
      menu.appendChild(btn);
    });
    menu.addEventListener("keydown", (ev) => {
      var btns = Array.from(menu.querySelectorAll("button:not(:disabled)"));
      var idx = btns.indexOf(document.activeElement);
      if (ev.key === "ArrowDown") { ev.preventDefault(); btns[(idx + 1) % btns.length].focus(); }
      else if (ev.key === "ArrowUp") { ev.preventDefault(); btns[(idx - 1 + btns.length) % btns.length].focus(); }
      else if (ev.key === "Escape") { closeMenu(); el.focus(); }
      else if (ev.key === "Enter") { ev.preventDefault(); if (idx >= 0) { el.focus(); items[parseInt(btns[idx].dataset.idx)].fn(); closeMenu(); } }
    });
    menu.style.left = e.clientX + "px";
    menu.style.top = e.clientY + "px";
    document.body.appendChild(menu);
    var rect = menu.getBoundingClientRect();
    if (rect.right > window.innerWidth) menu.style.left = (window.innerWidth - rect.width - 4) + "px";
    if (rect.bottom > window.innerHeight) menu.style.top = (window.innerHeight - rect.height - 4) + "px";
    var firstEnabled = menu.querySelector("button:not(:disabled)");
    if (firstEnabled) firstEnabled.focus();
  });
})();

// Custom confirm modal — replaces window.confirm so we can show richer content.
// Falls back to window.confirm when tests stub it (detected via string contains).
function _confirmModal(message, detail) {
  // Test shim: when tests override window.confirm, reuse it for determinism.
  if (window.confirm !== _origConfirm) {
    return Promise.resolve(window.confirm(message + (detail ? "\n\n" + window.i18n.t("modal.source_label") + detail : "")));
  }
  return new Promise((resolve) => {
    var backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    var box = document.createElement("div");
    box.className = "modal-box";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    var msg = document.createElement("p");
    msg.className = "modal-message";
    msg.textContent = message;
    box.appendChild(msg);
    if (detail) {
      var d = document.createElement("p");
      d.className = "modal-detail";
      d.textContent = window.i18n.t("modal.source_label") + detail;
      box.appendChild(d);
    }
    var btns = document.createElement("div");
    btns.className = "modal-buttons";
    var cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = window.i18n.t("modal.cancel");
    cancel.className = "modal-cancel";
    var ok = document.createElement("button");
    ok.type = "button";
    ok.textContent = window.i18n.t("modal.ok");
    ok.className = "modal-ok";
    btns.appendChild(cancel);
    btns.appendChild(ok);
    box.appendChild(btns);
    backdrop.appendChild(box);
    document.body.appendChild(backdrop);
    function close(v) { document.removeEventListener("keydown", trap); backdrop.remove(); resolve(v); }
    cancel.addEventListener("click", () => close(false));
    ok.addEventListener("click", () => close(true));
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) close(false);
    });
    var focusable = [cancel, ok];
    document.addEventListener("keydown", function trap(e) {
      if (e.key === "Escape") {
        close(false);
        return;
      }
      if (e.key === "Tab") {
        e.preventDefault();
        var idx = focusable.indexOf(document.activeElement);
        if (e.shiftKey) idx = (idx <= 0) ? focusable.length - 1 : idx - 1;
        else idx = (idx + 1) % focusable.length;
        focusable[idx].focus();
      }
    });
    ok.focus();
  });
}
var _origConfirm = window.confirm;

function clearResults() {
  activeUPlots.forEach(u => u.destroy());
  activeUPlots = [];
  chartCanvasRefs = [];
  resultsEl.className = "";
  resultsEl.innerHTML = "";
  lastData = null;
  _displayedSources = [];
}

function _setDisplayedSources(arr) {
  _displayedSources = (arr || []).filter(function(s) { return !!s; });
}

// If the rendered chart no longer reflects compareSources, drop it so the
// user is not misled by a stale chart attached to an edited track list.
function _maybeInvalidateResults() {
  if (!lastData) return;
  if (lastData.tracks) {
    if (_displayedSources.length !== compareSources.length) {
      clearResults();
      return;
    }
    for (var i = 0; i < compareSources.length; i++) {
      if (_displayedSources[i] !== compareSources[i]) {
        clearResults();
        return;
      }
    }
  } else {
    // single render: any track edits move the user toward compare prep,
    // making the single chart no longer the relevant view.
    if (compareSources.length > 0) clearResults();
  }
}

function safeName(label) {
  return (label || "untitled").replace(/[\x00-\x1f\\/:*?"<>|]/g, "_").slice(0, 80);
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
  return _effectiveTrackCount() >= 2 ? window.i18n.t("btn.compare") : window.i18n.t("btn.analyze");
}

function setBusy(busy) {
  isBusy = busy;
  browseBtn.disabled = busy;
  loadBtn.disabled = busy;
  addBtn.disabled = busy;
  clearBtn.disabled = busy;
  if (busy) {
    submitBtn.textContent = window.i18n.t("btn.cancel");
    submitBtn.classList.add("cancelling");
    submitBtn.setAttribute("aria-label", window.i18n.t("btn.cancel.aria"));
    statusEl.classList.add("loading");
    statusEl.setAttribute("aria-busy", "true");
  } else {
    submitBtn.textContent = _submitLabel();
    submitBtn.classList.remove("cancelling");
    submitBtn.removeAttribute("aria-label");
    statusEl.classList.remove("loading");
    statusEl.removeAttribute("aria-busy");
    activeAbort = null;
  }
  submitBtn.disabled = false;
  // Update track remove / reorder buttons (disabled during processing)
  document.querySelectorAll(".remove-track").forEach((btn) => {
    btn.disabled = busy;
  });
  document.querySelectorAll(".reorder-track").forEach((btn) => {
    if (btn.classList.contains("reorder-placeholder")) return;
    btn.disabled = busy;
  });
}


function _swapTracks(i, j) {
  if (j < 0 || j >= compareSources.length) return;

  // FLIP animation: record initial positions before DOM update
  var prevItems = trackList.querySelectorAll(".track-item");
  var prevRectI = prevItems[i] ? prevItems[i].getBoundingClientRect() : null;
  var prevRectJ = prevItems[j] ? prevItems[j].getBoundingClientRect() : null;

  var tmp = compareSources[i];
  compareSources[i] = compareSources[j];
  compareSources[j] = tmp;
  if (lastData && lastData.tracks && i < lastData.tracks.length && j < lastData.tracks.length) {
    var tt = lastData.tracks[i];
    lastData.tracks[i] = lastData.tracks[j];
    lastData.tracks[j] = tt;
    updateCompareUI();
    _reRenderCharts();
  } else {
    updateCompareUI();
  }

  var nextItems = trackList.querySelectorAll(".track-item");
  _flipTrackRow(nextItems[j], prevRectI);
  _flipTrackRow(nextItems[i], prevRectJ);
}

function _flipTrackRow(el, prevRect) {
  if (!el || !prevRect) return;
  var nextRect = el.getBoundingClientRect();
  var dy = prevRect.top - nextRect.top;
  if (!dy) return;
  el.style.transition = "none";
  el.style.transform = "translateY(" + dy + "px)";
  el.getBoundingClientRect();
  el.style.transition = "transform 220ms ease";
  el.style.transform = "";
  el.addEventListener("transitionend", function cleanup(ev) {
    if (ev.propertyName !== "transform") return;
    el.style.transition = "";
    el.style.transform = "";
    el.removeEventListener("transitionend", cleanup);
  });
}

function updateCompareUI() {
  trackList.innerHTML = "";
  for (let i = 0; i < compareSources.length; i++) {
    const item = document.createElement("div");
    item.className = "track-item";
    item.setAttribute("role", "listitem");
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
    const upBtn = document.createElement("button");
    upBtn.type = "button";
    upBtn.className = "reorder-track";
    upBtn.textContent = "\u2191";
    upBtn.setAttribute("aria-label", window.i18n.t("track.move_up_prefix") + compareSources[i] + window.i18n.t("track.move_up_suffix"));
    if (i === 0) {
      upBtn.classList.add("reorder-placeholder");
      upBtn.disabled = true;
      upBtn.setAttribute("aria-hidden", "true");
      upBtn.tabIndex = -1;
    } else {
      upBtn.disabled = isBusy;
    }
    upBtn.addEventListener("click", () => _swapTracks(i, i - 1));
    item.appendChild(upBtn);
    const downBtn = document.createElement("button");
    downBtn.type = "button";
    downBtn.className = "reorder-track";
    downBtn.textContent = "\u2193";
    downBtn.setAttribute("aria-label", window.i18n.t("track.move_down_prefix") + compareSources[i] + window.i18n.t("track.move_down_suffix"));
    if (i === compareSources.length - 1) {
      downBtn.classList.add("reorder-placeholder");
      downBtn.disabled = true;
      downBtn.setAttribute("aria-hidden", "true");
      downBtn.tabIndex = -1;
    } else {
      downBtn.disabled = isBusy;
    }
    downBtn.addEventListener("click", () => _swapTracks(i, i + 1));
    item.appendChild(downBtn);
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "remove-track";
    removeBtn.textContent = "\u00d7";
    removeBtn.tabIndex = 0;
    removeBtn.setAttribute("aria-label", window.i18n.t("track.remove_prefix") + compareSources[i] + window.i18n.t("track.remove_suffix"));
    removeBtn.disabled = isBusy;
    removeBtn.addEventListener("click", () => {
      compareSources.splice(i, 1);
      updateCompareUI();
      _maybeInvalidateResults();
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

function _setStatusNormal() {
  // Keep the .loading modifier so the spinner persists across status updates.
  statusEl.classList.remove("error");
  statusEl.setAttribute("role", "status");
  statusEl.setAttribute("aria-live", "polite");
  _lastErrorMessage = null;
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
    showError(window.i18n.t("err.max_tracks"));
    return;
  }

  // Determine mode from effective source count
  var isCompare = compareSources.length >= 2;
  var singleSource = null;
  if (!isCompare) {
    singleSource = compareSources.length === 1 ? compareSources[0] : pending;
    if (!singleSource) return;
  }

  statusEl.textContent = isCompare ? window.i18n.t("status.starting_comparison") : window.i18n.t("status.starting");
  _setStatusNormal();
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
      statusEl.textContent = window.i18n.t("status.cancelled");
      _setStatusNormal();
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
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      showError(err.error || `HTTP ${resp.status}`);
      return;
    }
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
    showError(window.i18n.t("err.max_tracks"));
    return;
  }
  if (compareSources.indexOf(url) !== -1) {
    showError(window.i18n.t("err.duplicate_track"));
    return;
  }
  compareSources.push(url);
  urlInput.value = "";
  urlInput.focus();
  updateCompareUI();
  _maybeInvalidateResults();
});

// Clear all tracks
clearBtn.addEventListener("click", () => {
  compareSources.length = 0;
  updateCompareUI();
  clearResults();
  statusEl.textContent = "";
  _setStatusNormal();
});

// Load JSON
loadBtn.addEventListener("click", async () => {
  if (isBusy) return;
  setBusy(true);
  statusEl.textContent = window.i18n.t("status.opening_file");
  _setStatusNormal();

  var loadAbort = new AbortController();
  var loadTimer = setTimeout(function () { loadAbort.abort(); }, 120000);
  try {
    const resp = await fetch(window.location.origin + "/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
      signal: loadAbort.signal,
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      showError(err.error || `HTTP ${resp.status}`);
      return;
    }
    const result = await resp.json();

    if (result.error) {
      showError(result.error);
      return;
    }
    if (!result.loaded) {
      statusEl.textContent = "";
      return;
    }

    // Loaded sources are routed through one of three paths so the resulting
    // UI state is predictable regardless of pre-existing tracks:
    //   1. solo render: only when the user starts from a clean slate
    //      (no tracks, no pending input).  Renders the single chart and
    //      mirrors the source into urlInput so a re-analyze is one click away.
    //   2. queue add: every other case.  Pending input + each loaded source
    //      are appended to compareSources; the chart area is left untouched
    //      except via _maybeInvalidateResults when the visible chart no
    //      longer matches the queue.
    //   3. as-is render: outdated schema, declined re-analysis.  Best-effort
    //      display of legacy data without touching compareSources / urlInput.

    if (result.schema_outdated) {
      var src = result.source || "";
      if (!result.source_available) {
        showError(window.i18n.t("err.outdated_no_source") + src);
        return;
      }
      var accepted = await _confirmModal(
        window.i18n.t("modal.outdated_prompt"),
        src
      );
      if (accepted) {
        // Outdated data is not cached server-side — queue the source so the
        // user can re-analyze fresh via Analyze/Compare.
        _loadAddToQueue([src]);
      } else {
        // Best-effort display of legacy fields. compareSources / urlInput
        // are left intact; the user remains in whatever state they were in.
        clearResults();
        lastDuration = null;
        statusEl.textContent = "";
        renderSingle(result.data);
      }
      return;
    }

    if (result.type === "multi") {
      var loadedSources = [];
      for (var i = 0; i < result.items.length; i++) {
        var item = result.items[i];
        var s = item.meta && item.meta.source;
        if (s) loadedSources.push(s);
      }
      _loadAddToQueue(loadedSources);
      return;
    }

    // single, latest schema
    var src = result.data.meta && result.data.meta.source;
    var initiallyEmpty = compareSources.length === 0 && !urlInput.value.trim();
    if (initiallyEmpty) {
      clearResults();
      if (src) {
        urlInput.value = src;
        lastSource = src;
      }
      lastDuration = null;
      statusEl.textContent = "";
      renderSingle(result.data);
    } else {
      _loadAddToQueue(src ? [src] : []);
    }
  } catch (err) {
    if (err.name === "AbortError") {
      showError(window.i18n.t("err.dialog_timeout"));
    } else {
      showError(err.message);
    }
  } finally {
    clearTimeout(loadTimer);
    setBusy(false);
  }
});

// Append loaded sources (plus any pending urlInput value) to compareSources.
// Reports total queued and how many were skipped due to dup/cap.
function _loadAddToQueue(loadedSources) {
  var pending = urlInput.value.trim();
  if (pending) _tryAddTrack(pending);
  urlInput.value = "";
  var skipped = 0;
  for (var i = 0; i < loadedSources.length; i++) {
    if (!_tryAddTrack(loadedSources[i])) skipped++;
  }
  updateCompareUI();
  _maybeInvalidateResults();
  if (compareSources.length >= 2) {
    var msg = compareSources.length + window.i18n.t("status.tracks_ready");
    if (skipped > 0) {
      msg += " (" + skipped + window.i18n.t("status.skipped_max_suffix");
    }
    statusEl.textContent = msg;
  } else {
    statusEl.textContent = "";
  }
  _setStatusNormal();
}

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

  // Stream closed cleanly but no result event was emitted — typically a
  // TCP reset or the server dropped the connection before flushing the
  // final line.  Surface this as "Connection interrupted" rather than the
  // older generic "No result" message which misled users into thinking the
  // analysis simply returned nothing.
  if (!result) throw new Error(window.i18n.t("err.stream_interrupted"));
  return result;
}

function _addCanvasChart(title, height, renderFn, renderArg) {
  const div = document.createElement("div");
  div.className = "chart-row";
  _chartTitle(div, title);
  const canvas = document.createElement("canvas");
  canvas.style.height = height;
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", title);
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
  if (uplot.ctx) {
    uplot.ctx.canvas.setAttribute("role", "img");
    uplot.ctx.canvas.setAttribute("aria-label", title);
    chartCanvasRefs.push({canvas: uplot.ctx.canvas, title: title});
  }
}

function renderSingle(data) {
  lastData = data;
  resultsEl.className = "visible";
  chartCanvasRefs = [];

  const titleRow = document.createElement("div");
  titleRow.className = "title-row";

  const titleEl = document.createElement("div");
  titleEl.className = "result-title";
  titleEl.textContent = data.label || window.i18n.t("result.analysis");
  titleRow.appendChild(titleEl);

  appendSaveButtons(titleRow, data);
  resultsEl.appendChild(titleRow);

  renderMeta(data.meta);
  renderSingleSummary(data);

  _addSpectrumChart("PSD Spectrum", [data]);
  _addCanvasChart("1/3 Octave Band Analysis", "300px", renderOctave, [data]);
  _addCanvasChart("Low-End Detail", "280px", renderLowEnd, [data]);
  _addCanvasChart("Mid-High Detail", "280px", renderMidHigh, [data]);

  _setDisplayedSources([data.meta && data.meta.source]);
  resultsEl.focus({ preventScroll: true });
}

function renderCompare(data) {
  lastData = data;
  resultsEl.className = "visible";
  chartCanvasRefs = [];

  const titleRow = document.createElement("div");
  titleRow.className = "title-row";

  const titleEl = document.createElement("div");
  titleEl.className = "result-title";
  titleEl.textContent = window.i18n.t("result.comparison");
  titleRow.appendChild(titleEl);

  // Save Image only (no JSON save for compare mode)
  const saveImgBtn = document.createElement("button");
  saveImgBtn.className = "save-btn";
  saveImgBtn.textContent = window.i18n.t("btn.save_image");
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

  _setDisplayedSources(data.tracks.map(function(t) {
    return t.meta && t.meta.source;
  }));
  resultsEl.focus({ preventScroll: true });
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
  if (meta.sources) parts.push(meta.sources.length + " " + window.i18n.t("meta.tracks"));
  el.textContent = parts.join(" | ");
  resultsEl.appendChild(el);
}

var _TIP_KEYS = {
  "Duration": "tip.duration",
  "RMS": "tip.rms",
  "True Peak": "tip.true_peak",
  "Crest": "tip.crest",
  "Low/Intel Ratio": "tip.low_intel",
  "Low/Intel": "tip.low_intel",
  "Spectral Centroid": "tip.centroid",
  "Centroid": "tip.centroid",
  "HPF -3dB": "tip.hpf",
  "Tilt": "tip.tilt",
  "Pres/Mid": "tip.pres_mid",
  "Bright": "tip.bright",
  "HF Rolloff": "tip.hf_rolloff",
  "Sub (20-80)": "tip.sub",
  "Low (80-200)": "tip.low",
  "Low-Mid (200-500)": "tip.low_mid",
  "Mid (500-2k)": "tip.mid",
  "Presence (2-5k)": "tip.presence",
  "Air (5-10k)": "tip.air",
  "PSD Spectrum": "tip.chart_psd",
  "1/3 Octave Band Analysis": "tip.chart_octave",
  "Transfer Function": "tip.chart_transfer",
  "Low-End Detail": "tip.chart_lowend",
  "Mid-High Detail": "tip.chart_midhigh",
};

function _tipFor(key) {
  var tipKey = _TIP_KEYS[key];
  return tipKey ? () => window.i18n.t(tipKey) : undefined;
}

function _chartTitle(parent, text) {
  var el = document.createElement("div");
  el.className = "chart-title";
  el.textContent = window.i18n.t(text);
  var tip = _tipFor(text);
  if (tip) _addTip(el, tip);
  parent.appendChild(el);
}

// Tooltip system — positions dynamically to stay within viewport
var _tipEl = null;
var _tipTimer = null;
var _tipAnchor = null;
var _tipSeq = 0;
function _showTip(anchor, text) {
  _hideTip();
  _tipAnchor = anchor;
  _tipTimer = setTimeout(() => {
    _tipEl = document.createElement("div");
    _tipEl.className = "tip-popup";
    _tipEl.setAttribute("role", "tooltip");
    _tipEl.id = anchor.getAttribute("aria-describedby") || ("tip-" + (++_tipSeq));
    anchor.setAttribute("aria-describedby", _tipEl.id);
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
  if (_tipAnchor) _tipAnchor.removeAttribute("aria-describedby");
  _tipAnchor = null;
  if (_tipEl) { _tipEl.remove(); _tipEl = null; }
}

function _addTip(cell, textOrFn) {
  cell.className = (cell.className ? cell.className + " " : "") + "has-tip";
  cell.tabIndex = 0;
  var resolve = typeof textOrFn === "function" ? textOrFn : () => textOrFn;
  cell.addEventListener("mouseenter", () => _showTip(cell, resolve()));
  cell.addEventListener("mouseleave", _hideTip);
  cell.addEventListener("focus", () => _showTip(cell, resolve()));
  cell.addEventListener("blur", _hideTip);
}

document.addEventListener("keydown", (e) => {
  if (e.isComposing || e.keyCode === 229) return;
  if (e.key === "Escape" && activeAbort) {
    e.preventDefault();
    cancelActive();
    return;
  }
  if (e.key === "Escape" && _tipEl) _hideTip();
});

function _addRow(table, cells, isHeader) {
  const row = document.createElement("tr");
  for (const text of cells) {
    const cell = document.createElement(isHeader ? "th" : "td");
    cell.textContent = isHeader ? window.i18n.t(text) : text;
    if (isHeader) {
      var tip = _tipFor(text);
      if (tip) _addTip(cell, tip);
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
  function _sdb(v) { return v == null ? "N/A" : fmtSign(v, 1) + " dB"; }
  return {
    rms: fmt(t.rms_dbfs, 1) + " dBFS",
    peak: fmt(t.true_peak_dbtp, 1) + " dBTP",
    crest: fmt(s.crest_factor_db, 1) + " dB",
    lowIntel: _sdb(s.low_intel_ratio_db),
    centroid: fmt(s.spectral_centroid_hz, 0) + " Hz",
    tilt: fmt(s.spectral_tilt_db_oct, 1) + " dB/oct",
    presMid: _sdb(s.presence_mid_ratio_db),
    bright: _sdb(s.brightness_db),
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

  _addRow(table, ["Duration", "RMS", "True Peak", "Crest"], true);
  _addRow(table, [
    fmt(data.duration_sec, 2) + "s",
    m.rms, m.peak, m.crest,
  ], false);
  _addRow(table, ["Tilt", "Low/Intel Ratio", "Spectral Centroid",
    "Pres/Mid", "Bright", "HPF -3dB", "HF Rolloff"], true);
  _addRow(table, [
    m.tilt, m.lowIntel, m.centroid, m.presMid, m.bright, m.hpf, m.hfRolloff,
  ], false);
  _addRow(table, ["Sub (20-80)", "Low (80-200)", "Low-Mid (200-500)",
    "Mid (500-2k)", "Presence (2-5k)", "Air (5-10k)"], true);
  _addRow(table, [
    m.sub, m.low, m.lowMid, m.mid, m.presence, m.air,
  ], false);

  resultsEl.appendChild(table);
}

function renderCompareSummary(tracks) {
  var specs = _buildSummaryTables({ tracks: tracks });
  for (var ti = 0; ti < specs.length; ti++) {
    var spec = specs[ti];
    const table = document.createElement("table");
    table.className = "summary-table";
    _addRow(table, spec.header, true);
    for (var r = 0; r < spec.rows.length; r++) {
      const row = document.createElement("tr");
      const labelCell = document.createElement("td");
      labelCell.className = "label-cell";
      labelCell.textContent = r === 0 ? spec.rows[r][0] + window.i18n.t("label.ref_suffix") : spec.rows[r][0];
      row.appendChild(labelCell);
      for (var ci = 1; ci < spec.rows[r].length; ci++) {
        const cell = document.createElement("td");
        cell.textContent = spec.rows[r][ci];
        row.appendChild(cell);
      }
      table.appendChild(row);
    }
    resultsEl.appendChild(table);
  }
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
    if (i === 0) {
      swatch.style.outline = "2px solid var(--text)";
      swatch.style.outlineOffset = "1px";
    }
    item.appendChild(swatch);
    const label = document.createElement("span");
    label.textContent = i === 0 ? tracks[i].label + window.i18n.t("label.ref_suffix") : tracks[i].label;
    item.appendChild(label);
    bar.appendChild(item);
  }
  resultsEl.appendChild(bar);
}

function appendSaveButtons(container, data) {
  const saveBtn = document.createElement("button");
  saveBtn.className = "save-btn";
  saveBtn.textContent = window.i18n.t("btn.save_json");
  saveBtn.addEventListener("click", () => saveResult(data));
  container.appendChild(saveBtn);

  const saveImgBtn = document.createElement("button");
  saveImgBtn.className = "save-btn";
  saveImgBtn.textContent = window.i18n.t("btn.save_image");
  saveImgBtn.addEventListener("click", () => saveImage(data));
  container.appendChild(saveImgBtn);
}

function fmt(val, decimals) {
  if (val == null || !isFinite(val)) return "?";
  return val.toFixed(decimals);
}

function fmtSign(val, decimals) {
  if (val == null || !isFinite(val)) return "?";
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
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      showError(window.i18n.t("err.save_failed") + (err.error || ("HTTP " + resp.status)));
      return;
    }
    const result = await resp.json();
    if (result.saved) {
      statusEl.textContent = window.i18n.t("status.saved") + result.path;
      _setStatusNormal();
    } else if (result.error) {
      showError(window.i18n.t("err.save_failed") + result.error);
    }
  } catch (err) {
    showError(window.i18n.t("err.save_failed") + err.message);
  }
}

function _buildSummaryTables(data) {
  if (data.tracks) {
    var table1 = {
      header: ["Track", "Duration", "RMS", "True Peak", "Crest"],
      rows: data.tracks.map((t) => {
        var m = _formatTrackMetrics(t);
        return [t.label, fmt(t.duration_sec, 2) + "s", m.rms, m.peak, m.crest];
      }),
    };
    var table2 = {
      header: ["Track", "Tilt", "Low/Intel", "Centroid", "Pres/Mid", "Bright", "HPF -3dB", "HF Rolloff"],
      rows: data.tracks.map((t) => {
        var m = _formatTrackMetrics(t);
        return [t.label, m.tilt, m.lowIntel, m.centroid, m.presMid, m.bright, m.hpf, m.hfRolloff];
      }),
    };
    var table3 = {
      header: ["Track", "Sub (20-80)", "Low (80-200)", "Low-Mid (200-500)", "Mid (500-2k)", "Presence (2-5k)", "Air (5-10k)"],
      rows: data.tracks.map((t) => {
        var m = _formatTrackMetrics(t);
        return [t.label, m.sub, m.low, m.lowMid, m.mid, m.presence, m.air];
      }),
    };
    return [table1, table2, table3];
  }
  var m = _formatTrackMetrics(data);
  var t1 = {
    header: ["Duration", "RMS", "True Peak", "Crest"],
    rows: [[fmt(data.duration_sec, 2) + "s", m.rms, m.peak, m.crest]],
  };
  var t2 = {
    header: ["Tilt", "Low/Intel Ratio", "Spectral Centroid", "Pres/Mid", "Bright", "HPF -3dB", "HF Rolloff"],
    rows: [[m.tilt, m.lowIntel, m.centroid, m.presMid, m.bright, m.hpf, m.hfRolloff]],
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
    ctx.fillText(window.i18n.t(header[i]), cx + colWidths[i] / 2, y + ROW_H / 2);
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

  if (chartSizes.length === 0) {
    showError(window.i18n.t("err.charts_not_ready"));
    return null;
  }

  const comp = document.createElement("canvas");
  comp.width = W * SCALE;
  comp.height = totalH * SCALE;
  const ctx = comp.getContext("2d");
  ctx.scale(SCALE, SCALE);

  var dark = isDark();
  ctx.fillStyle = dark ? "#1a1a2e" : "#fff";
  ctx.fillRect(0, 0, W, totalH);

  let y = PAD;

  const title = data.label || (data.tracks ? window.i18n.t("result.comparison") : window.i18n.t("result.analysis"));
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
    ctx.fillText(window.i18n.t(title), W / 2, y + 16);
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
    const dataUrl = captureImage(data);
    if (!dataUrl) return;
    statusEl.textContent = window.i18n.t("status.generating_image");
    _setStatusNormal();
    const resp = await fetch(window.location.origin + "/save-image", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dataUrl, filename }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      showError(window.i18n.t("err.save_failed") + (err.error || ("HTTP " + resp.status)));
      return;
    }
    const result = await resp.json();
    if (result.saved) {
      statusEl.textContent = window.i18n.t("status.saved") + result.path;
      _setStatusNormal();
    } else if (result.error) {
      showError(window.i18n.t("err.save_failed") + result.error);
    } else {
      statusEl.textContent = "";
    }
  } catch (err) {
    showError(window.i18n.t("err.save_failed") + err.message);
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

  const files = Array.from(e.dataTransfer.files);
  if (!files.length) return;

  const MAX_UPLOAD_BYTES = 500 * 1024 * 1024;

  for (const file of files) {
    // Reject oversize files before uploading so the user sees the error
    // immediately instead of waiting for the server to stream-reject.
    if (file.size > MAX_UPLOAD_BYTES) {
      showError(window.i18n.t("err.file_too_large"));
      continue;
    }
    statusEl.textContent = window.i18n.t("status.uploading") + file.name;
    _setStatusNormal();
    try {
      const resp = await fetch(window.location.origin + "/upload", {
        method: "POST",
        headers: {
          "Content-Type": "application/octet-stream",
          "X-Filename": encodeURIComponent(file.name),
        },
        body: file,
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        showError(err.error || `HTTP ${resp.status}`);
        continue;
      }
      const result = await resp.json();
      if (result.uploaded) {
        if (files.length === 1 && !urlInput.value.trim()) {
          urlInput.value = result.path;
          urlInput.focus();
        } else if (files.length === 1) {
          _tryAddTrack(urlInput.value.trim());
          urlInput.value = result.path;
          updateCompareUI();
          urlInput.focus();
        } else {
          compareSources.push(result.path);
          updateCompareUI();
        }
        statusEl.textContent = window.i18n.t("status.file_loaded") + file.name;
      } else if (result.error) {
        showError(result.error);
        continue;
      }
    } catch (err) {
      showError(err.message);
      continue;
    }
  }
}, true);

// Remembers the last showError message so language toggles can retranslate
// the "Error: " prefix and the Copy button label in place.
var _lastErrorMessage = null;

function showError(message) {
  _lastErrorMessage = message;
  statusEl.setAttribute("role", "alert");
  statusEl.setAttribute("aria-live", "assertive");
  statusEl.classList.remove("loading");
  statusEl.classList.add("error");
  statusEl.textContent = "";
  const icon = document.createElement("span");
  icon.className = "error-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = "\u26A0";
  statusEl.appendChild(icon);
  const text = document.createElement("span");
  text.className = "error-text";
  text.textContent = window.i18n.t("err.prefix") + message;
  statusEl.appendChild(text);
  if (navigator.clipboard) {
    const btn = document.createElement("button");
    btn.className = "copy-btn";
    btn.textContent = window.i18n.t("btn.copy");
    btn.addEventListener("click", () => {
      navigator.clipboard.writeText(message).then(() => {
        btn.textContent = window.i18n.t("btn.copied");
        setTimeout(() => { btn.textContent = window.i18n.t("btn.copy"); }, 1500);
      }).catch(() => {
        btn.textContent = window.i18n.t("btn.copy_failed");
        setTimeout(() => { btn.textContent = window.i18n.t("btn.copy"); }, 1500);
      });
    });
    statusEl.appendChild(btn);
  }
}
