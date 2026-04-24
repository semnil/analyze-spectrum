// Two-language (en / ja) UI translation for analyze-spectrum.  Default follows
// navigator.language ("ja*" -> ja, otherwise en); the user's choice is
// persisted in localStorage("spectrum-lang").
//
// Static markup uses data-i18n* attributes and is translated on
// DOMContentLoaded.  Dynamic strings created in main.js call window.i18n.t(key)
// directly.
(function () {
  const STORAGE_KEY = "spectrum-lang";

  const DICT = {
    en: {
      "app.title": "Spectrum Analyzer",
      "form.aria": "Analyze audio source",
      "url.label": "YouTube URL or local audio file path",
      "url.placeholder": "YouTube URL or local file path",
      "btn.browse": "\u{1F4C1} Browse",
      "btn.browse.aria": "Browse local audio file",
      "btn.analyze": "Analyze",
      "btn.cancel": "Cancel",
      "btn.cancel.aria": "Cancel analysis in progress",
      "btn.compare": "Compare",
      "btn.add": "+ Add Track",
      "btn.add.aria": "Add another track for comparison",
      "btn.load_json": "\u{1F4C4} Load JSON",
      "btn.load_json.aria": "Load saved JSON result",
      "btn.clear": "Clear All",
      "btn.clear.aria": "Clear all queued tracks",
      "btn.save_json": "Save JSON",
      "btn.save_image": "Save Image",
      "btn.copy": "Copy",
      "btn.copied": "Copied",
      "track_list.aria": "Tracks queued for comparison",
      "result.analysis": "Analysis Result",
      "result.comparison": "Comparison Result",
      "label.ref_suffix": " (ref)",
      "meta.tracks": "tracks",
      "status.starting": "Starting...",
      "status.starting_comparison": "Starting comparison...",
      "status.opening_file": "Opening file...",
      "status.cancelled": "Cancelled.",
      "status.generating_image": "Generating image...",
      "status.saved": "Saved: ",
      "status.uploading": "Uploading: ",
      "status.file_loaded": "File loaded: ",
      "status.tracks_ready": " tracks ready for comparison",
      "status.skipped_max_suffix": " skipped: max 6 tracks)",
      "err.prefix": "Error: ",
      "err.max_tracks": "Maximum 6 tracks for comparison",
      "err.duplicate_track": "This track is already added",
      "err.save_failed": "Save failed: ",
      "err.dialog_timeout": "The file dialog did not respond. Please try again.",
      "err.no_result": "No result received from server",
      "err.stream_interrupted": "Connection interrupted",
      "err.file_too_large": "File too large (max 500 MB)",
      "err.charts_not_ready": "Charts not ready for capture",
      "err.outdated_no_source": "Outdated data: the original file was not found, so it cannot be re-analysed: ",
      "modal.outdated_prompt": "This is legacy-format data. Re-analyse with the latest format?",
      "modal.source_label": "Source: ",
      "modal.ok": "OK",
      "modal.cancel": "Cancel",
      "drop.overlay": "Drop audio file here",
      "ctx.cut": "Cut",
      "ctx.copy": "Copy",
      "ctx.paste": "Paste",
      "ctx.select_all": "Select All",
      "track.move_up_prefix": "Move track ",
      "track.move_up_suffix": " up",
      "track.move_down_prefix": "Move track ",
      "track.move_down_suffix": " down",
      "track.remove_prefix": "Remove track ",
      "track.remove_suffix": "",
      "theme.aria_toggle": "Toggle color theme",
      "theme.title.light": "Light (click: Dark)",
      "theme.title.dark": "Dark (click: Auto)",
      "theme.title.auto": "Auto (click: Light)",
      "theme.aria_state.light": "Theme: light. Click to switch to dark.",
      "theme.aria_state.dark": "Theme: dark. Click to switch to auto.",
      "theme.aria_state.auto": "Theme: auto. Click to switch to light.",
      "lang.aria_toggle": "Switch language",
      "lang.title.en": "Language: English (click: 日本語)",
      "lang.title.ja": "Language: 日本語 (click: English)",
      "lang.label.en": "EN",
      "lang.label.ja": "JA",
      "tip.duration": "Length of the analyzed audio in seconds.",
      "tip.rms": "Root Mean Square level in dBFS \u2014 average perceived loudness. 0 dBFS is digital full scale.",
      "tip.true_peak": "ITU-R BS.1770 True Peak (dBTP). Detects inter-sample peaks via 4x oversampling. Values above 0 dBTP may clip on DA conversion.",
      "tip.crest": "Crest factor (True Peak - RMS). Indicator of dynamics: larger = wider dynamic range; compressed sources produce smaller values.",
      "tip.low_intel": "Energy ratio (dB) between the low band (20-200 Hz) and the intelligibility band (1-5 kHz). Per ANSI S3.5, 1-5 kHz carries ~72% of speech intelligibility. Values near 0 dB are ideal; positive = bass-heavy, negative = lacks low end.",
      "tip.centroid": "Spectral centroid (80-8000 Hz). Energy-weighted mean frequency. Higher values = brighter timbre, lower = darker / muffled.",
      "tip.hpf": "Estimated high-pass filter cutoff. Uses the 300-600 Hz average as the pass-band reference, then searches downward for the -3 dB point. N/A if no clear HPF is detected.",
      "tip.tilt": "Spectral tilt (dB/oct). Slope of the PSD from 80 Hz to 10 kHz regressed against log2 frequency. Negative = high-end rolloff. Professional mixes typically sit around -3 to -4 dB/oct.",
      "tip.pres_mid": "Energy ratio (dB) between presence (2-5 kHz) and mid (500 Hz-2 kHz). Positive values push vocals / instruments forward; negative values send them back in the mix.",
      "tip.bright": "High-end brightness. Energy ratio (dB) between air (5-10 kHz) and upper mid (500 Hz-5 kHz). Useful for spotting de-esser or reverb high-frequency attenuation.",
      "tip.hf_rolloff": "High-frequency rolloff. Frequency where the PSD drops -10 dB below the mid-band (500 Hz-2 kHz) average. Useful for detecting LPFs or codec (MP3/AAC) HF cut. N/A if not detected.",
      "tip.sub": "Sub-bass energy (dB). Governs the felt low-end pressure. Too much = muddy; too little = thin low end.",
      "tip.low": "Bass energy (dB). Home of kick and bass fundamentals \u2014 the foundation of the track.",
      "tip.low_mid": "Low-mid energy (dB). Chest voice and guitar body. Excess energy here is the usual cause of a 'muddy' mix.",
      "tip.mid": "Mid energy (dB). Vocal fundamentals and instrument presence live here.",
      "tip.presence": "Presence energy (dB). Consonant intelligibility and instrument attack. This band is what pushes sounds forward in the mix.",
      "tip.air": "Air energy (dB). Sense of openness and cymbal shimmer.",
      "tip.chart_psd": "Power Spectral Density via Welch's method. nperseg=4096 at 48 kHz gives ~11.7 Hz frequency resolution. Log-frequency X-axis, power (dB) Y-axis. Use for overall spectral shape.",
      "tip.chart_octave": "Energy per 1/3 octave band (25 Hz-10 kHz, 27 bands). Perceptually-motivated log frequency binning makes balance comparisons intuitive.",
      "tip.chart_transfer": "Per-frequency PSD difference (\u0394dB) of each track against the reference (first added). Visualises EQ processing. 0 dB = no change.",
      "tip.chart_lowend": "20-500 Hz zoomed on a linear frequency axis. Inspect HPF cutoff shape and bass-band detail. The dashed line marks the estimated HPF -3 dB point.",
      "tip.chart_midhigh": "500 Hz-20 kHz zoomed on a logarithmic frequency axis. Inspect presence / air shaping and codec-induced HF cut. The dashed line marks the HF rolloff estimate.",
    },
    ja: {
      "app.title": "Spectrum Analyzer",
      "form.aria": "音声ソースを分析",
      "url.label": "YouTube URL またはローカル音声ファイルのパス",
      "url.placeholder": "YouTube URL またはローカルファイルのパス",
      "btn.browse": "\u{1F4C1} 参照",
      "btn.browse.aria": "ローカル音声ファイルを参照",
      "btn.analyze": "分析",
      "btn.cancel": "キャンセル",
      "btn.cancel.aria": "分析をキャンセル",
      "btn.compare": "比較",
      "btn.add": "+ トラック追加",
      "btn.add.aria": "比較用のトラックを追加",
      "btn.load_json": "\u{1F4C4} JSON を開く",
      "btn.load_json.aria": "保存済み JSON 結果を読み込む",
      "btn.clear": "すべてクリア",
      "btn.clear.aria": "キュー内のトラックをすべてクリア",
      "btn.save_json": "JSON を保存",
      "btn.save_image": "画像を保存",
      "btn.copy": "コピー",
      "btn.copied": "コピー完了",
      "track_list.aria": "比較対象のトラック一覧",
      "result.analysis": "分析結果",
      "result.comparison": "比較結果",
      "label.ref_suffix": " (基準)",
      "meta.tracks": "トラック",
      "status.starting": "開始しています...",
      "status.starting_comparison": "比較を開始しています...",
      "status.opening_file": "ファイルを開いています...",
      "status.cancelled": "キャンセルされました。",
      "status.generating_image": "画像を生成しています...",
      "status.saved": "保存しました: ",
      "status.uploading": "アップロード中: ",
      "status.file_loaded": "ファイルを読み込みました: ",
      "status.tracks_ready": " 件のトラックを比較できます",
      "status.skipped_max_suffix": " 件スキップ: 最大 6 トラック)",
      "err.prefix": "エラー: ",
      "err.max_tracks": "比較できるのは最大 6 トラックまでです",
      "err.duplicate_track": "このトラックは既に追加されています",
      "err.save_failed": "保存に失敗しました: ",
      "err.dialog_timeout": "ファイルダイアログが応答しませんでした。もう一度お試しください。",
      "err.no_result": "サーバーから結果を受信できませんでした",
      "err.stream_interrupted": "接続が中断されました",
      "err.file_too_large": "ファイルが大きすぎます (最大 500 MB)",
      "err.charts_not_ready": "チャートの準備ができていません",
      "err.outdated_no_source": "旧バージョンのデータです。元のファイルが見つからないため再解析できません: ",
      "modal.outdated_prompt": "旧形式のデータです。最新形式で再解析しますか?",
      "modal.source_label": "Source: ",
      "modal.ok": "OK",
      "modal.cancel": "キャンセル",
      "drop.overlay": "音声ファイルをここにドロップ",
      "ctx.cut": "切り取り",
      "ctx.copy": "コピー",
      "ctx.paste": "貼り付け",
      "ctx.select_all": "すべて選択",
      "track.move_up_prefix": "トラック ",
      "track.move_up_suffix": " を上へ移動",
      "track.move_down_prefix": "トラック ",
      "track.move_down_suffix": " を下へ移動",
      "track.remove_prefix": "トラック ",
      "track.remove_suffix": " を削除",
      // Direct canonical-English -> ja mappings used by _chartTitle / _addRow
      "Duration": "Duration",
      "RMS": "RMS",
      "True Peak": "True Peak",
      "Crest": "Crest",
      "Low/Intel Ratio": "Low/Intel Ratio",
      "Low/Intel": "Low/Intel",
      "Spectral Centroid": "Spectral Centroid",
      "Centroid": "Centroid",
      "Tilt": "Tilt",
      "Pres/Mid": "Pres/Mid",
      "Bright": "Bright",
      "HPF -3dB": "HPF -3dB",
      "HF Rolloff": "HF Rolloff",
      "Sub (20-80)": "Sub (20-80)",
      "Low (80-200)": "Low (80-200)",
      "Low-Mid (200-500)": "Low-Mid (200-500)",
      "Mid (500-2k)": "Mid (500-2k)",
      "Presence (2-5k)": "Presence (2-5k)",
      "Air (5-10k)": "Air (5-10k)",
      "Track": "Track",
      "PSD Spectrum": "PSD Spectrum",
      "1/3 Octave Band Analysis": "1/3 Octave Band Analysis",
      "Transfer Function": "Transfer Function",
      "Low-End Detail": "Low-End Detail",
      "Mid-High Detail": "Mid-High Detail",
      "theme.aria_toggle": "配色テーマを切り替え",
      "theme.title.light": "ライト (クリックでダーク)",
      "theme.title.dark": "ダーク (クリックで自動)",
      "theme.title.auto": "自動 (クリックでライト)",
      "theme.aria_state.light": "テーマ: ライト。クリックでダーク切替。",
      "theme.aria_state.dark": "テーマ: ダーク。クリックで自動切替。",
      "theme.aria_state.auto": "テーマ: 自動。クリックでライト切替。",
      "lang.aria_toggle": "言語を切り替え",
      "lang.title.en": "言語: 英語 (クリックで日本語)",
      "lang.title.ja": "言語: 日本語 (クリックで English)",
      "lang.label.en": "EN",
      "lang.label.ja": "JA",
      "tip.duration": "\u5206\u6790\u5bfe\u8c61\u97f3\u58f0\u306e\u9577\u3055 (\u79d2)\u3002",
      "tip.rms": "\u5b9f\u52b9\u5024 (Root Mean Square) \u3092 dBFS \u3067\u8868\u793a\u3002\u97f3\u58f0\u5168\u4f53\u306e\u5e73\u5747\u7684\u306a\u97f3\u91cf\u30ec\u30d9\u30eb\u30020 dBFS \u304c\u30c7\u30b8\u30bf\u30eb\u30d5\u30eb\u30b9\u30b1\u30fc\u30eb\u3002",
      "tip.true_peak": "ITU-R BS.1770 \u6e96\u62e0\u306e True Peak (dBTP)\u30024 \u500d\u30aa\u30fc\u30d0\u30fc\u30b5\u30f3\u30d7\u30ea\u30f3\u30b0\u306b\u3088\u308a\u30b5\u30f3\u30d7\u30eb\u9593\u30d4\u30fc\u30af\u3092\u691c\u51fa\u3059\u308b\u30020 dBTP \u3092\u8d85\u3048\u308b\u3068 DA \u5909\u63db\u6642\u306b\u30af\u30ea\u30c3\u30d4\u30f3\u30b0\u304c\u767a\u751f\u3057\u3046\u308b\u3002",
      "tip.crest": "\u30af\u30ec\u30b9\u30c8\u30d5\u30a1\u30af\u30bf\u30fc (True Peak \u2212 RMS)\u3002\u30c0\u30a4\u30ca\u30df\u30af\u30b9\u306e\u6307\u6a19\u3002\u5024\u304c\u5927\u304d\u3044\u307b\u3069\u30c0\u30a4\u30ca\u30df\u30c3\u30af\u30ec\u30f3\u30b8\u304c\u5e83\u3044\u3002\u30b3\u30f3\u30d7\u30ec\u30c3\u30b5\u30fc\u3067\u6f70\u3055\u308c\u305f\u30bd\u30fc\u30b9\u306f\u5024\u304c\u5c0f\u3055\u304f\u306a\u308b\u3002",
      "tip.low_intel": "\u4f4e\u57df (20\u2013200Hz) \u3068\u660e\u77ad\u5ea6\u5e2f\u57df (1\u20135kHz) \u306e\u30a8\u30cd\u30eb\u30ae\u30fc\u6bd4 (dB)\u3002ANSI S3.5 \u306b\u57fa\u3065\u304d\u30011\u20135kHz \u306f\u97f3\u58f0\u660e\u77ad\u5ea6\u306e\u7d04 72% \u3092\u62c5\u3046\u30020 dB \u4ed8\u8fd1\u304c\u7406\u60f3\u3002\u6b63\u306e\u5024\u306f\u4f4e\u57df\u904e\u591a\u3001\u8ca0\u306f\u4f4e\u57df\u4e0d\u8db3\u3092\u793a\u3059\u3002",
      "tip.centroid": "\u30b9\u30da\u30af\u30c8\u30eb\u91cd\u5fc3 (80\u20138000Hz)\u3002\u30a8\u30cd\u30eb\u30ae\u30fc\u3067\u91cd\u307f\u4ed8\u3051\u3057\u305f\u5e73\u5747\u5468\u6ce2\u6570\u3002\u5024\u304c\u9ad8\u3044\u307b\u3069\u660e\u308b\u3044\u97f3\u8272\u3001\u4f4e\u3044\u307b\u3069\u6697\u3044\u30fb\u3053\u3082\u3063\u305f\u97f3\u8272\u3092\u793a\u3059\u3002",
      "tip.hpf": "\u30cf\u30a4\u30d1\u30b9\u30d5\u30a3\u30eb\u30bf\u30fc\u306e\u63a8\u5b9a\u30ab\u30c3\u30c8\u30aa\u30d5\u5468\u6ce2\u6570\u3002300\u2013600Hz \u306e\u5e73\u5747\u30ec\u30d9\u30eb\u3092\u30d1\u30b9\u30d0\u30f3\u30c9\u57fa\u6e96\u3068\u3057\u3001\u305d\u3053\u304b\u3089 \u22123dB \u4e0b\u304c\u308b\u4f4e\u57df\u5074\u306e\u5468\u6ce2\u6570\u3092\u63a2\u7d22\u3059\u308b\u3002N/A \u306f\u660e\u78ba\u306a HPF \u304c\u691c\u51fa\u3055\u308c\u306a\u3044\u5834\u5408\u3002",
      "tip.tilt": "\u30b9\u30da\u30af\u30c8\u30eb\u50be\u659c (dB/oct)\u300280Hz\u201310kHz \u306e PSD \u3092 log2 \u5468\u6ce2\u6570\u3067\u7dda\u5f62\u56de\u5e30\u3057\u305f\u50be\u304d\u3002\u8ca0\u306e\u5024\u306f\u9ad8\u57df\u6e1b\u8870\u3092\u793a\u3059\u3002\u30d7\u30ed\u306e\u30df\u30c3\u30af\u30b9\u306f\u6982\u306d \u22123\u301c\u22124 dB/oct\u3002",
      "tip.pres_mid": "\u30d7\u30ec\u30bc\u30f3\u30b9 (2\u20135kHz) \u3068\u30df\u30c3\u30c9 (500\u20132kHz) \u306e\u30a8\u30cd\u30eb\u30ae\u30fc\u6bd4 (dB)\u3002\u6b63\u306e\u5024\u306f\u30dc\u30fc\u30ab\u30eb\u3084\u697d\u5668\u304c\u300c\u524d\u306b\u51fa\u308b\u300d\u97f3\u50cf\u3001\u8ca0\u306e\u5024\u306f\u5f15\u3063\u8fbc\u3093\u3060\u97f3\u50cf\u3092\u793a\u3059\u3002",
      "tip.bright": "\u9ad8\u57df\u306e\u76f8\u5bfe\u7684\u306a\u8f1d\u304d\u3002\u30a8\u30a2\u30fc (5\u201310kHz) \u3068\u4e2d\u9ad8\u57df (500\u20135kHz) \u306e\u30a8\u30cd\u30eb\u30ae\u30fc\u6bd4 (dB)\u3002De-esser \u3084\u30ea\u30d0\u30fc\u30d6\u306e\u9ad8\u57df\u6e1b\u8870\u306e\u78ba\u8a8d\u306b\u6709\u7528\u3002",
      "tip.hf_rolloff": "\u9ad8\u57df\u30ed\u30fc\u30eb\u30aa\u30d5\u5468\u6ce2\u6570\u3002\u30df\u30c3\u30c9\u5e2f\u57df (500\u20132kHz) \u306e\u5e73\u5747\u30ec\u30d9\u30eb\u304b\u3089 \u221210dB \u4e0b\u304c\u308b\u9ad8\u57df\u5074\u306e\u5468\u6ce2\u6570\u3002LPF \u3084\u30b3\u30fc\u30c7\u30c3\u30af (MP3/AAC) \u306b\u3088\u308b\u9ad8\u57df\u30ab\u30c3\u30c8\u306e\u691c\u51fa\u306b\u4f7f\u3046\u3002N/A \u306f\u691c\u51fa\u3055\u308c\u306a\u3044\u5834\u5408\u3002",
      "tip.sub": "\u30b5\u30d6\u30d9\u30fc\u30b9\u5e2f\u57df\u306e\u30a8\u30cd\u30eb\u30ae\u30fc (dB)\u3002\u4f53\u611f\u7684\u306a\u4f4e\u97f3\u306e\u5727\u529b\u3092\u62c5\u3046\u5e2f\u57df\u3002\u904e\u591a\u3060\u3068\u3053\u3082\u308a\u3001\u4e0d\u8db3\u3060\u3068\u8584\u3044\u4f4e\u97f3\u306b\u306a\u308b\u3002",
      "tip.low": "\u30d9\u30fc\u30b9\u5e2f\u57df\u306e\u30a8\u30cd\u30eb\u30ae\u30fc (dB)\u3002\u30ad\u30c3\u30af\u3084\u30d9\u30fc\u30b9\u306e\u57fa\u97f3\u304c\u96c6\u4e2d\u3059\u308b\u3001\u697d\u66f2\u306e\u571f\u53f0\u3068\u306a\u308b\u5e2f\u57df\u3002",
      "tip.low_mid": "\u30ed\u30fc\u30df\u30c3\u30c9\u5e2f\u57df\u306e\u30a8\u30cd\u30eb\u30ae\u30fc (dB)\u3002\u30dc\u30fc\u30ab\u30eb\u306e\u80f8\u58f0\u3084\u30ae\u30bf\u30fc\u306e\u30dc\u30c7\u30a3\u611f\u3002\u904e\u591a\u306b\u306a\u308b\u3068\u97f3\u306e\u300c\u3053\u3082\u308a\u300d\u306e\u539f\u56e0\u306b\u306a\u308b\u3002",
      "tip.mid": "\u30df\u30c3\u30c9\u5e2f\u57df\u306e\u30a8\u30cd\u30eb\u30ae\u30fc (dB)\u3002\u30dc\u30fc\u30ab\u30eb\u306e\u57fa\u672c\u5468\u6ce2\u6570\u3084\u697d\u5668\u306e\u5b58\u5728\u611f\u3092\u62c5\u3046\u4e2d\u6838\u5e2f\u57df\u3002",
      "tip.presence": "\u30d7\u30ec\u30bc\u30f3\u30b9\u5e2f\u57df\u306e\u30a8\u30cd\u30eb\u30ae\u30fc (dB)\u3002\u5b50\u97f3\u306e\u660e\u77ad\u5ea6\u3084\u697d\u5668\u306e\u30a2\u30bf\u30c3\u30af\u611f\u3002\u3053\u306e\u5e2f\u57df\u304c\u97f3\u3092\u300c\u524d\u306b\u51fa\u3059\u300d\u5f79\u5272\u3092\u679c\u305f\u3059\u3002",
      "tip.air": "\u30a8\u30a2\u30fc\u5e2f\u57df\u306e\u30a8\u30cd\u30eb\u30ae\u30fc (dB)\u3002\u9ad8\u57df\u306e\u7a7a\u6c17\u611f\u3084\u30b7\u30f3\u30d0\u30eb\u306e\u8f1d\u304d\u3092\u62c5\u3046\u5e2f\u57df\u3002",
      "tip.chart_psd": "Welch \u6cd5\u306b\u3088\u308b PSD (Power Spectral Density) \u63a8\u5b9a\u3002nperseg=4096 / 48kHz \u3067\u5468\u6ce2\u6570\u5206\u89e3\u80fd 11.7Hz\u3002\u6a2a\u8ef8\u306f\u5bfe\u6570\u5468\u6ce2\u6570\u3001\u7e26\u8ef8\u306f\u30d1\u30ef\u30fc (dB)\u3002\u5168\u4f53\u7684\u306a\u30b9\u30da\u30af\u30c8\u30eb\u5f62\u72b6\u306e\u78ba\u8a8d\u306b\u4f7f\u3046\u3002",
      "tip.chart_octave": "1/3 \u30aa\u30af\u30bf\u30fc\u30d6\u30d0\u30f3\u30c9\u3054\u3068\u306e\u30a8\u30cd\u30eb\u30ae\u30fc (25Hz\u201310kHz, 27 bands)\u3002\u4eba\u9593\u306e\u8074\u899a\u7279\u6027\u306b\u8fd1\u3044\u5bfe\u6570\u7684\u306a\u5468\u6ce2\u6570\u5206\u5272\u3067\u3001\u5e2f\u57df\u3054\u3068\u306e\u30d0\u30e9\u30f3\u30b9\u3092\u76f4\u611f\u7684\u306b\u6bd4\u8f03\u3067\u304d\u308b\u3002",
      "tip.chart_transfer": "\u30ea\u30d5\u30a1\u30ec\u30f3\u30b9\u30c8\u30e9\u30c3\u30af (\u6700\u521d\u306b\u8ffd\u52a0\u3057\u305f\u30c8\u30e9\u30c3\u30af) \u306b\u5bfe\u3059\u308b\u5404\u30c8\u30e9\u30c3\u30af\u306e PSD \u5dee\u5206 (\u0394dB)\u3002EQ \u51e6\u7406\u306e\u52b9\u679c\u3092\u5468\u6ce2\u6570\u3054\u3068\u306b\u53ef\u8996\u5316\u3059\u308b\u30020dB \u30e9\u30a4\u30f3\u304c\u5909\u5316\u306a\u3057\u3002",
      "tip.chart_lowend": "20\u2013500Hz \u3092\u7dda\u5f62\u5468\u6ce2\u6570\u8ef8\u3067\u62e1\u5927\u8868\u793a\u3002HPF \u306e\u30ab\u30c3\u30c8\u30aa\u30d5\u7279\u6027\u3084\u30d9\u30fc\u30b9\u5e2f\u57df\u306e\u8a73\u7d30\u306a\u5f62\u72b6\u3092\u78ba\u8a8d\u3059\u308b\u3002\u7834\u7dda\u306f HPF \u22123dB \u63a8\u5b9a\u4f4d\u7f6e\u3002",
      "tip.chart_midhigh": "500Hz\u201320kHz \u3092\u5bfe\u6570\u5468\u6ce2\u6570\u8ef8\u3067\u62e1\u5927\u8868\u793a\u3002\u30d7\u30ec\u30bc\u30f3\u30b9\u30fb\u30a8\u30a2\u30fc\u5e2f\u57df\u306e\u5f62\u72b6\u3084\u30b3\u30fc\u30c7\u30c3\u30af\u306b\u3088\u308b\u9ad8\u57df\u30ab\u30c3\u30c8\u306e\u78ba\u8a8d\u306b\u4f7f\u3046\u3002\u7834\u7dda\u306f HF Rolloff \u63a8\u5b9a\u4f4d\u7f6e\u3002",
    },
  };

  function systemLang() {
    const l = (navigator.language || "en").toLowerCase();
    return l.startsWith("ja") ? "ja" : "en";
  }

  let current;
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    current = saved === "ja" || saved === "en" ? saved : systemLang();
  } catch (_) {
    current = systemLang();
  }

  function t(key) {
    const d = DICT[current] || DICT.en;
    if (Object.prototype.hasOwnProperty.call(d, key)) return d[key];
    if (Object.prototype.hasOwnProperty.call(DICT.en, key)) return DICT.en[key];
    return key;
  }

  function applyStatic() {
    document.documentElement.setAttribute("lang", current);
    document.querySelectorAll("[data-i18n]").forEach((n) => {
      n.textContent = t(n.getAttribute("data-i18n"));
    });
    document.querySelectorAll("[data-i18n-title]").forEach((n) => {
      n.title = t(n.getAttribute("data-i18n-title"));
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((n) => {
      n.placeholder = t(n.getAttribute("data-i18n-placeholder"));
    });
    document.querySelectorAll("[data-i18n-aria-label]").forEach((n) => {
      n.setAttribute("aria-label", t(n.getAttribute("data-i18n-aria-label")));
    });
    const titleEl = document.querySelector("title");
    if (titleEl && titleEl.getAttribute("data-i18n")) {
      titleEl.textContent = t(titleEl.getAttribute("data-i18n"));
    }
  }

  const listeners = [];

  window.i18n = {
    t: t,
    lang: function () { return current; },
    setLang: function (lang) {
      if (lang !== "ja" && lang !== "en") return;
      current = lang;
      try { localStorage.setItem(STORAGE_KEY, lang); } catch (_) {}
      applyStatic();
      listeners.forEach((fn) => { try { fn(lang); } catch (_) {} });
    },
    onChange: function (fn) { listeners.push(fn); },
    applyStatic: applyStatic,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyStatic);
  } else {
    applyStatic();
  }
})();
