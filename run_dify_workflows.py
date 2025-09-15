#!/usr/bin/env python3
import os
import sys
import argparse
import logging
import json
import time
from pathlib import Path
import requests

UPLOAD_URL = "http://localhost/v1/files/upload"
WORKFLOW_RUN_URL = "http://localhost/v1/workflows/run"
CHUNK_SIZE = 10
DEFAULT_USER = "dify-workflow-script"
TRUNCATE_LEN = 1000  # レスポンス本文の表示上限

def setup_logger(debug=False):
    logger = logging.getLogger("dify")
    if logger.handlers:
        return logger
    ch = logging.StreamHandler()
    fmt = "%(asctime)s %(levelname)s %(message)s"
    ch.setFormatter(logging.Formatter(fmt))
    logger.addHandler(ch)
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    return logger

def mask_headers(headers):
    # headers は dict-like
    h = dict(headers) if headers else {}
    return h

def truncate(text, n=TRUNCATE_LEN):
    if text is None:
        return ""
    s = text if isinstance(text, str) else str(text)
    return s if len(s) <= n else s[:n] + "...(truncated)"

def find_mdx_files(root_dir="."):
    root = Path(root_dir)
    return sorted([p for p in root.rglob("*.mdx") if p.is_file()])

def upload_file(file_path, api_key, user=DEFAULT_USER, logger=None, pause=0.0):
    headers = {"Authorization": f"Bearer {api_key}"}
    # requests will set Content-Type for multipart automatically
    try:
        try:
            file_size = file_path.stat().st_size
        except Exception:
            file_size = None

        if logger:
            logger.info(f"Preparing upload: {file_path} (size={file_size} bytes)")
            logger.debug("Upload request summary:")
            logger.debug("  URL: %s", UPLOAD_URL)
            logger.debug("  Method: POST")
            logger.debug("  Headers: %s", mask_headers(headers))
            logger.debug("  Files: %s", [{"filename": file_path.name, "size": file_size}])
            logger.debug("  Form data: %s", {"user": user, "type": "MD"})

        try:
            with open(file_path, "rb") as f:
                files = {"file": (file_path.name, f, "text/markdown")}
                data = {"user": user, "type": "MD"}
                resp = requests.post(UPLOAD_URL, headers=headers, files=files, data=data, timeout=60)
        except Exception as e:
            if logger:
                logger.exception("Exception during file upload: %s", e)
            return None

        if logger:
            logger.info("Upload response status: %s", resp.status_code)
            logger.debug("Upload response headers: %s", mask_headers(resp.headers))
            # レスポンス本文は長くなる可能性があるためトリムして表示
            logger.debug("Upload response body: %s", truncate(resp.text))
        if resp.status_code in (200, 201):
            try:
                return resp.json().get("id")
            except Exception:
                if logger:
                    logger.warning("Upload succeeded but response JSON parse failed; body: %s", truncate(resp.text))
                return None
        else:
            if logger:
                logger.error("File upload failed: status=%s body=%s", resp.status_code, truncate(resp.text))
            return None
    finally:
        if pause:
            time.sleep(pause)

def run_workflow_with_files(upload_ids, dataset_id, api_key, workflow_url=WORKFLOW_RUN_URL, user=DEFAULT_USER, logger=None):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    file_list = [
        {"transfer_method": "local_file", "upload_file_id": uid, "type": "document"}
        for uid in upload_ids
    ]
    payload = {"inputs": {"files": file_list, "dataset_id": dataset_id, "max_chunk_length": 4000, "split_max_level": 3}, "response_mode": "blocking", "user": user}

    if logger:
        logger.info("Running workflow with %d files (dataset_id=%s)", len(upload_ids), dataset_id)
        logger.debug("Workflow request summary:")
        logger.debug("  URL: %s", workflow_url)
        logger.debug("  Method: POST")
        logger.debug("  Headers: %s", mask_headers(headers))
        # payload を整形してログ出力（大きすぎる場合はtruncate）
        try:
            pretty = json.dumps(payload, ensure_ascii=False, indent=2)
        except Exception:
            pretty = str(payload)
        logger.debug("  JSON payload: %s", truncate(pretty, TRUNCATE_LEN))

    try:
        resp = requests.post(workflow_url, headers=headers, json=payload, timeout=120)
    except Exception as e:
        if logger:
            logger.exception("Exception during workflow run: %s", e)
        return {"status": "error", "message": str(e)}

    if logger:
        logger.info("Workflow run response status: %s", resp.status_code)
        logger.debug("Workflow run response headers: %s", mask_headers(resp.headers))
        logger.debug("Workflow run response body: %s", truncate(resp.text))

    try:
        return resp.json()
    except Exception:
        return {"status": "ok", "raw": resp.text, "http_status": resp.status_code}

def chunked(iterable, size):
    for i in range(0, len(iterable), size):
        yield iterable[i:i+size]

def main():
    parser = argparse.ArgumentParser(description="Upload .mdx files and run Dify workflow in chunks (max 10 files per run).")
    parser.add_argument("--dataset-id", required=True, help="Dataset ID to pass to the workflow (string).")
    parser.add_argument("--api-key", help="Dify API key (Bearer). If omitted, read from DIFY_API_KEY env var.")
    parser.add_argument("--root", default=".", help="Root directory to search for .mdx files (default: current dir).")
    parser.add_argument("--workflow-url", default=WORKFLOW_RUN_URL, help="Workflow run endpoint (default Dify API).")
    parser.add_argument("--pause", type=float, default=0.5, help="Pause seconds between uploads to avoid rate limits.")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    logger = setup_logger(args.debug)

    api_key = args.api_key or os.environ.get("DIFY_API_KEY")
    if not api_key:
        logger.error("DIFY API key not provided. Set DIFY_API_KEY env var or use --api-key.")
        sys.exit(1)

    files = find_mdx_files(args.root)
    if not files:
        logger.info("No .mdx files found.")
        return

    logger.info("Found %d .mdx files. Running in chunks of %d...", len(files), CHUNK_SIZE)

    for idx, batch in enumerate(chunked(files, CHUNK_SIZE), start=1):
        logger.info("Processing batch %d: %d files", idx, len(batch))
        upload_ids = []
        for p in batch:
            logger.info("Uploading: %s", p)
            uid = upload_file(p, api_key, user=DEFAULT_USER, logger=logger, pause=args.pause)
            if uid:
                logger.info("Uploaded id: %s", uid)
                upload_ids.append(uid)
            else:
                logger.warning("Upload failed for %s. Check logs above.", p)

        if not upload_ids:
            logger.warning("No files uploaded for this batch; skipping workflow run.")
            continue

        resp = run_workflow_with_files(upload_ids, args.dataset_id, api_key, workflow_url=args.workflow_url, user=DEFAULT_USER, logger=logger)
        logger.info("Workflow run returned: %s", truncate(json.dumps(resp, ensure_ascii=False), TRUNCATE_LEN))

if __name__ == "__main__":
    main()
