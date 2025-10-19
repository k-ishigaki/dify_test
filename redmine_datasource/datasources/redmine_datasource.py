# For online document, you can use the following code:
import logging
import urllib.parse
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any, Mapping

import requests

from dify_plugin.entities.datasource import (
    DatasourceGetPagesResponse,
    DatasourceMessage,
    GetOnlineDocumentPageContentRequest,
    OnlineDocumentInfo,
    OnlineDocumentPage,
)
from dify_plugin.interfaces.datasource import DatasourceProvider
from dify_plugin.interfaces.datasource.online_document import OnlineDocumentDatasource

logger = logging.getLogger(__name__)


class RedmineDatasourceError(RuntimeError):
    """Raised when the Redmine datasource cannot fulfil a request."""


@dataclass(frozen=True)
class RedmineCredentials:
    base_url: str
    api_key: str
    workspace_id: str
    workspace_name: str
    workspace_icon: str


class RedmineDatasourceProvider(DatasourceProvider):
    """
    Validate the Redmine datasource configuration supplied by operators.
    """

    def _validate_credentials(self, credentials: Mapping[str, Any]):
        api_key = (credentials or {}).get("api_key")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("Redmine API key is required.")

        base_url = (credentials or {}).get("base_url")
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("Redmine base URL is required.")

        parsed = urllib.parse.urlparse(base_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Redmine base URL must include http(s) scheme and host, e.g. https://redmine.example.com.")


class RedmineDatasourceDataSource(OnlineDocumentDatasource):

    DEFAULT_PAGE_SIZE = 100
    REQUEST_TIMEOUT = 15

    def _get_pages(self, _: Mapping[str, Any]) -> DatasourceGetPagesResponse:
        credentials = self._resolve_credentials()
        projects = self._fetch_all_projects(credentials)
        pages: list[OnlineDocumentPage] = []

        for project in projects:
            project_identifier = project.get("identifier") or str(project.get("id"))
            if not project_identifier:
                logger.debug("Skipping project without identifier: %s", project)
                continue

            project_page_id = f"project:{project_identifier}"
            project_name_raw = project.get("name") or project_identifier
            project_name = project_name_raw.replace("\r", " ").replace("\n", " ").strip()
            if not project_name:
                project_name = project_identifier
            project_updated_at = (
                project.get("updated_on")
                or project.get("created_on")
                or ""
            )
            pages.append(
                OnlineDocumentPage(
                    page_name=project_name,
                    page_id=project_page_id,
                    type="project",
                    last_edited_time=project_updated_at,
                    parent_id=None,
                    page_icon=None,
                )
            )

            issues = self._fetch_all_project_issues(credentials, project_identifier)
            for issue in issues:
                issue_id = issue.get("id")
                subject_raw = issue.get("subject") or ""
                subject = subject_raw.replace("\r", " ").replace("\n", " ").strip()
                if not issue_id or not subject:
                    logger.debug("Skipping issue with missing id or subject: %s", issue)
                    continue

                issue_display_name = f"{issue_id}_{subject}".strip("_")
                issue_updated_at = (
                    issue.get("updated_on")
                    or issue.get("created_on")
                    or ""
                )
                pages.append(
                    OnlineDocumentPage(
                        page_name=issue_display_name,
                        page_id=f"issue:{issue_id}",
                        type="page",
                        last_edited_time=issue_updated_at,
                        parent_id=project_page_id,
                        page_icon=None,
                    )
                )

        online_document_info = OnlineDocumentInfo(
            workspace_name=credentials.workspace_name,
            workspace_icon=credentials.workspace_icon,
            workspace_id=credentials.workspace_id,
            pages=pages,
            total=len(pages),
        )
        return DatasourceGetPagesResponse(result=[online_document_info])

    def _get_content(self, page: GetOnlineDocumentPageContentRequest) -> Generator[DatasourceMessage, None, None]:
        credentials = self._resolve_credentials()
        if page.page_id.startswith("issue:"):
            issue_id = page.page_id.split(":", 1)[1]
            issue = self._fetch_issue(credentials, issue_id)
            subject_raw = issue.get("subject") or ""
            subject = subject_raw.replace("\r", " ").replace("\n", " ").strip()
            title = f"{issue.get('id')}_{subject}".strip("_")
            description = issue.get("description") or ""

            yield self.create_variable_message("workspace_id", credentials.workspace_id)
            yield self.create_variable_message("page_id", page.page_id)
            yield self.create_variable_message("content", description)
            if title:
                yield self.create_variable_message("title", title)
            return

        if page.page_id.startswith("project:"):
            project_identifier = page.page_id.split(":", 1)[1]
            project = self._fetch_project(credentials, project_identifier)
            project_description = project.get("description") or ""

            yield self.create_variable_message("workspace_id", credentials.workspace_id)
            yield self.create_variable_message("page_id", page.page_id)
            yield self.create_variable_message("content", project_description)
            if project.get("name"):
                cleaned_name = project["name"].replace("\r", " ").replace("\n", " ").strip()
                yield self.create_variable_message("title", cleaned_name)
            return

        raise RedmineDatasourceError(f"Unsupported page id: {page.page_id}")

    def _resolve_credentials(self) -> RedmineCredentials:
        api_key = (self.runtime.credentials or {}).get("api_key")
        base_url = (self.runtime.credentials or {}).get("base_url")

        if not api_key:
            raise RedmineDatasourceError("Missing Redmine API key. Configure it in the datasource credentials.")

        if not base_url:
            raise RedmineDatasourceError("Missing Redmine base URL. Configure it in the datasource credentials.")

        parsed = urllib.parse.urlparse(base_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RedmineDatasourceError("Invalid Redmine base URL. Make sure it includes the protocol, e.g. https://example.com")

        normalized_path = parsed.path.rstrip("/")
        normalized_base_url = f"{parsed.scheme}://{parsed.netloc}{normalized_path}"
        workspace_name = parsed.netloc or normalized_base_url

        return RedmineCredentials(
            base_url=normalized_base_url,
            api_key=api_key,
            workspace_id=normalized_base_url,
            workspace_name=f"Redmine ({workspace_name})",
            workspace_icon="",
        )

    def _fetch_all_projects(self, credentials: RedmineCredentials) -> list[Mapping[str, Any]]:
        logger.debug("Fetching Redmine projects")
        projects: list[Mapping[str, Any]] = []
        offset = 0

        while True:
            payload = self._request(
                credentials,
                "/projects.json",
                params={
                    "limit": self.DEFAULT_PAGE_SIZE,
                    "offset": offset,
                },
            )
            batch = payload.get("projects") or []
            projects.extend(batch)

            if not batch:
                break

            total_count = payload.get("total_count")
            if total_count is None or offset + self.DEFAULT_PAGE_SIZE >= total_count:
                break

            offset += self.DEFAULT_PAGE_SIZE

        return projects

    def _fetch_all_project_issues(self, credentials: RedmineCredentials, project_identifier: str) -> list[Mapping[str, Any]]:
        logger.debug("Fetching issues for project %s", project_identifier)
        issues: list[Mapping[str, Any]] = []
        offset = 0

        while True:
            payload = self._request(
                credentials,
                "/issues.json",
                params={
                    "project_id": project_identifier,
                    "status_id": "*",
                    "limit": self.DEFAULT_PAGE_SIZE,
                    "offset": offset,
                },
            )
            batch = payload.get("issues") or []
            issues.extend(batch)

            if not batch:
                break

            total_count = payload.get("total_count")
            if total_count is None or offset + self.DEFAULT_PAGE_SIZE >= total_count:
                break

            offset += self.DEFAULT_PAGE_SIZE

        return issues

    def _fetch_issue(self, credentials: RedmineCredentials, issue_id: str) -> Mapping[str, Any]:
        logger.debug("Fetching issue %s", issue_id)
        payload = self._request(credentials, f"/issues/{issue_id}.json")
        issue = payload.get("issue")
        if not issue:
            raise RedmineDatasourceError(f"Issue {issue_id} not found")
        return issue

    def _fetch_project(self, credentials: RedmineCredentials, project_identifier: str) -> Mapping[str, Any]:
        logger.debug("Fetching project %s", project_identifier)
        payload = self._request(credentials, f"/projects/{project_identifier}.json")
        project = payload.get("project")
        if not project:
            raise RedmineDatasourceError(f"Project {project_identifier} not found")
        return project

    def _request(
        self,
        credentials: RedmineCredentials,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        url = urllib.parse.urljoin(credentials.base_url.rstrip("/") + "/", path.lstrip("/"))
        headers = {
            "X-Redmine-API-Key": credentials.api_key,
        }

        try:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=self.REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Redmine API request failed: %s", exc, exc_info=True)
            raise RedmineDatasourceError(f"Redmine API request failed: {exc}") from exc

        try:
            return response.json()
        except ValueError as exc:
            logger.error("Failed to decode Redmine response as JSON: %s", exc, exc_info=True)
            raise RedmineDatasourceError("Failed to decode Redmine response as JSON") from exc


# For website crawl, you can use the following code:
# from typing import Any, Generator

# from dify_plugin.entities.datasource import WebSiteInfo, WebSiteInfoDetail
# from dify_plugin.entities.tool import ToolInvokeMessage
# from dify_plugin.interfaces.datasource.website import WebsiteCrawlDatasource


# class RedmineDatasourceDataSource(WebsiteCrawlDatasource):

#     def _get_website_crawl(
#         self, datasource_parameters: dict[str, Any]
#     ) -> Generator[ToolInvokeMessage, None, None]:

#         crawl_res = WebSiteInfo(web_info_list=[], status="", total=0, completed=0)
#         crawl_res.status = "processing"
#         yield self.create_crawl_message(crawl_res)

#         crawl_res.status = "completed"
#         crawl_res.web_info_list = [
#             WebSiteInfoDetail(
#                 title="",
#                 source_url="",
#                 description="",
#                 content="",
#             )
#         ]
#         crawl_res.total = 1
#         crawl_res.completed = 1

#         yield self.create_crawl_message(crawl_res)


# For online drive, you can use the following code:
# from collections.abc import Generator

# from dify_plugin.entities.datasource import (
#     DatasourceMessage,
#     OnlineDriveBrowseFilesRequest,
#     OnlineDriveBrowseFilesResponse,
#     OnlineDriveDownloadFileRequest,
#     OnlineDriveFile,
#     OnlineDriveFileBucket,
# )
# from dify_plugin.interfaces.datasource.online_drive import OnlineDriveDatasource


# class RedmineDatasourceDataSource(OnlineDriveDatasource):

#     def _browse_files(
#         self, request: OnlineDriveBrowseFilesRequest
#     ) -> OnlineDriveBrowseFilesResponse:

#         credentials = self.runtime.credentials
#         bucket_name = request.bucket
#         prefix = request.prefix or ""  # Allow empty prefix for root folder; When you browse the folder, the prefix is the folder id
#         max_keys = request.max_keys or 10
#         next_page_parameters = request.next_page_parameters or {}

#         files = []
#         files.append(OnlineDriveFile(
#             id="", 
#             name="", 
#             size=0, 
#             type="folder" # or "file"
#         ))

#         return OnlineDriveBrowseFilesResponse(result=[
#             OnlineDriveFileBucket(
#                 bucket="", 
#                 files=files, 
#                 is_truncated=False, 
#                 next_page_parameters={}
#             )
#         ])

#     # if file.type is "file", the plugin will download the file content
#     def _download_file(self, request: OnlineDriveDownloadFileRequest) -> Generator[DatasourceMessage, None, None]:
#         credentials = self.runtime.credentials
#         file_id = request.id

#         file_content = bytes()
#         file_name = ""

#         mime_type = self._get_mime_type_from_filename(file_name)
        
#         yield self.create_blob_message(file_content, meta={
#             "file_name": file_name,
#             "mime_type": mime_type
#         })

#     def _get_mime_type_from_filename(self, filename: str) -> str:
#         """Determine MIME type from file extension."""
#         import mimetypes
#         mime_type, _ = mimetypes.guess_type(filename)
#         return mime_type or "application/octet-stream"
