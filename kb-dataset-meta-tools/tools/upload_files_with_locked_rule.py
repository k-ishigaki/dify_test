from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.file.file import File

from dataset_meta_client import DatasetMetaClient, META_DOCUMENT_NAME, extract_document_id


class UploadFilesWithLockedRuleTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        dataset_id = tool_parameters["dataset_id"]
        files_param = tool_parameters.get("files") or []
        raw_metadata_param = tool_parameters.get("metadata_list")
        if raw_metadata_param is None:
            metadata_map: dict[str, Any] = {}
        elif isinstance(raw_metadata_param, str):
            trimmed = raw_metadata_param.strip()
            if not trimmed:
                metadata_map = {}
            else:
                parsed = json.loads(trimmed)
                if not isinstance(parsed, dict):
                    raise RuntimeError("metadata_list must be a JSON object mapping names to values")
                metadata_map = parsed
        elif isinstance(raw_metadata_param, dict):
            metadata_map = raw_metadata_param
        else:
            raise RuntimeError("metadata_list must be provided as a JSON object string")

        if not isinstance(files_param, list) or not all(isinstance(item, File) for item in files_param):
            raise RuntimeError("files parameter must be a list of uploaded files")
        if not files_param:
            raise RuntimeError("At least one file must be provided")
        for key in metadata_map:
            if not isinstance(key, str) or not key:
                raise RuntimeError("Metadata field names must be non-empty strings")

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

        if metadata_map:
            dataset_metadata = client.list_dataset_metadata(dataset_id)
            name_to_meta = {
                item.get("name"): item
                for item in dataset_metadata
                if isinstance(item, dict) and isinstance(item.get("name"), str) and item.get("id")
            }

            resolved_metadata: list[dict[str, Any]] = []
            missing_names: list[str] = []
            for meta_name, meta_value in metadata_map.items():
                matched = name_to_meta.get(meta_name)
                if not matched:
                    missing_names.append(str(meta_name))
                    continue
                resolved_metadata.append(
                    {
                        "id": matched["id"],
                        "name": matched["name"],
                        "value": meta_value,
                    }
                )

            if missing_names:
                raise RuntimeError(
                    f"Metadata fields not found in dataset {dataset_id}: {', '.join(sorted(missing_names))}"
                )

            operation_data: list[dict[str, Any]] = []
            for item in results:
                document_id = item.get("document_id")
                if not document_id:
                    raise RuntimeError("Document identifier missing from upload response; cannot update metadata")
                operation_data.append(
                    {
                        "document_id": document_id,
                        "metadata_list": [dict(entry) for entry in resolved_metadata],
                    }
                )

            if operation_data:
                client.update_documents_metadata(dataset_id, operation_data)
                for item in results:
                    item["metadata_list"] = [dict(entry) for entry in resolved_metadata]

        yield self.create_json_message({"results": results})

    def _build_client(self) -> DatasetMetaClient:
        credentials = self.runtime.credentials
        base_url = credentials.get("BASE_URL")
        api_key = credentials.get("API_KEY")
        return DatasetMetaClient(base_url, api_key)
