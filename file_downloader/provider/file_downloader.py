from typing import Any
from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError
from tools.file_downloader import DownloadFileTool

class FileDownloaderProvider(ToolProvider):
    """今回は外部APIキー不要なのでバリデーションのみ軽く実装"""

    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        try:
            # サンプルURLで疎通確認（失敗時は例外）
            for _ in DownloadFileTool().invoke({"url": "https://example.com/favicon.ico"}):
                break
        except Exception as e:
            raise ToolProviderCredentialValidationError(str(e))

    # provider が保持するツールリスト
    def tools(self):
        return [DownloadFileTool]