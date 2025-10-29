from __future__ import annotations

import io
import json
import logging
import mimetypes
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import urljoin, urlparse

import requests


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

META_DOCUMENT_NAME = "_DATASET_META.md"


@dataclass
class DocumentProfile:
    process_rule: dict[str, Any]
    doc_form: str | None
    indexing_technique: str | None


class DatasetMetaClient:
    """
    Thin wrapper over Dify's Dataset server-side API.
    """

    def __init__(self, base_url: str, api_key: str, timeout: int = 60) -> None:
        if not base_url:
            raise ValueError("BASE_URL is required")
        parsed = urlparse(base_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("BASE_URL must include scheme and host, e.g. https://your-dify.example.com")

        if not api_key:
            raise ValueError("API_KEY is required")

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            }
        )

    def validate_connection(self) -> dict[str, Any]:
        """
        Perform a lightweight authenticated call to ensure the credentials are valid.
        """
        return self._request_json("GET", "/v1/datasets", params={"page": 1, "limit": 1})

    def list_documents(self, dataset_id: str, page: int = 1, limit: int = 200) -> dict[str, Any]:
        return self._request_json(
            "GET",
            f"/v1/datasets/{dataset_id}/documents",
            params={"page": page, "limit": limit},
        )

    def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/v1/datasets/{dataset_id}")

    def get_dataset_indexing_technique(self, dataset_id: str) -> str | None:
        detail = self.get_dataset(dataset_id)
        indexing = detail.get("indexing_technique")
        if isinstance(indexing, str) and indexing:
            logger.debug("Dataset indexing technique dataset=%s value=%s", dataset_id, indexing)
            return indexing
        logger.debug("Dataset indexing technique not defined dataset=%s", dataset_id)
        return None

    def list_dataset_metadata(self, dataset_id: str) -> list[dict[str, Any]]:
        response = self._request_json("GET", f"/v1/datasets/{dataset_id}/metadata")

        def _extract(obj: Any, depth: int = 0) -> list[dict[str, Any]] | None:
            if isinstance(obj, list):
                dict_items = [item for item in obj if isinstance(item, dict)]
                if dict_items or not obj:
                    return dict_items
                return []
            if isinstance(obj, dict):
                for key in ("data", "items", "metadata", "list", "results"):
                    if key in obj:
                        extracted = _extract(obj[key], depth + 1)
                        if extracted is not None:
                            return extracted
                for value in obj.values():
                    extracted = _extract(value, depth + 1)
                    if extracted is not None:
                        return extracted
                return []
            return None

        extracted = _extract(response)
        if extracted is None:
            raise RuntimeError(
                f"Unexpected response shape when listing dataset metadata (type={type(response).__name__})"
            )
        return extracted

    def iter_documents(self, dataset_id: str, page_size: int = 200) -> Iterator[dict[str, Any]]:
        page = 1
        while True:
            listing = self.list_documents(dataset_id, page=page, limit=page_size)
            items = listing.get("data") or listing.get("items") or []
            logger.debug(
                "iter_documents dataset=%s page=%s count=%s keys=%s",
                dataset_id,
                page,
                len(items),
                [item.get("name") or item.get("filename") for item in items],
            )
            for item in items:
                yield item

            has_more = listing.get("has_more")
            if has_more is False:
                break
            if len(items) < page_size:
                break
            page_field = listing.get("page")
            if isinstance(page_field, int) and page_field == page:
                page += 1
            else:
                page = (page_field or page) + 1

    def find_meta_document(self, dataset_id: str) -> dict[str, Any]:
        for doc in self.iter_documents(dataset_id):
            name = doc.get("name") or doc.get("filename") or ""
            logger.debug("Inspecting document dataset=%s doc_id=%s name=%s", dataset_id, doc.get("id"), name)
            if name == META_DOCUMENT_NAME:
                logger.info("Found metadata document dataset=%s doc_id=%s", dataset_id, doc.get("id"))
                return doc
        logger.error("Metadata document %s not found in dataset %s", META_DOCUMENT_NAME, dataset_id)
        raise RuntimeError(f"{META_DOCUMENT_NAME} was not found in dataset {dataset_id}")

    def get_document(self, dataset_id: str, document_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/v1/datasets/{dataset_id}/documents/{document_id}")

    def delete_document(self, dataset_id: str, document_id: str) -> None:
        self._request("DELETE", f"/v1/datasets/{dataset_id}/documents/{document_id}")

    def create_document_by_text(
        self,
        dataset_id: str,
        name: str,
        text: str,
        process_rule: dict[str, Any],
        indexing_technique: str | None = None,
        doc_form: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": name,
            "text": text,
            "process_rule": process_rule,
        }
        if indexing_technique:
            payload["indexing_technique"] = indexing_technique
        if doc_form:
            payload["doc_form"] = doc_form
        return self._request_json("POST", f"/v1/datasets/{dataset_id}/document/create-by-text", json=payload)

    def create_document_by_file(
        self,
        dataset_id: str,
        filename: str,
        file_bytes: bytes,
        process_rule: dict[str, Any],
        indexing_technique: str | None = None,
        doc_form: str | None = None,
    ) -> dict[str, Any]:
        data_payload: dict[str, Any] = {"process_rule": process_rule}
        if indexing_technique:
            data_payload["indexing_technique"] = indexing_technique
        if doc_form:
            data_payload["doc_form"] = doc_form

        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        files = {
            "file": (filename, io.BytesIO(file_bytes), mime_type),
            "data": (None, json.dumps(data_payload), "application/json"),
        }
        return self._request_json(
            "POST",
            f"/v1/datasets/{dataset_id}/document/create-by-file",
            files=files,
            use_session_headers=False,
        )

    def update_documents_metadata(self, dataset_id: str, operation_data: list[dict[str, Any]]) -> Any:
        payload = {"operation_data": operation_data}
        return self._request_json("POST", f"/v1/datasets/{dataset_id}/documents/metadata", json=payload)

    def get_document_text(self, dataset_id: str, document_id: str) -> str:
        detail = self.get_document(dataset_id, document_id)
        content = detail.get("content")
        if isinstance(content, str) and content:
            return content

        segments = list(self.iter_document_segments(dataset_id, document_id))
        if segments:
            parts = [segment.get("content", "") for segment in segments if segment.get("content")]
            if parts:
                return "\n".join(parts)

        raise RuntimeError("Unable to read metadata content; ensure it is stored as a text document.")

    def get_locked_process_rule(self, dataset_id: str, document_id: str) -> dict[str, Any]:
        profile = self.get_document_profile(dataset_id, document_id)
        return profile.process_rule

    def get_document_profile(self, dataset_id: str, document_id: str) -> DocumentProfile:
        detail = self.get_document(dataset_id, document_id)
        logger.debug(
            "Loaded document detail dataset=%s doc_id=%s keys=%s",
            dataset_id,
            document_id,
            list(detail.keys()),
        )
        process_rule = detail.get("dataset_process_rule") or detail.get("process_rule") or detail.get(
            "document_process_rule"
        )
        if not isinstance(process_rule, dict) or not process_rule:
            logger.error(
                "process_rule missing dataset=%s doc_id=%s available_keys=%s",
                dataset_id,
                document_id,
                list(detail.keys()),
            )
            raise RuntimeError("process_rule not found on metadata document detail")
        doc_form = detail.get("doc_form") if isinstance(detail.get("doc_form"), str) else None
        if doc_form:
            logger.debug("Document doc_form dataset=%s doc_id=%s form=%s", dataset_id, document_id, doc_form)
        indexing = detail.get("indexing_technique") or detail.get("document_indexing_technique")
        if isinstance(indexing, str) and indexing:
            logger.debug("Document indexing technique dataset=%s doc_id=%s value=%s", dataset_id, document_id, indexing)
        else:
            indexing = None
        return DocumentProfile(process_rule=process_rule, doc_form=doc_form, indexing_technique=indexing)

    def infer_indexing_technique(self, dataset_id: str, document_id: str) -> str | None:
        profile = self.get_document_profile(dataset_id, document_id)
        if profile.indexing_technique:
            return profile.indexing_technique
        logger.debug("Indexing technique not provided dataset=%s doc_id=%s", dataset_id, document_id)
        return None

    def iter_document_segments(self, dataset_id: str, document_id: str, page_size: int = 200) -> Iterator[dict[str, Any]]:
        page = 1
        while True:
            listing = self._request_json(
                "GET",
                f"/v1/datasets/{dataset_id}/documents/{document_id}/segments",
                params={"page": page, "limit": page_size},
            )
            items = listing.get("data") or listing.get("items") or []
            for item in items:
                yield item

            has_more = listing.get("has_more")
            if has_more is False:
                break
            if len(items) < page_size:
                break
            page_field = listing.get("page")
            if isinstance(page_field, int) and page_field == page:
                page += 1
            else:
                page = (page_field or page) + 1

    def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._request(method, path, **kwargs)
        return response.json()

    def _request(self, method: str, path: str, *, use_session_headers: bool = True, **kwargs: Any) -> requests.Response:
        url = urljoin(f"{self.base_url}/", path.lstrip("/"))

        if not use_session_headers:
            headers = {"Authorization": self.session.headers["Authorization"]}
            if "headers" in kwargs:
                headers.update(kwargs.pop("headers"))
        else:
            headers = self.session.headers

        response = self.session.request(method, url, headers=headers, timeout=self.timeout, **kwargs)
        response.raise_for_status()
        return response


def extract_document_id(response_json: dict[str, Any]) -> str | None:
    """
    Unified helper that pulls the document identifier from different payload shapes.
    """
    if not isinstance(response_json, dict):
        return None
    if "document_id" in response_json and isinstance(response_json["document_id"], str):
        return response_json["document_id"]
    if "id" in response_json and isinstance(response_json["id"], str):
        return response_json["id"]
    document = response_json.get("document")
    if isinstance(document, dict):
        if "id" in document and isinstance(document["id"], str):
            return document["id"]
        if "document_id" in document and isinstance(document["document_id"], str):
            return document["document_id"]
    return None
