from collections.abc import Generator
from pathlib import Path
from typing import Any
import mimetypes, re, requests

import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

import os, urllib.parse as up

class DownloadFileTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:

        url = tool_parameters["url"].strip()

        timeout = 15

        logger.debug(f"start download: {url}")
        # 1) 取得
        r = requests.get(url, timeout=timeout, stream=False, verify=False)
        r.raise_for_status()

        # 2) MIMEタイプ判定（ヘッダ優先、次に拡張子）
        mime_type = r.headers.get("content-type", "").split(";")[0]
        if not mime_type or mime_type == "application/octet-stream":
            mime_type, _ = mimetypes.guess_type(url) or ("application/octet-stream", None)

        # 3) ファイル名推定
        fname = Path(re.sub(r"[?#].*$", "", url)).name or "downloaded"
        if "." not in fname and (ext := mimetypes.guess_extension(mime_type)):
            fname += ext

        blob = r.content

        logger.debug(f"mime={mime_type}, size={len(blob)}")

        # 4) Workflow の `files` 変数へ返却
        yield self.create_blob_message(
            blob=blob,
            meta={
                "mime_type": mime_type,  # Vision対応で必須
                "filename": tool_parameters.get("filename", fname),
            },
        )