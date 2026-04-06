/**
 * Mid-high detail chart: log frequency 500Hz-20kHz PSD overlay on Canvas.
 * Highlights mid, presence, and air bands with shading.
 */

function _midHighRegionColors() {
  var dark = isDark();
  return [
    { lo: 500, hi: 2000, label: "Mid", color: dark ? "rgba(100,181,246,0.08)" : "rgba(25,118,210,0.06)" },
    { lo: 2000, hi: 5000, label: "Presence", color: dark ? "rgba(102,187,106,0.08)" : "rgba(56,142,60,0.06)" },
    { lo: 5000, hi: 10000, label: "Air", color: dark ? "rgba(255,167,38,0.08)" : "rgba(245,124,0,0.06)" },
    { lo: 10000, hi: 20000, label: "Brilliance", color: dark ? "rgba(206,147,216,0.08)" : "rgba(123,31,162,0.06)" },
  ];
}

function renderMidHigh(canvas, tracks) {
  var theme = getThemeColors();
  var regions = _midHighRegionColors();
  var ctx = canvas.getContext("2d");
  var dpr = window.devicePixelRatio || 1;
  var w = canvas.clientWidth;
  var h = canvas.clientHeight || 280;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);

  var pad = { top: 36, right: 20, bottom: 50, left: 55 };
  var pw = w - pad.left - pad.right;
  var ph = h - pad.top - pad.bottom;

  ctx.clearRect(0, 0, w, h);

  var fMin = 500, fMax = 20000;
  var logMin = Math.log10(fMin), logMax = Math.log10(fMax);
  var logRange = logMax - logMin;

  function freqToX(f) {
    return pad.left + ((Math.log10(f) - logMin) / logRange) * pw;
  }

  // Find y range
  var yMin = Infinity, yMax = -Infinity;
  for (var t = 0; t < tracks.length; t++) {
    var freqs = tracks[t].spectrum.freqs;
    var psd = tracks[t].spectrum.psd_db;
    for (var i = 0; i < freqs.length; i++) {
      if (freqs[i] >= fMin && freqs[i] <= fMax && isFinite(psd[i])) {
        if (psd[i] < yMin) yMin = psd[i];
        if (psd[i] > yMax) yMax = psd[i];
      }
    }
  }
  yMin = Math.floor(yMin / 5) * 5 - 5;
  yMax = Math.ceil(yMax / 5) * 5 + 5;
  var yRange = yMax - yMin || 1;

  // Band region shading
  for (var r = 0; r < regions.length; r++) {
    var region = regions[r];
    var x1 = freqToX(Math.max(region.lo, fMin));
    var x2 = freqToX(Math.min(region.hi, fMax));
    ctx.fillStyle = region.color;
    ctx.fillRect(x1, pad.top, x2 - x1, ph);

    ctx.fillStyle = theme.textMuted;
    ctx.font = "10px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(region.label, (x1 + x2) / 2, pad.top + 12);
  }

  // Horizontal grid
  ctx.strokeStyle = theme.gridStrong;
  ctx.lineWidth = 1;
  for (var db = yMin; db <= yMax; db += 10) {
    var gy = pad.top + ph - ((db - yMin) / yRange) * ph;
    ctx.beginPath();
    ctx.moveTo(pad.left, gy);
    ctx.lineTo(pad.left + pw, gy);
    ctx.stroke();
  }

  // Vertical freq grid (log scale)
  var fTicks = [500, 1000, 2000, 3000, 5000, 7000, 10000, 15000, 20000];
  var fLabels = ["500", "1k", "2k", "3k", "5k", "7k", "10k", "15k", "20k"];
  ctx.strokeStyle = theme.grid;
  for (var i = 0; i < fTicks.length; i++) {
    var x = freqToX(fTicks[i]);
    ctx.beginPath();
    ctx.moveTo(x, pad.top);
    ctx.lineTo(x, pad.top + ph);
    ctx.stroke();
  }

  // Plot each track
  for (var t = 0; t < tracks.length; t++) {
    var freqs = tracks[t].spectrum.freqs;
    var psd = tracks[t].spectrum.psd_db;
    var color = theme.trackColors[t % theme.trackColors.length];

    ctx.strokeStyle = color;
    ctx.lineWidth = 1.8;
    ctx.beginPath();

    var started = false;
    for (var i = 0; i < freqs.length; i++) {
      if (freqs[i] < fMin || freqs[i] > fMax) continue;
      if (!isFinite(psd[i])) continue;
      var x = freqToX(freqs[i]);
      var y = pad.top + ph - ((psd[i] - yMin) / yRange) * ph;
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.stroke();

    // HF Rolloff marker
    var hfr = tracks[t].summary && tracks[t].summary.hf_rolloff_hz;
    if (hfr != null && hfr >= fMin && hfr <= fMax) {
      var hx = freqToX(hfr);
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(hx, pad.top);
      ctx.lineTo(hx, pad.top + ph);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = color;
      ctx.font = "9px sans-serif";
      ctx.textAlign = "center";
      var label = hfr >= 1000 ? (hfr / 1000).toFixed(1) + "kHz" : Math.round(hfr) + "Hz";
      ctx.fillText("HF " + label, hx, pad.top + ph + 28);
    }
  }

  // X tick labels
  ctx.fillStyle = theme.textSecondary;
  ctx.font = "10px sans-serif";
  ctx.textAlign = "center";
  for (var i = 0; i < fTicks.length; i++) {
    var x = freqToX(fTicks[i]);
    ctx.fillText(fLabels[i], x, pad.top + ph + 16);
  }

  // Y tick labels
  ctx.textAlign = "right";
  for (var db = yMin; db <= yMax; db += 10) {
    var gy = pad.top + ph - ((db - yMin) / yRange) * ph;
    ctx.fillText(db.toString(), pad.left - 6, gy + 3);
  }

  // Axis labels
  ctx.fillStyle = theme.text;
  ctx.font = "12px sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("Frequency (Hz)", w / 2, h - 6);

  ctx.save();
  ctx.translate(14, pad.top + ph / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("Power (dB)", 0, 0);
  ctx.restore();

  // Title
  ctx.font = "bold 13px sans-serif";
  ctx.fillText("Mid-High Detail (500 Hz - 20 kHz, Log)", w / 2, 20);

  // Legend (if multi-track)
  if (tracks.length > 1) {
    ctx.font = "10px sans-serif";
    ctx.textAlign = "right";
    for (var t = 0; t < tracks.length; t++) {
      var lx = w - pad.right - 8;
      var ly = pad.top + 14 + t * 14;
      ctx.strokeStyle = theme.trackColors[t % theme.trackColors.length];
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(lx - 12, ly - 4);
      ctx.lineTo(lx, ly - 4);
      ctx.stroke();
      ctx.fillStyle = theme.text;
      ctx.fillText(tracks[t].label, lx - 16, ly);
    }
  }
}
