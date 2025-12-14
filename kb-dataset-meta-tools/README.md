## kb-dataset-meta-tools

**Author:** k-ishigaki
**Version:** 0.0.1
**Type:** tool


## プラグイン設計（概要）

認証（プラグイン設定時に1度だけ）
	•	BASE_URL（例: https://your-dify.example.com）
	•	API_KEY（Server-side API Key）

共通ポリシー
	•	_DATASET_META_JSON.txt の document id を特定 → 以降それを軸に処理
	•	_DATASET_META_JSON.txt の中身は JSON 文字列として扱う（常に JSON 文字列を読み書き）
	•	process_rule は常にメタデータ文書の dataset_process_rule を参照（＝固定）
	•	書き込みは API の「更新系」が無い環境でも動くよう、削除→再作成でフォールバック

想定する主要API（Knowledge Base / Dataset API）

バージョン差でパスやペイロード名が微妙に違う場合があります。下のスケルトンは“安全側”（フォールバックあり）で組んでいます。

	•	ドキュメント一覧: GET /datasets/{dataset_id}/documents?limit=200&offset=0
	•	ドキュメント詳細: GET /datasets/{dataset_id}/documents/{document_id}
	•	テキストで作成: POST /datasets/{dataset_id}/document/create-by-text
	•	ファイルで作成: POST /datasets/{dataset_id}/document/create-by-file（multipart）
	•	ドキュメント削除: DELETE /datasets/{dataset_id}/documents/{document_id}

重要：読み書きしやすさのため、_DATASET_META_JSON.txt は “テキスト登録” を推奨
もともと「手動登録」とのことですが、UIからでも「テキスト」を選べるなら、後の読み書きが非常に楽になります（ファイル本体のダウンロードAPIはバージョン依存・制限があるため）。

ツール仕様

1) メタデータ読み出し（read_meta）

入力: dataset_id: string
処理:
	1.	_DATASET_META_JSON.txt を名前一致で検索 → meta_doc_id 取得
	2.	詳細取得 → dataset_process_rule を保持（以降のツールでも使う）
	3.	本文（JSON 文字列）の取り出し
	•	テキスト文書として作っている場合：document の content（もしくは segments から連結）に入っている JSON 文字列をそのまま読む
	•	“ファイル”として作っている場合は、取得が難しいためベストエフォート：
	•	可能ならダウンロードAPI（環境により /files/{file_id}/download が使える）
	•	使えない場合は代替策として「メタはテキスト登録に切替えてもらう」運用を返す
	4.	JSON 文字列を返す

出力: { content: string（JSON 文字列） }

2) メタデータ書き込み（write_meta）

入力: dataset_id: string, content: string（JSON 文字列）
処理:
	1.	_DATASET_META_JSON.txt の meta_doc_id を特定
	2.	GET .../documents/{meta_doc_id} で dataset_process_rule を取得（固定ルール）
	3.	更新方法
	•	“テキスト更新API”がある場合はそれを使用
	•	無い場合のフォールバック：DELETE → POST create-by-text で再作成（name=_DATASET_META_JSON.txt、text=content、process_rule=取得した固定ルール）
	4.	完了ステータスを返す

出力: { ok: true, document_id: string }

3) ファイルアップロード（upload_files_with_locked_rule）

入力: dataset_id: string, files: [binary or url or base64]
処理:
	1.	_DATASET_META_JSON.txt の meta_doc_id を特定
2.	GET .../documents/{meta_doc_id} → dataset_process_rule を取得
	3.	各 file について POST /document/create-by-file にて multipart 送信
	•	フィールド file に実体
	•	フィールド data に JSON 文字列：{ "process_rule": <dataset_process_rule> }
	4.	作成（または更新）結果を配列で返す

出力: { results: Array<{ name: string, document_id: string }> }

plugin.yaml（例：Dify ツールプラグイン）

name: dataset-meta-tools
label:
  en_US: Dataset Meta Tools
  ja_JP: データセット・メタツール
icon: 🗂️
description:
  en_US: Read/write dataset metadata and upload files with the dataset's locked process_rule.
  ja_JP: データセットのメタデータ読み書きと、固定process_ruleでの一括アップロード

credentials:
  - name: BASE_URL
    label:
      en_US: Dify Base URL
      ja_JP: Dify ベースURL
    type: text-input
    required: true
  - name: API_KEY
    label:
      en_US: Dify Server API Key
      ja_JP: Dify サーバAPIキー
    type: secret-input
    required: true

tools:
  - name: read_meta
    label:
      ja_JP: メタデータ読み出し
    description:
      ja_JP: 指定データセット内の _DATASET_META_JSON.txt に保存された JSON 文字列を読み出します
    parameters:
      type: object
      properties:
        dataset_id:
          type: string
          description: Dify dataset id
      required: [dataset_id]

  - name: write_meta
    label:
      ja_JP: メタデータ書き込み
    description:
      ja_JP: 指定データセット内の _DATASET_META_JSON.txt に保存する JSON 文字列を上書き保存します
    parameters:
      type: object
      properties:
        dataset_id:
          type: string
        content:
          type: string
          description: 書き込む JSON 文字列（_DATASET_META_JSON.txt の内容）
      required: [dataset_id, content]

  - name: upload_files_with_locked_rule
    label:
      ja_JP: ファイルアップロード（process_rule固定）
    description:
      ja_JP: _DATASET_META_JSON.txt の process_rule を流用してファイルを登録（更新）
    parameters:
      type: object
      properties:
        dataset_id:
          type: string
        files:
          type: array
          items:
            type: string
            format: binary
          description: アップロードするファイル群（multipart対応）
      required: [dataset_id, files]


実装スケルトン（Python）

# plugins/dataset_meta_tools/__init__.py
import io
import json
import mimetypes
import requests

