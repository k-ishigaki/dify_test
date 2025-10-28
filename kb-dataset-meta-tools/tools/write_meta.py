from __future__ import annotations

from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from requests import HTTPError, RequestException

from dataset_meta_client import DocumentProfile, DatasetMetaClient, META_DOCUMENT_NAME, extract_document_id


class WriteMetaTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        dataset_id = tool_parameters["dataset_id"]
        content = tool_parameters["content"]

        try:
            client, meta_document_id, profile = self._prepare_meta_context(dataset_id)
            indexing = profile.indexing_technique or client.get_dataset_indexing_technique(dataset_id) or "high_quality"
            doc_form = profile.doc_form
            created = client.create_document_by_text(
                dataset_id,
                META_DOCUMENT_NAME,
                content,
                profile.process_rule,
                indexing_technique=indexing,
                doc_form=doc_form,
            )
            document_id = extract_document_id(created) or created.get("document_id") or created.get("id") or meta_document_id
        except HTTPError as exc:
            yield self.create_json_message(
                {
                    "error": f"HTTP error while writing {META_DOCUMENT_NAME}: {exc.response.text or exc.response.reason}",
                    "status_code": exc.response.status_code,
                }
            )
            return
        except RequestException as exc:
            yield self.create_json_message({"error": f"Network error while calling Dify API: {exc!s}"})
            return
        except Exception as exc:
            yield self.create_json_message({"error": str(exc)})
            return

        yield self.create_json_message({"ok": True, "document_id": document_id})

    def _prepare_meta_context(self, dataset_id: str) -> tuple[DatasetMetaClient, str, DocumentProfile]:
        client = self._build_client()
        meta_doc = client.find_meta_document(dataset_id)
        document_id = meta_doc.get("id") or meta_doc.get("document_id")
        if not document_id:
            raise RuntimeError("Metadata document id was not returned by Dify")
        profile = client.get_document_profile(dataset_id, document_id)
        return client, document_id, profile

    def _build_client(self) -> DatasetMetaClient:
        credentials = self.runtime.credentials
        base_url = credentials.get("BASE_URL")
        api_key = credentials.get("API_KEY")
        return DatasetMetaClient(base_url, api_key)
