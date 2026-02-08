from collections.abc import Generator
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, unquote
from urllib.request import Request, urlopen
import mimetypes

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage


MAX_FILE_BYTES = 50 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30


class UrlFileConverterTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        url = (tool_parameters.get("url") or tool_parameters.get("query") or "").strip()
        if not url:
            yield self.create_text_message("URLが指定されていません。")
            return

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            message = "http または https のURLのみ対応しています。"
            yield self.create_text_message(message)
            yield self.create_variable_message(
                "result",
                {"url": url, "status": "error", "error": message},
            )
            return

        try:
            request = Request(
                url,
                headers={
                    "User-Agent": "Dify-UrlFileConverter/0.0.1",
                },
            )
            with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        if int(content_length) > MAX_FILE_BYTES:
                            message = "ファイルサイズが上限を超えています。"
                            yield self.create_text_message(message)
                            yield self.create_variable_message(
                                "result",
                                {"url": url, "status": "error", "error": message},
                            )
                            return
                    except ValueError:
                        pass

                content_type_header = response.headers.get("Content-Type", "")
                content_type = content_type_header.split(";", 1)[0].strip()

                filename = self._extract_filename(response.headers.get("Content-Disposition"), parsed.path)
                data = bytearray()
                while True:
                    chunk = response.read(READ_CHUNK_BYTES)
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > MAX_FILE_BYTES:
                        message = "ファイルサイズが上限を超えています。"
                        yield self.create_text_message(message)
                        yield self.create_variable_message(
                            "result",
                            {"url": url, "status": "error", "error": message},
                        )
                        return

            if not content_type:
                content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

            meta = {
                "mime_type": content_type,
                "filename": filename,
                "name": filename,
                "size": len(data),
            }
            yield self.create_blob_message(bytes(data), meta=meta)
            yield self.create_variable_message(
                "result",
                {
                    "url": url,
                    "filename": filename,
                    "mime_type": content_type,
                    "size": len(data),
                    "status": "success",
                },
            )
        except HTTPError as exc:
            message = f"HTTPエラー: {exc.code}"
            yield self.create_text_message(message)
            yield self.create_variable_message(
                "result",
                {"url": url, "status": "error", "error": message},
            )
        except URLError as exc:
            message = f"URLエラー: {exc.reason}"
            yield self.create_text_message(message)
            yield self.create_variable_message(
                "result",
                {"url": url, "status": "error", "error": message},
            )
        except Exception as exc:
            message = f"ダウンロードに失敗しました: {exc}"
            yield self.create_text_message(message)
            yield self.create_variable_message(
                "result",
                {"url": url, "status": "error", "error": message},
            )


    @staticmethod
    def _extract_filename(content_disposition: str | None, path: str) -> str:
        if content_disposition:
            parts = [p.strip() for p in content_disposition.split(";")]
            for part in parts:
                if part.lower().startswith("filename="):
                    name = part.split("=", 1)[1].strip().strip('"')
                    if name:
                        return name
        basename = path.rsplit("/", 1)[-1]
        if basename:
            return unquote(basename)
        return "downloaded-file"
