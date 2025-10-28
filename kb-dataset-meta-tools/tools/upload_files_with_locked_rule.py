from __future__ import annotations

from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.file.file import File
from requests import HTTPError, RequestException

from dataset_meta_client import DatasetMetaClient, META_DOCUMENT_NAME, extract_document_id


class UploadFilesWithLockedRuleTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        dataset_id = tool_parameters["dataset_id"]
        files_param = tool_parameters.get("files") or []

        if not isinstance(files_param, list) or not all(isinstance(item, File) for item in files_param):
            yield self.create_json_message({"error": "files parameter must be a list of uploaded files"})
            return
        if not files_param:
            yield self.create_json_message({"error": "At least one file must be provided"})
            return

        try:
            client = self._build_client()
            meta_doc = client.find_meta_document(dataset_id)
            meta_doc_id = meta_doc.get("id") or meta_doc.get("document_id")
            if not meta_doc_id:
                raise RuntimeError("Metadata document id was not returned by Dify")
            profile = client.get_document_profile(dataset_id, meta_doc_id)
            indexing = profile.indexing_technique or client.get_dataset_indexing_technique(dataset_id) or "high_quality"
            doc_form = profile.doc_form

            results: list[dict[str, Any]] = []
            for file_item in files_param:
                filename = file_item.filename or META_DOCUMENT_NAME
                file_bytes = file_item.blob
                created = client.create_document_by_file(
                    dataset_id,
                    filename,
                    file_bytes,
                    profile.process_rule,
                    indexing_technique=indexing,
                    doc_form=doc_form,
                )
                document_id = extract_document_id(created) or created.get("document_id") or created.get("id")
                results.append({"name": filename, "document_id": document_id})
        except HTTPError as exc:
            yield self.create_json_message(
                {
                    "error": f"HTTP error while uploading with locked process_rule: {exc.response.text or exc.response.reason}",
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

        yield self.create_json_message({"results": results})

    def _build_client(self) -> DatasetMetaClient:
        credentials = self.runtime.credentials
        base_url = credentials.get("BASE_URL")
        api_key = credentials.get("API_KEY")
        return DatasetMetaClient(base_url, api_key)
