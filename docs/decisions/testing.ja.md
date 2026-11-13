# Testing decisions

> For the English version, see [testing.md](testing.md).

このリポジトリのテストについて、閉じた判断の記録。テストの今の動かし方は `AGENTS.md` (「Tests」) にある。この文書には、何を選んだか、理由、決め直す条件を残す。

## The test page's static server keeps the default accept queue

- **決定** (2026-11-02): `tests/test_frontend.py` の `_test_server` (プロジェクトのルートを `tests/frontend/test_ui.html` へ配信する、単一スレッドの `HTTPServer`) は、Python の既定の待ち列 (`request_queue_size`、5) のままにする。analyze-loudness は同じフィクスチャの待ち列を 64 にした (semnil/analyze-loudness#143)。その変更は、このリポジトリへは持ち込まない。
- **理由**: `test_ui.html` が読み込む外部スクリプトは 5 つで、ページがサーバーへ同時に開く接続は最大 5 本になり、既定の待ち列を超えない。analyze-loudness のテスト用ページは 7 つを読み込み、6 本に届く。6 本という数は、Chromium が 1 つのホストへ同時に開く接続は最大 6 本、という前提に立つ。
- **開け直す条件**: `test_ui.html` に 6 つ目の外部スクリプトを足すとき。ページの同時接続が 6 本に届き、既定の待ち列を 1 本超える。
- **この決定に入らないもの**: アプリ自身が動かすサーバー。py-analyze-common の `GuiServer` (`analyze_common/server.py`) は `request_queue_size = 64` を持つ。
