from __future__ import annotations

from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from dataset_meta_client import DatasetMetaClient, extract_segment_id


class WriteMetaTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        dataset_id = tool_parameters["dataset_id"]
        content = tool_parameters["content"]

        client = self._build_client()
        meta_doc = client.find_meta_document(dataset_id)
        document_id = meta_doc.get("id") or meta_doc.get("document_id")
        if not document_id:
            raise RuntimeError("Metadata document id was not returned by Dify")

        segments = list(client.iter_document_segments(dataset_id, document_id))
        if not segments:
            raise RuntimeError("No metadata segments found; ensure _DATASET_META_JSON.txt has been processed.")

        primary_segment_id = extract_segment_id(segments[0])
        if not primary_segment_id:
            raise RuntimeError("Segment id was not returned for metadata document.")

        client.update_segment(dataset_id, document_id, primary_segment_id, content=content)

        yield self.create_json_message({"ok": True, "document_id": document_id})

    def _build_client(self) -> DatasetMetaClient:
        credentials = self.runtime.credentials
        base_url = credentials.get("BASE_URL")
        api_key = credentials.get("API_KEY")
        return DatasetMetaClient(base_url, api_key)
