/**
 * Low-end detail chart: linear frequency 20-500Hz PSD overlay on Canvas.
 * Highlights sub, low, and low-mid bands with shading.
 */

function _bandRegionColors() {
  var dark = isDark();
  return [
    { lo: 20, hi: 80, label: "Sub", color: dark ? "rgba(100,181,246,0.08)" : "rgba(25,118,210,0.06)" },
    { lo: 80, hi: 200, label: "Low", color: dark ? "rgba(102,187,106,0.08)" : "rgba(56,142,60,0.06)" },
    { lo: 200, hi: 500, label: "Low-Mid", color: dark ? "rgba(255,167,38,0.08)" : "rgba(245,124,0,0.06)" },
  ];
}

function renderLowEnd(canvas, tracks) {
  var theme = getThemeColors();
  var bandRegions = _bandRegionColors();
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

  var fMin = 20, fMax = 500;
  var fRange = fMax - fMin;

  // Find y range from all tracks in this freq range
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
  for (var r = 0; r < bandRegions.length; r++) {
    var region = bandRegions[r];
    var x1 = pad.left + ((region.lo - fMin) / fRange) * pw;
    var x2 = pad.left + ((Math.min(region.hi, fMax) - fMin) / fRange) * pw;
    ctx.fillStyle = region.color;
    ctx.fillRect(x1, pad.top, x2 - x1, ph);

    // Region label
    ctx.fillStyle = theme.textMuted;
    ctx.font = "10px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(region.label, (x1 + x2) / 2, pad.top + 12);
  }

  // Grid lines
  ctx.strokeStyle = theme.gridStrong;
  ctx.lineWidth = 1;
  for (var db = yMin; db <= yMax; db += 10) {
    var gy = pad.top + ph - ((db - yMin) / yRange) * ph;
    ctx.beginPath();
    ctx.moveTo(pad.left, gy);
    ctx.lineTo(pad.left + pw, gy);
    ctx.stroke();
  }

  // Vertical freq grid
  var fTicks = [20, 50, 80, 100, 150, 200, 300, 400, 500];
  ctx.strokeStyle = theme.grid;
  for (var i = 0; i < fTicks.length; i++) {
    var x = pad.left + ((fTicks[i] - fMin) / fRange) * pw;
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
      var x = pad.left + ((freqs[i] - fMin) / fRange) * pw;
      var y = pad.top + ph - ((psd[i] - yMin) / yRange) * ph;
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.stroke();

    // HPF marker
    var hpf = tracks[t].summary && tracks[t].summary.hpf_3db_hz;
    if (hpf != null && hpf >= fMin && hpf <= fMax) {
      var hx = pad.left + ((hpf - fMin) / fRange) * pw;
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
      ctx.fillText("HPF " + Math.round(hpf) + "Hz", hx, pad.top + ph + 28);
    }
  }

  // X tick labels
  ctx.fillStyle = theme.textSecondary;
  ctx.font = "10px sans-serif";
  ctx.textAlign = "center";
  for (var i = 0; i < fTicks.length; i++) {
    var x = pad.left + ((fTicks[i] - fMin) / fRange) * pw;
    ctx.fillText(fTicks[i].toString(), x, pad.top + ph + 16);
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
  ctx.fillText("Low-End Detail (20-500 Hz, Linear)", w / 2, 20);

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