META_NAME = "_DATASET_META_JSON.txt"

class DifyClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

    # ---- documents ----

    def list_documents(self, dataset_id: str, limit=200, offset=0):
        url = f"{self.base_url}/v1/datasets/{dataset_id}/documents?limit={limit}&offset={offset}"
        r = self.session.get(url, timeout=30)
        r.raise_for_status()
        return r.json()

    def get_document(self, dataset_id: str, document_id: str):
        url = f"{self.base_url}/v1/datasets/{dataset_id}/documents/{document_id}"
        r = self.session.get(url, timeout=30)
        r.raise_for_status()
        return r.json()

    def delete_document(self, dataset_id: str, document_id: str):
        url = f"{self.base_url}/v1/datasets/{dataset_id}/documents/{document_id}"
        r = self.session.delete(url, timeout=30)
        r.raise_for_status()
        return True

    def create_document_by_text(self, dataset_id: str, name: str, text: str, process_rule: dict):
        url = f"{self.base_url}/v1/datasets/{dataset_id}/document/create-by-text"
        payload = {
            "name": name,
            "text": text,
            "process_rule": process_rule
        }
        r = self.session.post(url, data=json.dumps(payload), timeout=60)
        r.raise_for_status()
        return r.json()

    def create_document_by_file(self, dataset_id: str, filename: str, file_bytes: bytes, process_rule: dict):
        url = f"{self.base_url}/v1/datasets/{dataset_id}/document/create-by-file"
        # multipart: file + data(JSON string)
        files = {
            "file": (filename, io.BytesIO(file_bytes), mimetypes.guess_type(filename)[0] or "application/octet-stream"),
            "data": (None, json.dumps({"process_rule": process_rule}), "application/json"),
        }
        # NOTE: for multipart we need to override Content-Type
        headers = {"Authorization": self.session.headers["Authorization"]}
        r = requests.post(url, files=files, headers=headers, timeout=120)
        r.raise_for_status()
        return r.json()

    # ---- helpers ----

    def find_meta_document(self, dataset_id: str):
        # Linear scan with pagination (defensive)
        offset = 0
        while True:
            doclist = self.list_documents(dataset_id, limit=200, offset=offset)
            items = doclist.get("data") or doclist.get("items") or []
            for d in items:
                # name / filename の片方しか無い版も考慮
                name = d.get("name") or d.get("filename") or ""
                if name == META_NAME:
                    return d
            if len(items) < 200:
                break
            offset += 200
        raise RuntimeError(f"{META_NAME} not found in dataset {dataset_id}")

    def get_locked_process_rule(self, dataset_id: str, document_id: str):
        detail = self.get_document(dataset_id, document_id)
        pr = detail.get("dataset_process_rule") or detail.get("process_rule") or {}
        if not pr:
            raise RuntimeError("process_rule not found on metadata document detail")
        return pr

    def get_text_content_best_effort(self, dataset_id: str, document_id: str):
        """
        可能なら本文テキストを取得。APIが無い場合は例外。
        （テキスト文書として登録している前提だと最も安定）
        """
        detail = self.get_document(dataset_id, document_id)
        # 1) 直接 content がある型
        if "content" in detail and isinstance(detail["content"], str):
            return detail["content"]

        # 2) segments が取れるなら連結（環境差あり）
        segs = detail.get("segments") or []
        if isinstance(segs, list) and segs:
            return "\n".join(s.get("content", "") for s in segs)

        # 3) ダウンロードURL系が提供されている場合（環境依存）
        #    detail.get("files", [{id, download_url}, ...]) などがあれば取得する処理を追加

        raise RuntimeError("Unable to read text content; register metadata as a TEXT document for best compatibility.")

# ---- Tool handlers ----

def tool_read_meta(params, credentials):
    client = DifyClient(credentials["BASE_URL"], credentials["API_KEY"])
    ds = params["dataset_id"]
    meta = client.find_meta_document(ds)
    content = client.get_text_content_best_effort(ds, meta["id"])
    return {"content": content}

def tool_write_meta(params, credentials):
    client = DifyClient(credentials["BASE_URL"], credentials["API_KEY"])
    ds = params["dataset_id"]
    new_text = params["content"]
    meta = client.find_meta_document(ds)

    # 既存の固定 process_rule を取得
    pr = client.get_locked_process_rule(ds, meta["id"])

    # 更新系が無いケースに備え、削除→再作成（同名）
    client.delete_document(ds, meta["id"])
    created = client.create_document_by_text(ds, META_NAME, new_text, pr)
    return {"ok": True, "document_id": created.get("document_id") or created.get("id")}

def tool_upload_files_with_locked_rule(params, credentials):
    client = DifyClient(credentials["BASE_URL"], credentials["API_KEY"])
    ds = params["dataset_id"]
    meta = client.find_meta_document(ds)
    pr = client.get_locked_process_rule(ds, meta["id"])

    results = []
    for file_item in params["files"]:
        # file_item は環境から渡されるバイナリ。必要に応じて name / bytes を抽出
        filename = file_item["filename"]
        file_bytes = file_item["bytes"]
        res = client.create_document_by_file(ds, filename, file_bytes, pr)
        results.append({"name": filename, "document_id": res.get("document_id") or res.get("id")})
    return {"results": results}

補足:
	•	requests.post(..., files=...) を使うため、Content-Type は自動で multipart/form-data になります。data パートには JSON文字列（{"process_rule": ...}）を入れています。
	•	list_documents の戻りはバージョンで data / items が揺れるため両方見ています。
	•	「本文取得」は テキスト文書で登録しておくのが最も安定です。ファイル原本のダウンロードは提供版差があるため、必要ならあなたの環境のレスポンス形を見て 3) の分岐を肉付けしてください。
