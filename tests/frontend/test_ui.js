/**
 * Frontend UI tests for analyze-spectrum.
 *
 * Runs in the browser (test_ui.html) or headless via Deno/Playwright.
 * Tests UI state management by mocking fetch() and verifying DOM state.
 */

var _passed = 0;
var _failed = 0;
var _output = document.getElementById("test-output");

function _log(cls, text) {
  var el = document.createElement("div");
  el.className = cls;
  el.textContent = text;
  _output.appendChild(el);
}

function suite(name) { _log("suite", "--- " + name + " ---"); }

function assert(condition, msg) {
  if (condition) {
    _passed++;
    _log("pass", "  PASS: " + msg);
  } else {
    _failed++;
    _log("fail", "  FAIL: " + msg);
  }
}

function assertEqual(actual, expected, msg) {
  if (actual === expected) {
    _passed++;
    _log("pass", "  PASS: " + msg);
  } else {
    _failed++;
    _log("fail", "  FAIL: " + msg + " (got " + JSON.stringify(actual) + ", expected " + JSON.stringify(expected) + ")");
  }
}

function assertIncludes(arr, val, msg) {
  assert(arr.indexOf(val) !== -1, msg);
}

// ------ Helpers ------

function resetState() {
  compareSources.length = 0;
  document.getElementById("url-input").value = "";
  lastData = null;
  lastSource = null;
  lastDuration = null;
  setBusy(false);
  document.getElementById("status").textContent = "";
  document.getElementById("results").innerHTML = "";
  updateCompareUI();
}

// Mock fetch to return controlled responses
var _fetchQueue = [];
var _origFetch = window.fetch;

function mockFetch(responseFn) {
  _fetchQueue.push(responseFn);
}

window.fetch = function(url, opts) {
  if (_fetchQueue.length > 0) {
    var fn = _fetchQueue.shift();
    return Promise.resolve(fn(url, opts));
  }
  // Fall through to stub for unmocked calls
  return Promise.resolve(new Response("{}", { status: 200 }));
};

