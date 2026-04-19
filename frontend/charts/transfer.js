/**
 * Transfer function chart (delta dB vs log-frequency) on Canvas.
 * Shows PSD difference between tracks and the reference.
 */

function renderTransfer(canvas, transferFunctions) {
  var theme = getThemeColors();
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

  // Find y range
  var yMin = -15, yMax = 15;
  for (var t = 0; t < transferFunctions.length; t++) {
    var dd = transferFunctions[t].delta_db;
    for (var i = 0; i < dd.length; i++) {
      if (isFinite(dd[i])) {
        if (dd[i] < yMin) yMin = dd[i];
        if (dd[i] > yMax) yMax = dd[i];
      }
    }
  }
  yMin = Math.floor(yMin / 5) * 5 - 5;
  yMax = Math.ceil(yMax / 5) * 5 + 5;
  var yRange = yMax - yMin || 1;

  var fMin = Math.log10(20), fMax = Math.log10(20000);
  var fRange = fMax - fMin;

  // Grid lines
  ctx.strokeStyle = theme.grid;
  ctx.lineWidth = 1;
  for (var db = yMin; db <= yMax; db += 5) {
    var gy = pad.top + ph - ((db - yMin) / yRange) * ph;
    ctx.beginPath();
    ctx.moveTo(pad.left, gy);
    ctx.lineTo(pad.left + pw, gy);
    ctx.stroke();
  }

  // Zero line (emphasized)
  var zeroY = pad.top + ph - ((0 - yMin) / yRange) * ph;
  ctx.strokeStyle = theme.zero;
  ctx.lineWidth = 1.5;
  ctx.setLineDash([4, 3]);
  ctx.beginPath();
  ctx.moveTo(pad.left, zeroY);
  ctx.lineTo(pad.left + pw, zeroY);
  ctx.stroke();
  ctx.setLineDash([]);

  // Vertical freq grid
  var freqTicks = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000];
  var freqLabels = ["20", "50", "100", "200", "500", "1k", "2k", "5k", "10k", "20k"];
  ctx.strokeStyle = theme.grid;
  ctx.lineWidth = 1;
  for (var i = 0; i < freqTicks.length; i++) {
    var x = pad.left + ((Math.log10(freqTicks[i]) - fMin) / fRange) * pw;
    ctx.beginPath();
    ctx.moveTo(x, pad.top);
    ctx.lineTo(x, pad.top + ph);
    ctx.stroke();
  }

  // Plot each transfer function
  for (var t = 0; t < transferFunctions.length; t++) {
    var tf = transferFunctions[t];
    var freqs = tf.freqs;
    var delta = tf.delta_db;
    var color = theme.trackColors[t % theme.trackColors.length];

    ctx.strokeStyle = color;
    ctx.lineWidth = 1.8;
    ctx.beginPath();

    var started = false;
    for (var i = 0; i < freqs.length; i++) {
      if (freqs[i] < 20 || freqs[i] > 20000) continue;
      if (!isFinite(delta[i])) continue;
      var x = pad.left + ((Math.log10(freqs[i]) - fMin) / fRange) * pw;
      var y = pad.top + ph - ((delta[i] - yMin) / yRange) * ph;
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.stroke();
  }

  // X tick labels
  ctx.fillStyle = theme.textSecondary;
  ctx.font = "10px sans-serif";
  ctx.textAlign = "center";
  for (var i = 0; i < freqTicks.length; i++) {
    var x = pad.left + ((Math.log10(freqTicks[i]) - fMin) / fRange) * pw;
    ctx.fillText(freqLabels[i], x, pad.top + ph + 16);
  }

  // Y tick labels
  ctx.textAlign = "right";
  for (var db = yMin; db <= yMax; db += 5) {
    var gy = pad.top + ph - ((db - yMin) / yRange) * ph;
    var label = (db > 0 ? "+" : "") + db;
    ctx.fillText(label, pad.left - 6, gy + 3);
  }

  // Axis labels
  ctx.fillStyle = theme.text;
  ctx.font = "12px sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("Frequency (Hz)", w / 2, h - 6);

  ctx.save();
  ctx.translate(14, pad.top + ph / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("\u0394 dB", 0, 0);
  ctx.restore();

  // Legend
  ctx.font = "10px sans-serif";
  ctx.textAlign = "left";
  var lx = pad.left + 8;
  for (var t = 0; t < transferFunctions.length; t++) {
    var ly = pad.top + 14 + t * 14;
    ctx.strokeStyle = theme.trackColors[t % theme.trackColors.length];
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(lx, ly - 4);
    ctx.lineTo(lx + 12, ly - 4);
    ctx.stroke();
    ctx.fillStyle = theme.text;
    ctx.fillText(transferFunctions[t].label, lx + 16, ly);
  }
}
