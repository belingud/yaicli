from typing import Optional

import httpx

from ...model_limits import (
    METADATA_TIMEOUT_SECONDS,
    ModelLimits,
    limits_from_dict,
    normalize_model_name,
)
from .openai_provider import OpenAIProvider


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
    COMPLETION_PARAMS_KEYS = {
        "model": "MODEL",
        "temperature": "TEMPERATURE",
        "top_p": "TOP_P",
        "max_tokens": "MAX_TOKENS",
        "timeout": "TIMEOUT",
        "extra_body": "EXTRA_BODY",
        "frequency_penalty": "FREQUENCY_PENALTY",
    }

    def model_limits(self, model: str) -> Optional[ModelLimits]:
        """Fetch OpenRouter's advertised context limits for ``model``.

        One bounded ``GET {base_url}/models`` probe (2s timeout, ``Bearer`` auth
        only when ``API_KEY`` is set). The configured model id is normalized and
        matched against every advertised row id (so ``anthropic/claude-...`` and
        a ``:free`` variant resolve to the same row). Any failure — network,
        timeout, HTTP, malformed JSON — silently returns ``None``; the hook never
        prints and never caches.
        """
        if not model:
            return None
        try:
            api_key = self.config.get("API_KEY")
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            response = httpx.get(
                f"{self.base_url}/models",
                headers=headers,
                timeout=METADATA_TIMEOUT_SECONDS,
            )
            payload = response.json()
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                return None
            normalized = normalize_model_name(model)
            for row in rows:
                if not isinstance(row, dict):
                    continue
                row_id = row.get("id")
                if normalize_model_name(row_id) != normalized and str(row_id or "") != str(model):
                    continue
                top_provider = row.get("top_provider")
                if not isinstance(top_provider, dict):
                    top_provider = {}
                window = row.get("context_length") or top_provider.get("context_length")
                max_output = top_provider.get("max_completion_tokens")
                return limits_from_dict(
                    {
                        "window": window,
                        "max_output": max_output,
                        "source": "metadata",
                        "detail": "openrouter /models",
                    }
                )
            return None
        except Exception:
            # A metadata probe must never break a request: fall through to the
            # static resolution layers.
            return None
