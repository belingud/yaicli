import os
from typing import Any, Dict, Optional

from ...config import cfg
from ...console import get_console
from ...exceptions import ProviderError
from ..openai_wire import OpenAIWireProvider

#: Provider classes whose default transport is the httpx lite transport (v0.24 P1-c).
#: Matched by exact class name on purpose: every other OpenAI-family provider
#: (deepseek, groq, openrouter, ...), every custom-``CLIENT_CLS`` subclass
#: (cerebras, fireworks, doubao), Azure and user subclasses keep the openai SDK.
LITE_TRANSPORT_PROVIDER_CLASSES = frozenset({"OpenAIProvider", "OpenAICompatibleProvider"})


class OpenAIProvider(OpenAIWireProvider):
    """OpenAI provider implementation (openai SDK or the httpx lite transport).

    v0.24 P1-c: the SDK is imported lazily, only when this provider instance
    actually uses it. ``LITE_TRANSPORT=false`` restores the previous SDK path;
    see :mod:`yaicli.llms.lite_transport` for the parity contract.
    """

    #: ``None`` = resolve to ``openai.OpenAI`` lazily inside :meth:`create_client`
    #: (keeps ``import openai`` off the module import path). Subclasses may set
    #: their own SDK class (cerebras/fireworks/doubao do).
    CLIENT_CLS = None

    def _use_lite_transport(self) -> bool:
        """True when this instance should use the httpx lite transport."""
        if type(self).__name__ not in LITE_TRANSPORT_PROVIDER_CLASSES:
            return False
        # The config layer normalizes booleans (env/ini, default true); tests build
        # providers from plain dicts where the key may be absent → default on.
        return bool(self.config.get("LITE_TRANSPORT", True))

    def _log_transport(self, transport: str) -> None:
        if self.verbose:
            self.console.print(f"Transport: {transport}")

    def create_client(self) -> Any:
        """Build either the httpx lite client or the openai SDK client."""
        if self._use_lite_transport():
            self._log_transport("lite (httpx)")
            # Imported here (not at module import) so the SDK-free path pays for
            # httpx only, and custom-CLIENT_CLS subclasses never import it.
            from ..lite_transport import create_lite_client

            return create_lite_client(self.client_params)

        self._log_transport("openai SDK")
        import openai

        client_cls = self.CLIENT_CLS or openai.OpenAI
        return client_cls(**self.client_params)


class OpenAIAzure(OpenAIProvider):
    """Azure OpenAI provider implementation (always the openai SDK).

    Azure requires ``api-version`` query parameters, deployment URLs and
    ``azure_ad_token`` auth, so it keeps the SDK transport (the lite transport is
    only enabled for the ``openai`` / ``openai-compatible`` classes).
    """

    CLIENT_CLS = None

    def __init__(self, config: dict = cfg, verbose: bool = False, **kwargs):
        self.config = config
        self.enable_function = self.config["ENABLE_FUNCTIONS"]
        self.enable_mcp = self.config["ENABLE_MCP"]
        self.verbose = verbose
        self.console = get_console()

        # Initialize client
        self.client_params = self.get_client_params()
        self.client = self.create_client()

        # Store completion params
        self._completion_params: Optional[Dict[str, Any]] = None

    def create_client(self) -> Any:
        import openai

        client_cls = self.CLIENT_CLS or openai.AzureOpenAI
        return client_cls(**self.client_params)

    def get_client_params(self) -> Dict[str, Any]:
        """
        azure_endpoint: Your Azure endpoint, including the resource, e.g. `https://example-resource.azure.openai.com/`

        azure_ad_token: Your Azure Active Directory token, https://www.microsoft.com/en-us/security/business/identity-access/microsoft-entra-id

        azure_ad_token_provider: A callable that returns an Azure Active Directory token, will be invoked on every request.

        azure_deployment: A model deployment, if given with `azure_endpoint`, sets the base client URL to include `/deployments/{azure_deployment}`.
            Not supported with Assistants APIs.
        """
        api_key = self.config.get("API_KEY")
        azure_ad_token = self.config.get("AZURE_AD_TOKEN")
        azure_ad_token_provider = self.config.get("AZURE_AD_TOKEN_PROVIDER")
        api_version = self.config.get("API_VERSION")
        if api_key is None:
            api_key = os.environ.get("AZURE_OPENAI_API_KEY")

        if azure_ad_token is None:
            azure_ad_token = os.environ.get("AZURE_OPENAI_AD_TOKEN")

        if api_key is None and azure_ad_token is None:
            raise ProviderError(
                "Missing credentials. Please pass one of `api_key`, `azure_ad_token`, or the `AZURE_OPENAI_API_KEY` or `AZURE_OPENAI_AD_TOKEN` environment variables."
            )

        if api_version is None:
            api_version = os.environ.get("OPENAI_API_VERSION")

        if api_version is None:
            raise ProviderError(
                "Must provide either the `api_version` argument or the `OPENAI_API_VERSION` environment variable"
            )

        default_query = {"api-version": api_version}
        # Merge with custom default query if provided
        custom_default_query = self.config.get("DEFAULT_QUERY")
        if custom_default_query:
            default_query.update(custom_default_query)
        default_headers = self.config.get("DEFAULT_HEADERS") or {}
        default_headers.update({"X-Title": self.APP_NAME, "HTTP_Referer": self.APP_REFERER})
        base_url = self.config.get("BASE_URL") or None  # set to None if base url is empty
        azure_deployment = self.config.get("AZURE_DEPLOYMENT")
        azure_endpoint = self.config.get("AZURE_ENDPOINT")

        if base_url is None:
            if azure_endpoint is None:
                azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")

            if azure_endpoint is None:
                raise ValueError(
                    "Must provide one of the `base_url` or `azure_endpoint` arguments, or the `AZURE_OPENAI_ENDPOINT` environment variable"
                )

            if azure_deployment is not None:
                base_url = f"{azure_endpoint.rstrip('/')}/openai/deployments/{azure_deployment}"
            else:
                base_url = f"{azure_endpoint.rstrip('/')}/openai"
        else:
            if azure_endpoint is not None:
                raise ValueError("base_url and azure_endpoint are mutually exclusive")

        client_params = {
            "api_key": api_key,
            "azure_ad_token": azure_ad_token,
            "default_query": default_query,
            "default_headers": default_headers,
            "azure_endpoint": azure_endpoint,
            "azure_deployment": azure_deployment,
            "base_url": base_url,
        }

        # Add azure_ad_token_provider if provided
        if azure_ad_token_provider:
            client_params["azure_ad_token_provider"] = azure_ad_token_provider

        return client_params
