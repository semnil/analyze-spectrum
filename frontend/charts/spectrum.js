/**
 * PSD spectrum overlay using uPlot (log-frequency X axis).
 * Supports multiple tracks with color coding.
 */

function renderSpectrum(container, tracks) {
  if (!tracks || !tracks.length) return null;
  var theme = getThemeColors();

  // Build log-frequency x-axis from first track
  var freqs = tracks[0].spectrum.freqs;
  // Filter to 20Hz-20kHz range
  var mask = [];
  for (var i = 0; i < freqs.length; i++) {
    mask.push(freqs[i] >= 20 && freqs[i] <= 20000);
  }

  var logFreqs = [];
  for (var i = 0; i < freqs.length; i++) {
    if (mask[i]) logFreqs.push(Math.log10(freqs[i]));
  }

  var seriesData = [logFreqs];
  var seriesOpts = [{
    label: "Frequency",
    value: function(self, val) {
      if (val == null) return "--";
      var freq = Math.pow(10, val);
      return freq >= 1000 ? (freq / 1000).toFixed(2) + " kHz" : freq.toFixed(1) + " Hz";
    },
  }];

  for (var t = 0; t < tracks.length; t++) {
    var psd = tracks[t].spectrum.psd_db;
    var filtered = [];
    for (var i = 0; i < psd.length; i++) {
      if (mask[i]) filtered.push(psd[i]);
    }
    seriesData.push(filtered);

    var color = theme.trackColors[t % theme.trackColors.length];
    seriesOpts.push({
      label: tracks[t].label,
      stroke: color,
      width: tracks.length === 1 ? 1.5 : 1.2,
      fill: tracks.length === 1 ? color + "18" : undefined,
      value: function(self, val) {
        if (val == null) return "--";
        return val.toFixed(1) + " dB";
      },
    });
  }

  // Frequency tick positions for log scale
  var freqTicks = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000];
  var freqLabels = ["20", "50", "100", "200", "500", "1k", "2k", "5k", "10k", "20k"];

  var dark = isDark();
  var opts = {
    width: container.clientWidth,
    height: 380,
    title: "Power Spectral Density (Welch)",
    scales: {
      x: {
        time: false,
        range: [Math.log10(20), Math.log10(20000)],
      },
      y: {},
    },
    axes: [
      {
        label: "Frequency (Hz)",
        stroke: theme.textSecondary,
        grid: { stroke: theme.grid, width: 1 },
        ticks: { stroke: theme.grid },
        values: function(self, splits) {
          return splits.map(function(v) {
            var best = 0;
            var bestDist = Infinity;
            for (var i = 0; i < freqTicks.length; i++) {
              var d = Math.abs(Math.log10(freqTicks[i]) - v);
              if (d < bestDist) { bestDist = d; best = i; }
            }
            return bestDist < 0.02 ? freqLabels[best] : "";
          });
        },
        splits: freqTicks.map(function(f) { return Math.log10(f); }),
      },
      {
        label: "Power (dB)",
        stroke: theme.textSecondary,
        grid: { stroke: theme.grid, width: 1 },
        ticks: { stroke: theme.grid },
      },
    ],
    series: seriesOpts,
  };

  return new uPlot(opts, seriesData, container);
}
