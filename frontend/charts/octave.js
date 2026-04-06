/**
 * 1/3 octave band grouped bar chart on Canvas.
 * Supports multiple tracks with color-coded bars.
 */

function renderOctave(canvas, tracks) {
  if (!tracks || !tracks.length) return;
  var theme = getThemeColors();
  var ctx = canvas.getContext("2d");
  var dpr = window.devicePixelRatio || 1;
  var w = canvas.clientWidth;
  var h = canvas.clientHeight || 300;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);

  var pad = { top: 36, right: 20, bottom: 50, left: 55 };
  var pw = w - pad.left - pad.right;
  var ph = h - pad.top - pad.bottom;

  ctx.clearRect(0, 0, w, h);

  var centers = tracks[0].bands.centers;
  var nBands = centers.length;
  var nTracks = tracks.length;

  // Find y range across all tracks
  var yMin = Infinity, yMax = -Infinity;
  for (var t = 0; t < nTracks; t++) {
    var energies = tracks[t].bands.energy_db;
    for (var i = 0; i < energies.length; i++) {
      if (!isFinite(energies[i])) continue;
      if (energies[i] < yMin) yMin = energies[i];
      if (energies[i] > yMax) yMax = energies[i];
    }
  }
  if (!isFinite(yMin)) { yMin = -100; yMax = 0; }
  yMin = Math.floor(yMin / 5) * 5 - 5;
  yMax = Math.ceil(yMax / 5) * 5 + 5;
  var yRange = yMax - yMin || 1;

  // Grid lines
  ctx.strokeStyle = theme.grid;
  ctx.lineWidth = 1;
  for (var db = yMin; db <= yMax; db += 10) {
    var gy = pad.top + ph - ((db - yMin) / yRange) * ph;
    ctx.beginPath();
    ctx.moveTo(pad.left, gy);
    ctx.lineTo(pad.left + pw, gy);
    ctx.stroke();
  }

  // Y axis labels
  ctx.fillStyle = theme.textSecondary;
  ctx.font = "10px sans-serif";
  ctx.textAlign = "right";
  for (var db = yMin; db <= yMax; db += 10) {
    var gy = pad.top + ph - ((db - yMin) / yRange) * ph;
    ctx.fillText(db.toString(), pad.left - 6, gy + 3);
  }

  // Bars
  var groupW = pw / nBands;
  var barW = (groupW * 0.75) / nTracks;
  var groupPad = groupW * 0.125;

  for (var i = 0; i < nBands; i++) {
    for (var t = 0; t < nTracks; t++) {
      var val = tracks[t].bands.energy_db[i];
      var barH = Math.max(0, ((val - yMin) / yRange) * ph);
      var x = pad.left + i * groupW + groupPad + t * barW;
      var y = pad.top + ph - barH;

      ctx.fillStyle = theme.trackColors[t % theme.trackColors.length];
      ctx.globalAlpha = 0.8;
      ctx.fillRect(x, y, barW - 1, barH);
      ctx.globalAlpha = 1;
    }
  }

  // X axis labels (select subset for readability)
  var labelCenters = [25, 63, 125, 250, 500, 1000, 2000, 4000, 8000];
  ctx.fillStyle = theme.textSecondary;
  ctx.font = "10px sans-serif";
  ctx.textAlign = "center";
  for (var i = 0; i < nBands; i++) {
    var fc = centers[i];
    var show = false;
    for (var j = 0; j < labelCenters.length; j++) {
      if (Math.abs(fc - labelCenters[j]) / labelCenters[j] < 0.1) show = true;
    }
    if (!show) continue;
    var cx = pad.left + (i + 0.5) * groupW;
    var label = fc >= 1000 ? (fc / 1000) + "k" : fc.toString();
    ctx.fillText(label, cx, pad.top + ph + 16);
  }

  // Axis labels
  ctx.fillStyle = theme.text;
  ctx.font = "12px sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("1/3 Octave Band Center (Hz)", w / 2, h - 6);

  ctx.save();
  ctx.translate(14, pad.top + ph / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("Energy (dB)", 0, 0);
  ctx.restore();

  // Title
  ctx.font = "bold 13px sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("1/3 Octave Band Analysis (25 Hz - 10 kHz)", w / 2, 20);

  // Legend (if multi-track)
  if (nTracks > 1) {
    ctx.font = "10px sans-serif";
    ctx.textAlign = "left";
    var lx = pad.left + 8;
    for (var t = 0; t < nTracks; t++) {
      var ly = pad.top + 14 + t * 14;
      ctx.fillStyle = theme.trackColors[t % theme.trackColors.length];
      ctx.fillRect(lx, ly - 8, 12, 8);
      ctx.fillStyle = theme.text;
      ctx.fillText(tracks[t].label, lx + 16, ly);
    }
  }
}
