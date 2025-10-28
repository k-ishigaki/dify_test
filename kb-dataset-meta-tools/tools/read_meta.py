from __future__ import annotations

import logging
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from requests import HTTPError, RequestException

from dataset_meta_client import DatasetMetaClient, META_DOCUMENT_NAME


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class ReadMetaTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        dataset_id = tool_parameters["dataset_id"]

        try:
            logger.info("read_meta invoked dataset=%s", dataset_id)
            client = self._build_client()
            meta_doc = client.find_meta_document(dataset_id)
            content = client.get_document_text(dataset_id, meta_doc["id"])
        except HTTPError as exc:
            logger.exception("HTTP error while reading metadata dataset=%s", dataset_id)
            yield self.create_json_message(
                {
                    "error": f"HTTP error while reading {META_DOCUMENT_NAME}: {exc.response.text or exc.response.reason}",
                    "status_code": exc.response.status_code,
                }
            )
            return
        except RequestException as exc:
            logger.exception("Network error while reading metadata dataset=%s", dataset_id)
            yield self.create_json_message({"error": f"Network error while calling Dify API: {exc!s}"})
            return
        except Exception as exc:
            logger.exception("Unexpected error while reading metadata dataset=%s", dataset_id)
            yield self.create_json_message({"error": str(exc)})
            return

        document_id = meta_doc.get("id") or meta_doc.get("document_id")
        logger.info("Metadata read success dataset=%s doc_id=%s", dataset_id, document_id)
        yield self.create_text_message(content)
        yield self.create_json_message({"content": content, "document_id": document_id})

    def _build_client(self) -> DatasetMetaClient:
        credentials = self.runtime.credentials
        base_url = credentials.get("BASE_URL")
        api_key = credentials.get("API_KEY")
        return DatasetMetaClient(base_url, api_key)