function makeJsonResponse(obj) {
  return new Response(JSON.stringify(obj), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

// Fake analysis result
function fakeResult(source, label) {
  return {
    label: label || source,
    sample_rate: 48000,
    duration_sec: 1.0,
    rms_dbfs: -14.0,
    peak_dbfs: -3.0,
    true_peak_dbtp: -2.8,
    spectrum: { freqs: [100, 200, 400, 800], psd_db: [-30, -35, -40, -45] },
    bands: { centers: [100, 200, 400], energy_db: [-30, -35, -40] },
    summary: {
      crest_factor_db: 11.0,
      low_intel_ratio_db: 3.0,
      spectral_centroid_hz: 600,
      spectral_tilt_db_oct: -3.5,
      presence_mid_ratio_db: -2.0,
      brightness_db: -10.0,
      hpf_3db_hz: null,
      hf_rolloff_hz: 12000,
      band_energy: {
        sub_20_80: -45, low_80_200: -20, low_mid_200_500: -22,
        mid_500_2k: -25, presence_2k_5k: -27, air_5k_10k: -38,
      },
    },
    meta: { version: "1.0.0", analyzed_at: "2026-01-01T00:00:00Z", source: source },
  };
}

function fakeCompareResult(sources) {
  var tracks = sources.map(function(s) { return fakeResult(s); });
  return {
    tracks: tracks,
    transfer_functions: [{
      label: tracks[1].label + " - " + tracks[0].label,
      freqs: [100, 200, 400, 800],
      delta_db: [1, 2, -1, 0],
    }],
    meta: { version: "1.0.0", analyzed_at: "2026-01-01T00:00:00Z", sources: sources },
  };
}

function makeNdjsonResponse(type, data) {
  var ndjson = JSON.stringify({ type: type, data: data }) + "\n";
  var stream = new ReadableStream({
    start: function(controller) {
      controller.enqueue(new TextEncoder().encode(ndjson));
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "application/x-ndjson" },
  });
}

// ------ Tests ------

(async function runTests() {
  var urlInput = document.getElementById("url-input");
  var addBtn = document.getElementById("add-btn");
  var loadBtn = document.getElementById("load-btn");

  // ================================================
  suite("Add Track / Remove Track");
  // ================================================

  resetState();
  urlInput.value = "file_A.wav";
  addBtn.click();
  assertEqual(compareSources.length, 1, "Add first track");
  assertEqual(compareSources[0], "file_A.wav", "First track is file_A");
  assertEqual(urlInput.value, "", "URL input cleared after add");

  urlInput.value = "file_B.wav";
  addBtn.click();
  assertEqual(compareSources.length, 2, "Add second track");

  // Remove second track — remaining track stays in compareSources (no
  // auto-collapse).  Keeps the visual track list and internal state aligned.
  var removeBtns = document.querySelectorAll(".remove-track");
  removeBtns[1].click();
  assertEqual(compareSources.length, 1, "After removing one of two, one track remains");
  assertEqual(compareSources[0], "file_A.wav", "Remaining track is file_A");
  assertEqual(urlInput.value, "", "URL input untouched by remove");

  // ================================================
  suite("Duplicate track rejected");
  // ================================================

  resetState();
  urlInput.value = "dup.wav";
  addBtn.click();
  urlInput.value = "dup.wav";
  addBtn.click();
  assertEqual(compareSources.length, 1, "Duplicate not added");

  // ================================================
  suite("Max 6 tracks");
  // ================================================

  resetState();
  for (var i = 1; i <= 7; i++) {
    urlInput.value = "track_" + i + ".wav";
    addBtn.click();
  }
  assertEqual(compareSources.length, 6, "Capped at 6 tracks");

  // ================================================
  suite("Load JSON — single file, no pending");
  // ================================================

  resetState();
  mockFetch(function() {
    return makeJsonResponse({
      loaded: true,
      type: "single",
      data: fakeResult("/path/to/single.wav"),
    });
  });
  loadBtn.click();
  await new Promise(function(r) { setTimeout(r, 200); });

  assertEqual(urlInput.value, "/path/to/single.wav", "Single load restores URL");
  assertEqual(compareSources.length, 0, "compareSources empty for single load");

  // ================================================
  suite("Load JSON — single file, with pending source in urlInput");
  // ================================================

  resetState();
  urlInput.value = "pending_A.wav";
  mockFetch(function() {
    return makeJsonResponse({
      loaded: true,
      type: "single",
      data: fakeResult("loaded_B.wav"),
    });
  });
  loadBtn.click();
  await new Promise(function(r) { setTimeout(r, 200); });

  assertEqual(compareSources.length, 2, "Pending + loaded = 2 tracks in compare mode");
  assertIncludes(compareSources, "pending_A.wav", "Pending source preserved");
  assertIncludes(compareSources, "loaded_B.wav", "Loaded source added");
  assertEqual(urlInput.value, "", "URL input cleared in compare mode");

  // ================================================
  suite("Load JSON — multi file, with pending source");
  // ================================================

  resetState();
  urlInput.value = "existing.wav";
  mockFetch(function() {
    return makeJsonResponse({
      loaded: true,
      type: "multi",
      items: [fakeResult("new_1.wav"), fakeResult("new_2.wav")],
    });
  });
  loadBtn.click();
  await new Promise(function(r) { setTimeout(r, 200); });

  assertEqual(compareSources.length, 3, "Pending + 2 loaded = 3 tracks");
  assertIncludes(compareSources, "existing.wav", "Pending preserved in multi load");
  assertIncludes(compareSources, "new_1.wav", "First loaded track added");
  assertIncludes(compareSources, "new_2.wav", "Second loaded track added");

  // ================================================
  suite("Load JSON — multi file deduplication");
  // ================================================

  resetState();
  compareSources.push("dup.wav");
  updateCompareUI();
  mockFetch(function() {
    return makeJsonResponse({
      loaded: true,
      type: "multi",
      items: [fakeResult("dup.wav"), fakeResult("new.wav")],
    });
  });
  loadBtn.click();
  await new Promise(function(r) { setTimeout(r, 200); });

  assertEqual(compareSources.length, 2, "Duplicate not added in multi load");
  assertIncludes(compareSources, "dup.wav", "Original dup preserved");
  assertIncludes(compareSources, "new.wav", "New track added");

  // ================================================
  suite("Load JSON — schema_outdated accepted adds source as track");
  // ================================================

  resetState();
  var _origConfirm = window.confirm;
  window.confirm = function() { return true; };
  mockFetch(function() {
    return makeJsonResponse({
      loaded: true,
      type: "single",
      schema_outdated: true,
      source: "https://example.com/test.mp4",
      source_available: true,
      data: fakeResult("https://example.com/test.mp4"),
    });
  });
  loadBtn.click();
  await new Promise(function(r) { setTimeout(r, 200); });

  // Outdated data is queued (not cached server-side) so Submit re-analyzes.
  // The source goes into compareSources, not urlInput, keeping the queue-add
  // path consistent with multi load.
  assertEqual(urlInput.value, "", "URL input cleared by queue-add");
  assertEqual(compareSources.length, 1, "Outdated source queued as track");
  assertEqual(compareSources[0], "https://example.com/test.mp4", "Source queued");
  window.confirm = _origConfirm;

  // ================================================
  suite("Load JSON — schema_outdated accepted preserves existing tracks");
  // ================================================

  resetState();
  window.confirm = function() { return true; };
  urlInput.value = "existing.wav";
  addBtn.click();
  assertEqual(compareSources.length, 1, "Setup: 1 track added");

  mockFetch(function() {
    return makeJsonResponse({
      loaded: true,
      type: "single",
      schema_outdated: true,
      source: "outdated.wav",
      source_available: true,
      data: fakeResult("outdated.wav"),
    });
  });
  loadBtn.click();
  await new Promise(function(r) { setTimeout(r, 200); });

  assertEqual(compareSources.length, 2, "Existing track preserved + outdated added");
  assertIncludes(compareSources, "existing.wav", "Existing track still in list");
  assertIncludes(compareSources, "outdated.wav", "Outdated source added as track");
  assertEqual(urlInput.value, "", "URL input cleared in compare mode");
  window.confirm = _origConfirm;

  // ================================================
  suite("Load JSON — schema_outdated declined shows data as-is");
  // ================================================

  resetState();
  window.confirm = function() { return false; };
  mockFetch(function() {
    return makeJsonResponse({
      loaded: true,
      type: "single",
      schema_outdated: true,
      source: "old_file.wav",
      source_available: true,
      data: fakeResult("old_file.wav"),
    });
  });
  loadBtn.click();
  await new Promise(function(r) { setTimeout(r, 200); });

  // Declined re-analysis — data displayed as-is. compareSources / urlInput
  // are left untouched so the user keeps whatever they were preparing.
  assertEqual(urlInput.value, "", "URL input untouched by declined load");
  assertEqual(compareSources.length, 0, "compareSources untouched by declined load");
  window.confirm = _origConfirm;

  // ================================================
  suite("Load JSON — cancelled dialog");
  // ================================================

  resetState();
  urlInput.value = "keep_me.wav";
  mockFetch(function() {
    return makeJsonResponse({ loaded: false });
  });
  loadBtn.click();
  await new Promise(function(r) { setTimeout(r, 200); });

  assertEqual(urlInput.value, "keep_me.wav", "URL preserved when dialog cancelled");
  assertEqual(compareSources.length, 0, "No tracks added on cancel");

  // ================================================
  suite("Scenario: 2 tracks -> delete 1 -> Load single -> Compare ready");
  // ================================================

  resetState();
  urlInput.value = "A.wav";
  addBtn.click();
  urlInput.value = "B.wav";
  addBtn.click();
  assertEqual(compareSources.length, 2, "Setup: 2 tracks added");

  // Delete B (index 1) — A stays in compareSources (no auto-collapse), so
  // the post-delete state matches what "1 track added" looks like.  Load
  // single JSON below should now behave identically to that case.
  document.querySelectorAll(".remove-track")[1].click();
  assertEqual(urlInput.value, "", "Setup: urlInput stays empty after remove");
  assertEqual(compareSources.length, 1, "Setup: A remains in compareSources");
  assertEqual(compareSources[0], "A.wav", "Setup: remaining track is A");

  // Load single JSON
  mockFetch(function() {
    return makeJsonResponse({
      loaded: true,
      type: "single",
      data: fakeResult("C.wav"),
    });
  });
  loadBtn.click();
  await new Promise(function(r) { setTimeout(r, 200); });

  assertEqual(compareSources.length, 2, "A + C = 2 tracks");
  assertIncludes(compareSources, "A.wav", "A preserved from existing track");
  assertIncludes(compareSources, "C.wav", "C added from load");
  assertEqual(urlInput.value, "", "URL cleared in compare mode");

  // ================================================
  suite("Theme toggle cycles light -> dark -> auto");
  // ================================================

  resetState();
  var themeBtn = document.getElementById("theme-toggle");
  setThemeMode("light");
  assertEqual(document.documentElement.getAttribute("data-theme"), "light", "Theme starts light");

  themeBtn.click();
  assertEqual(document.documentElement.getAttribute("data-theme"), "dark", "Toggle to dark");

  themeBtn.click();
  // auto depends on OS, just check attribute is set
  var autoTheme = document.documentElement.getAttribute("data-theme");
  assert(autoTheme === "light" || autoTheme === "dark", "Auto resolves to light or dark");

  // ================================================
  suite("Clear All resets track list");
  // ================================================

  resetState();
  urlInput.value = "X.wav";
  addBtn.click();
  urlInput.value = "Y.wav";
  addBtn.click();
  assertEqual(compareSources.length, 2, "Setup: 2 tracks");
  document.getElementById("clear-btn").click();
  assertEqual(compareSources.length, 0, "Clear All empties tracks");
  assertEqual(document.getElementById("track-list").children.length, 0, "Track list DOM cleared");

  // ================================================
  suite("setBusy / button states");
  // ================================================

  resetState();
  setBusy(true);
  assertEqual(document.getElementById("browse-btn").disabled, true, "Browse disabled when busy");
  assertEqual(document.getElementById("add-btn").disabled, true, "Add disabled when busy");
  assertEqual(document.getElementById("submit-btn").textContent, "Cancel", "Submit shows Cancel");

  setBusy(false);
  assertEqual(document.getElementById("browse-btn").disabled, false, "Browse re-enabled");
  assertEqual(document.getElementById("submit-btn").textContent, "Analyze", "Submit shows Analyze");

  // ================================================
  suite("Submit label reflects mode");
  // ================================================

  resetState();
  assertEqual(document.getElementById("submit-btn").textContent, "Analyze", "No tracks = Analyze");
  urlInput.value = "A.wav"; addBtn.click();
  urlInput.value = "B.wav"; addBtn.click();
  assertEqual(document.getElementById("submit-btn").textContent, "Compare", "2+ tracks = Compare");

  // ================================================
  suite("P1: Remove track preserves urlInput value");
  // ================================================

  resetState();
  urlInput.value = "A.wav"; addBtn.click();
  urlInput.value = "B.wav"; addBtn.click();
  assertEqual(compareSources.length, 2, "Setup: 2 tracks");
  urlInput.value = "C.wav";  // User is typing a third source
  // Remove B — should NOT overwrite urlInput
  document.querySelectorAll(".remove-track")[1].click();
  assertEqual(compareSources.length, 1, "1 track remains in compareSources");
  assertEqual(compareSources[0], "A.wav", "A.wav stays in track list");
  assertEqual(urlInput.value, "C.wav", "urlInput value preserved");

  // ================================================
  suite("Remove track keeps remaining without collapse");
  // ================================================

  resetState();
  urlInput.value = "A.wav"; addBtn.click();
  urlInput.value = "B.wav"; addBtn.click();
  // urlInput is empty after second add. Auto-collapse was removed so the
  // remaining track stays visible in the queue.
  document.querySelectorAll(".remove-track")[1].click();
  assertEqual(compareSources.length, 1, "One track remains in queue");
  assertEqual(compareSources[0], "A.wav", "Remaining track is A");
  assertEqual(urlInput.value, "", "urlInput stays empty");

  // ================================================
  suite("P3: Submit label updates with urlInput (input event)");
  // ================================================

  resetState();
  urlInput.value = "A.wav"; addBtn.click();
  assertEqual(document.getElementById("submit-btn").textContent, "Analyze", "1 track = Analyze");
  urlInput.value = "B.wav";
  urlInput.dispatchEvent(new Event("input"));
  assertEqual(document.getElementById("submit-btn").textContent, "Compare", "1 track + urlInput = Compare");
  urlInput.value = "";
  urlInput.dispatchEvent(new Event("input"));
  assertEqual(document.getElementById("submit-btn").textContent, "Analyze", "1 track + empty = Analyze");

  // ================================================
  suite("Submit promotes pending urlInput to compareSources");
  // ================================================

  resetState();
  urlInput.value = "A.wav"; addBtn.click();
  urlInput.value = "B.wav";
  // Mock the /compare NDJSON response
  mockFetch(function(url, opts) {
    return makeNdjsonResponse("compare_result", fakeCompareResult(["A.wav", "B.wav"]));
  });
  document.getElementById("submit-btn").click();
  // Verify pending was promoted before fetch
  assertIncludes(compareSources, "A.wav", "Existing track preserved");
  assertIncludes(compareSources, "B.wav", "Pending promoted to compareSources");
  assertEqual(urlInput.value, "", "urlInput cleared after promotion");
  await new Promise(function(r) { setTimeout(r, 500); });
  assert(!isBusy, "Not busy after submit completes");

  // ================================================
  suite("Submit at max capacity rejects pending with error");
  // ================================================

  resetState();
  for (var i = 1; i <= 6; i++) {
    urlInput.value = "track_" + i + ".wav";
    addBtn.click();
  }
  assertEqual(compareSources.length, 6, "Setup: 6 tracks");
  urlInput.value = "track_7.wav";
  document.getElementById("submit-btn").click();
  // Should show error and NOT submit
  assert(document.getElementById("status").textContent.indexOf("Maximum 6") !== -1,
    "Error shown for 7th track on submit");
  assertEqual(urlInput.value, "track_7.wav", "urlInput not cleared");
  assert(!isBusy, "Not busy (submit was blocked)");

  // ================================================
  suite("Submit with 1 track and empty urlInput analyzes the track");
  // ================================================

  resetState();
  urlInput.value = "solo.wav"; addBtn.click();
  assertEqual(compareSources.length, 1, "Setup: 1 track");
  assertEqual(urlInput.value, "", "urlInput empty");
  mockFetch(function(url, opts) {
    return makeNdjsonResponse("result", fakeResult("solo.wav"));
  });
  document.getElementById("submit-btn").click();
  await new Promise(function(r) { setTimeout(r, 500); });
  assert(!isBusy, "Not busy after single analysis");

  // ================================================
  // Summary
  // ================================================

  var summaryEl = document.getElementById("summary");
  var total = _passed + _failed;
  summaryEl.textContent = total + " tests: " + _passed + " passed, " + _failed + " failed";
  summaryEl.className = _failed > 0 ? "fail" : "pass";

  // Exit code for headless runners
  if (typeof Deno !== "undefined") {
    Deno.exit(_failed > 0 ? 1 : 0);
  }
  // For pytest-playwright or other automation
  window._testResult = { passed: _passed, failed: _failed };
})();
