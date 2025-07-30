#!/usr/bin/env python
"""
upload_sources_to_dify.py

- .kt / .swift ファイルを再帰的に収集
- Dify ナレッジベース (datasets/{dataset_id}) に 1 ファイルずつ登録
- 失敗時は HTTP ステータスとレスポンス本文を完全表示

Python 3.9+ / requests / tqdm が必要
"""
from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import chain
from pathlib import Path
from typing import Iterable

import requests
from tqdm import tqdm

# ----------------------- デフォルト設定 ----------------------- #
DEFAULT_CONFIG: dict = {
    "indexing_technique": "high_quality",
    "process_rule": {
        "rules": {
            "pre_processing_rules": [
                {"id": "remove_extra_spaces", "enabled": True},
                {"id": "remove_urls_emails", "enabled": True},
            ],
            "segmentation": {"separator": "###", "max_tokens": 500},
        },
        "mode": "custom",
    },
}
# ------------------------------------------------------------- #


def find_source_files(root: Path) -> Iterable[Path]:
    """root 配下の .kt / .swift ファイルを再帰列挙"""
    return chain(root.rglob("*.kt"), root.rglob("*.swift"), root.rglob("*.txt"))


def add_document_with_file(
    session: requests.Session,
    base_url: str,
    dataset_id: str,
    api_key: str,
    file_path: Path,
    config: dict,
) -> requests.Response:
    """サンプルコード準拠で 1 ファイルをアップロード"""
    url = f"{base_url.rstrip('/')}/v1/datasets/{dataset_id}/document/create-by-file"
    headers = {"Authorization": f"Bearer {api_key}"}

    with open(file_path, "rb") as f:
        files = {
            "data": (None, json.dumps(config, ensure_ascii=False), "text/plain"),
            "file": (f"{file_path.name}.txt", open(file_path, "rb"), "text/plain"),
        }
        return session.post(url, headers=headers, files=files, timeout=60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recursively upload .kt/.swift files to a Dify knowledge base."
    )
    parser.add_argument(
        "--dataset-id",
        default=os.getenv("DIFY_DATASET_ID"),
        required=os.getenv("DIFY_DATASET_ID") is None,
        help="Target dataset ID (env: DIFY_DATASET_ID)",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("DIFY_API_KEY"),
        required=os.getenv("DIFY_API_KEY") is None,
        help="Dify API key (env: DIFY_API_KEY)",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("DIFY_BASE_URL", "http://localhost"),
        help="Dify server base URL (env: DIFY_BASE_URL)",
    )
    parser.add_argument("--root-dir", default=".", help="Scan root directory (default: .)")
    parser.add_argument(
        "--concurrency", type=int, default=4, help="Parallel upload threads (default: 4)"
    )
    parser.add_argument(
        "--config-file",
        help="JSON file to override the default config (indexing_technique, retrieval_model, etc.)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="エラー時に要求・応答の詳細 (ヘッダ / JSON / ファイルサイズ) をすべて表示",
    )
    args = parser.parse_args()

    # コンフィグ読み込み
    config = DEFAULT_CONFIG.copy()
    if args.config_file:
        config.update(json.loads(Path(args.config_file).read_text(encoding="utf-8")))

    root_path = Path(args.root_dir).resolve()
    source_files = list(find_source_files(root_path))
    if not source_files:
        print("対象ファイルが見つかりませんでした。")
        return

    print(f"Found {len(source_files)} files under {root_path}. Start uploading ...")

    session = requests.Session()
    success = 0

    def _upload(fp: Path):
        try:
            res = add_document_with_file(
                session=session,
                base_url=args.base_url,
                dataset_id=args.dataset_id,
                api_key=args.api_key,
                file_path=fp,
                config=config,
            )
            return fp, res
        except Exception as exc:
            return fp, exc  # ネットワーク例外など

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(_upload, fp): fp for fp in source_files}
        for fut in tqdm(as_completed(futures), total=len(futures), unit="file"):
            fp, result = fut.result()
            if isinstance(result, Exception):
                print(f"\n[EXCEPTION] {fp} ----------\n{result}\n----------")
                continue

            if result.ok:
                success += 1
            else:
                # 失敗時：最小限 or 詳細 (debug) を切り替え
                if args.debug:
                    # 受信ヘッダ
                    resp_head = "\n".join(f"{k}: {v}" for k, v in result.headers.items())
                    # 送信ヘッダ
                    req_head = "\n".join(
                        f"{k}: {v}" for k, v in result.request.headers.items()
                    )
                    # data JSON 部分
                    data_json = json.dumps(config, ensure_ascii=False, indent=2)
                    # ファイル情報
                    fsize = fp.stat().st_size
                    print(
                        f"\n[ERROR] {fp} ----------\n"
                        f"REQUEST:\n"
                        f"POST {result.request.url}\n{req_head}\n"
                        f"-- data JSON --\n{data_json}\n"
                        f"-- file --\nname={fp.name} size={fsize} bytes\n\n"
                        f"RESPONSE:\n"
                        f"{result.status_code} {result.reason}\n{resp_head}\n"
                        f"{result.text}\n----------"
                    )
                else:
                    # 簡易表示
                    print(
                        f"\n[ERROR] {fp} ----------\n"
                        f"{result.status_code} {result.reason}\n"
                        f"{result.text}\n----------"
                    )

    print(f"Finished: {success}/{len(source_files)} files uploaded successfully.")


if __name__ == "__main__":
    main()
