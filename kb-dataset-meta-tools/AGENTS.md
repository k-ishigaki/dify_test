# Repository Guidelines

## プロジェクト構成と役割
- `main.py`: `dify_plugin.Plugin` エントリーポイント。ローカル実行でプラグインを起動。
- `dataset_meta_client.py`: Dify Dataset API の薄いクライアント。メタ文書検索、segment 更新、ファイル upload などの共通処理を集約。
- `tools/`: Dify Tool 実装。`read_meta.py`（メタ読み出し）、`write_meta.py`（メタ上書き）、`upload_files_with_locked_rule.py`（process_rule 固定でアップロード）。
- `provider/`: プラグイン定義と YAML。`kb-dataset-meta-tools.yaml` が UI/カタログ側設定。
- `manifest.yaml`, `requirements.txt`, `README.md`: プラグイン登録情報と依存ライブラリ、概要ドキュメント。

## セットアップ／ビルド／開発
- Python 3.10+ を想定。仮想環境推奨：`python -m venv .venv && source .venv/bin/activate`。
- 依存取得：`pip install -r requirements.txt`（`dify_plugin`, `requests` を導入）。
- 開発サーバ（ローカル実行）：`python main.py`。環境変数 `BASE_URL`, `API_KEY` をエクスポートしておく。
- CLI で動作確認する場合、`tools/*.py` を直接実行するより Dify 側でツールを呼び出す運用を前提とする。

## コーディングスタイルと命名
- 型ヒント必須。public メソッドは docstring で意図を明示。
- ログは `logger`（module-level）を使用し、dataset_id/document_id などのコンテキストを含める。
- 例外は `requests.HTTPError` と `RequestException` を捕捉し、ユーザーには JSON でエラー詳細を返すパターンを踏襲。
- 命名は `snake_case`、定数は `UPPER_SNAKE`。Dify API 名は実体と一致させる（例: `META_DOCUMENT_NAME`）。

## テスト指針
- 現在自動テストなし。API ラッパーを改修する場合は `pytest` ベースのユニットテスト追加を推奨（モックで HTTP を固定）。
- メタドキュメント検索や segment 更新など副作用のある処理はステージング環境で手動検証し、リクエスト/レスポンスの shape をログで確認。
- 新しいツール追加時は、想定する `tool_parameters` と例外パス（認証失敗、ファイル未指定など）を最低 1 ケースずつ確認。

## コミット／プルリクエスト
- 既存コミットは短い英語センテンスで要約するスタイル（例: `Add metadata_list parameter to upload_files_with_locked_rule tool`）。同様に「何を」「どこに」を端的に記述。
- PR では目的、主要変更点、確認手順（利用した Dify エンドポイントやテストコマンド）を箇条書きで記載。外部依存（API キー・ベース URL など）の前提があれば明記。
- 画面やレスポンス形式が変わる場合はサンプル payload/ログを貼付し、後方互換性への影響を記述。

## セキュリティ／設定の注意
- 資格情報（`API_KEY`）は `.env` やリポジトリ外で管理し、ログ出力しない。例外メッセージにも露出させない。
- ベース URL は末尾スラッシュなしで保持し、`urljoin` で組み立てる既存実装に倣う。
- 大きなファイルを multipart で送る処理が多いため、`timeout` を適切に設定し（デフォルト 60–120 秒）、ハング時は再試行前にログを確認。
