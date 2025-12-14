from __future__ import annotations

import logging
from collections.abc import Generator
from typing import Any
import json

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from dataset_meta_client import DatasetMetaClient


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class ReadMetaTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        dataset_id = tool_parameters["dataset_id"]

        logger.info("read_meta invoked dataset=%s", dataset_id)
        client = self._build_client()
        meta_doc = client.find_meta_document(dataset_id)
        content = client.get_document_text(dataset_id, meta_doc["id"])

        document_id = meta_doc.get("id") or meta_doc.get("document_id")
        logger.info("Metadata read success dataset=%s doc_id=%s", dataset_id, document_id)
        yield self.create_text_message(content)
        yield self.create_json_message(json.loads(content))

    def _build_client(self) -> DatasetMetaClient:
        credentials = self.runtime.credentials
        base_url = credentials.get("BASE_URL")
        api_key = credentials.get("API_KEY")
        return DatasetMetaClient(base_url, api_key)
