"""Tests for the OpenRouter provider metadata hook (v0.23 K22).

``OpenRouterProvider.model_limits`` probes ``GET {base_url}/models`` at most once,
matches the configured model id after normalization, and maps the advertised
``context_length``/``top_provider.max_completion_tokens``. The boundary (httpx) is
always mocked: no test touches the network, no test prints or caches.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from yaicli.llms.provider import Provider
from yaicli.llms.providers.openrouter_provider import OpenRouterProvider
from yaicli.model_limits import ModelLimits

GET_TARGET = "yaicli.llms.providers.openrouter_provider.httpx.get"


def _config(**overrides):
    config = {
        "API_KEY": "fake_openrouter_key",
        "BASE_URL": "https://openrouter.ai/api/v1",
        "MODEL": "anthropic/claude-sonnet-4",
        "TEMPERATURE": 0.7,
        "TOP_P": 1.0,
        "MAX_TOKENS": 1024,
        "TIMEOUT": 60,
        "EXTRA_HEADERS": None,
        "EXTRA_BODY": None,
        "ENABLE_FUNCTIONS": False,
        "ENABLE_MCP": False,
    }
    config.update(overrides)
    return config


def _models_response(rows):
    response = MagicMock()
    response.json.return_value = {"data": rows}
    return response


class TestOpenRouterModelLimits:
    """Metadata hook: success, normalization, fallbacks and silent failures."""

    @pytest.fixture
    def provider(self):
        with patch.object(OpenRouterProvider, "CLIENT_CLS", MagicMock()):
            return OpenRouterProvider(config=_config())

    def test_base_url_uses_config_and_default(self):
        with patch.object(OpenRouterProvider, "CLIENT_CLS", MagicMock()):
            configured = OpenRouterProvider(config=_config(BASE_URL="https://gateway.example/v1"))
            defaulted = OpenRouterProvider(config=_config(BASE_URL=None))
        assert configured.base_url == "https://gateway.example/v1"
        assert defaulted.base_url == OpenRouterProvider.DEFAULT_BASE_URL

    def test_matches_normalized_row_id_and_returns_metadata(self, provider):
        response = _models_response(
            [
                {"id": "openai/gpt-4o", "context_length": 128000},
                {
                    "id": "anthropic/claude-sonnet-4",
                    "context_length": 1000000,
                    "top_provider": {"max_completion_tokens": 64000},
                },
            ]
        )
        with patch(GET_TARGET, return_value=response) as mock_get:
            limits = provider.model_limits("anthropic/claude-sonnet-4")

        assert isinstance(limits, ModelLimits)
        assert limits.window == 1000000
        assert limits.max_output == 64000
        assert limits.source == "metadata"
        assert limits.detail == "openrouter /models"
        mock_get.assert_called_once()
        assert mock_get.call_args.args[0] == "https://openrouter.ai/api/v1/models"
        assert mock_get.call_args.kwargs["headers"] == {"Authorization": "Bearer fake_openrouter_key"}
        assert mock_get.call_args.kwargs["timeout"] == 2.0

    def test_matches_openrouter_variant_and_vendor_prefixes(self, provider):
        """``:free`` variants and vendor-prefixed configured ids match the same row."""
        response = _models_response(
            [
                {
                    "id": "anthropic/claude-sonnet-4:free",
                    "context_length": 200000,
                    "top_provider": {"max_completion_tokens": 8192},
                }
            ]
        )
        with patch(GET_TARGET, return_value=response):
            limits = provider.model_limits("claude-sonnet-4")
        assert limits is not None
        assert limits.window == 200000

    def test_falls_back_to_top_provider_context_length(self, provider):
        response = _models_response(
            [
                {
                    "id": "meta-llama/llama-4",
                    "top_provider": {"context_length": 131072, "max_completion_tokens": 4096},
                }
            ]
        )
        with patch(GET_TARGET, return_value=response):
            limits = provider.model_limits("meta-llama/llama-4")
        assert limits is not None
        assert limits.window == 131072
        assert limits.max_output == 4096

    def test_uses_default_base_url_when_config_base_url_is_empty(self):
        with patch.object(OpenRouterProvider, "CLIENT_CLS", MagicMock()):
            provider = OpenRouterProvider(config=_config(BASE_URL=None))
        response = _models_response([{"id": "gpt-4o", "context_length": 128000}])
        with patch(GET_TARGET, return_value=response) as mock_get:
            provider.model_limits("gpt-4o")
        assert mock_get.call_args.args[0] == f"{OpenRouterProvider.DEFAULT_BASE_URL}/models"

    def test_omits_authorization_when_no_api_key(self):
        with patch.object(OpenRouterProvider, "CLIENT_CLS", MagicMock()):
            provider = OpenRouterProvider(config=_config())
        provider.config["API_KEY"] = None  # e.g. a keyless proxy configuration
        response = _models_response([{"id": "gpt-4o", "context_length": 128000}])
        with patch(GET_TARGET, return_value=response) as mock_get:
            provider.model_limits("gpt-4o")
        assert "Authorization" not in mock_get.call_args.kwargs["headers"]

    def test_empty_model_returns_none_without_request(self, provider):
        with patch(GET_TARGET) as mock_get:
            assert provider.model_limits("") is None
        mock_get.assert_not_called()

    def test_unknown_model_returns_none(self, provider):
        response = _models_response([{"id": "openai/gpt-4o", "context_length": 128000}])
        with patch(GET_TARGET, return_value=response):
            assert provider.model_limits("totally-unknown-model") is None

    def test_network_or_http_failure_returns_none_silently(self, provider, capsys):
        with patch(GET_TARGET, side_effect=httpx.ConnectError("connection refused")):
            assert provider.model_limits("anthropic/claude-sonnet-4") is None
        with patch(GET_TARGET, side_effect=httpx.ReadTimeout("timed out")):
            assert provider.model_limits("anthropic/claude-sonnet-4") is None
        assert capsys.readouterr().err == ""

    def test_malformed_payload_returns_none(self, provider):
        bad_json = MagicMock()
        bad_json.json.side_effect = ValueError("not json")
        no_data = MagicMock()
        no_data.json.return_value = {"error": "boom"}
        not_a_list = MagicMock()
        not_a_list.json.return_value = {"data": {"id": "x"}}
        for response in (bad_json, no_data, not_a_list):
            with patch(GET_TARGET, return_value=response):
                assert provider.model_limits("anthropic/claude-sonnet-4") is None

    def test_row_without_limits_returns_none(self, provider):
        response = _models_response([{"id": "anthropic/claude-sonnet-4"}])
        with patch(GET_TARGET, return_value=response):
            assert provider.model_limits("anthropic/claude-sonnet-4") is None

    def test_no_provider_side_caching(self, provider):
        """Caching is the resolver's job; the hook probes once per call."""
        response = _models_response([{"id": "anthropic/claude-sonnet-4", "context_length": 200000}])
        with patch(GET_TARGET, return_value=response) as mock_get:
            first = provider.model_limits("anthropic/claude-sonnet-4")
            second = provider.model_limits("anthropic/claude-sonnet-4")
        assert first == second
        assert mock_get.call_count == 2


def test_openai_family_providers_do_not_probe_metadata_they_lack():
    """The base hook returns None so only metadata-capable providers hit the network."""
    assert Provider.model_limits(MagicMock(), "gpt-4o") is None
    assert OpenRouterProvider.model_limits is not Provider.model_limits
