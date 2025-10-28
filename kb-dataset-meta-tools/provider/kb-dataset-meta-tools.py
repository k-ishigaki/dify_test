from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError
from requests import HTTPError, RequestException

from dataset_meta_client import DatasetMetaClient


class KbDatasetMetaToolsProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        try:
            base_url = credentials.get("BASE_URL")
            api_key = credentials.get("API_KEY")
            client = DatasetMetaClient(base_url, api_key)
            client.validate_connection()
        except HTTPError as exc:
            response = exc.response
            detail = response.text or response.reason or "HTTP error from Dify API"
            raise ToolProviderCredentialValidationError(
                f"Dify API returned {response.status_code}: {detail}"
            ) from exc
        except RequestException as exc:
            raise ToolProviderCredentialValidationError(
                f"Network error while validating credentials: {exc!s}"
            ) from exc
        except Exception as exc:
            raise ToolProviderCredentialValidationError(str(exc)) from exc

    #########################################################################################
    # If OAuth is supported, uncomment the following functions.
    # Warning: please make sure that the sdk version is 0.4.2 or higher.
    #########################################################################################
    # def _oauth_get_authorization_url(self, redirect_uri: str, system_credentials: Mapping[str, Any]) -> str:
    #     """
    #     Generate the authorization URL for kb-dataset-meta-tools OAuth.
    #     """
    #     try:
    #         """
    #         IMPLEMENT YOUR AUTHORIZATION URL GENERATION HERE
    #         """
    #     except Exception as e:
    #         raise ToolProviderOAuthError(str(e))
    #     return ""
        
    # def _oauth_get_credentials(
    #     self, redirect_uri: str, system_credentials: Mapping[str, Any], request: Request
    # ) -> Mapping[str, Any]:
    #     """
    #     Exchange code for access_token.
    #     """
    #     try:
    #         """
    #         IMPLEMENT YOUR CREDENTIALS EXCHANGE HERE
    #         """
    #     except Exception as e:
    #         raise ToolProviderOAuthError(str(e))
    #     return dict()

    # def _oauth_refresh_credentials(
    #     self, redirect_uri: str, system_credentials: Mapping[str, Any], credentials: Mapping[str, Any]
    # ) -> OAuthCredentials:
    #     """
    #     Refresh the credentials
    #     """
    #     return OAuthCredentials(credentials=credentials, expires_at=-1)
