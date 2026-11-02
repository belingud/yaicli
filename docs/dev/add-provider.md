# Add a New Provider

This tutorial walks through adding an LLM provider. Read
`.trellis/spec/py/provider-guidelines.md` first; it is the authoritative coding guide for the
provider layer.

## 1. Pick the narrowest base class

Provider classes live in `yaicli/llms/providers/`. Most providers only need a base URL, a
client class, and a parameter mapping:

| Base | Use when | Examples |
| --- | --- | --- |
| `OpenAIProvider` (`openai_provider.py`) | OpenAI-compatible Chat Completions API | XAI, Together, SiliconFlow, Chutes, ModelScope, Moonshot, OpenRouter, Targon, Yi |
| `OpenAIProvider` + custom `CLIENT_CLS` | OpenAI wire format, different SDK client | Doubao (`Ark`), Cerebras, Fireworks |
| `OpenAICompatibleProvider` | Generic `/chat/completions` endpoints with proxy quirks | `openai-compatible` |
| `AnthropicProvider` (`anthropic_provider.py`) | Anthropic Messages API family | Anthropic Bedrock/Vertex, LongCat (Anthropic format) |
| `GeminiProvider` (`gemini_provider.py`) | Google GenAI SDK (native Gemini protocol) | Gemini, VertexAI |
| `Provider` directly | Native SDK with its own protocol | Ollama, Cohere, Mistral |

The two abstract methods are `completion()` (a generator of `LLMResponse`) and
`detect_tool_role()`. `_convert_messages()` has a default OpenAI-format implementation; override
it only when the wire format differs.

## 2. Create the provider module

Create `yaicli/llms/providers/<name>_provider.py`:

```python
from .openai_provider import OpenAIProvider


class MyProvider(OpenAIProvider):
    """My LLM provider, OpenAI-compatible."""

    DEFAULT_BASE_URL = "https://api.example.com/v1"
    COMPLETION_PARAMS_KEYS = {
        "model": "MODEL",
        "temperature": "TEMPERATURE",
        "top_p": "TOP_P",
        "max_tokens": "MAX_TOKENS",
        "timeout": "TIMEOUT",
        "extra_body": "EXTRA_BODY",
    }
```

Provider-specific config keys (`AK`/`SK`, `HF_PROVIDER`, `AWS_REGION`, ...) are read with
`config.get()`; they are not in `DEFAULT_CONFIG_MAP`, so they have no `YAI_*` environment alias
unless you add them there. Use `DEFAULT_BASE_URL` for the endpoint, keep the API key in
`config["API_KEY"]`, and never instantiate the SDK client at import time.

## 3. Register the provider key

Add the provider to `ProviderFactory.providers_map` in **`yaicli/llms/provider.py`** (the
`yaicli/llms/providers/__init__.py` file is empty):

```python
providers_map = {
    ...
    "my-provider": (".providers.my_provider", "MyProvider"),
}
```

The key is the exact `PROVIDER=` value users set; only lowercasing is applied. Registry key and
class name are independent (`"openai-azure"` → `OpenAIAzure`). The factory imports modules lazily,
so a missing optional SDK only fails when that provider is selected.

## 4. Optional dependency (if the SDK is not core)

If the provider SDK is optional, add an extra for it in `pyproject.toml`
(`[project.optional-dependencies]`) and include it in the `all` extra. Import the SDK at the top
of your provider module (it is only imported when selected) — never add it to the shared
`yaicli` import path.

## 5. Images and special capabilities

If the API cannot accept images, add the provider key to `NO_VISION_PROVIDERS` in
`yaicli/const.py`; `CLI._build_messages()` then warns and strips images for that provider.

## 6. Tests

- Add `tests/llms/test_<name>_provider.py`. Mock the SDK client (never call a real API) and
  follow the fixture/mocking style of `tests/llms/test_deepseek_provider.py`; patch schema
  helpers on the provider module, not on `yaicli.tools`.
- Add the new key to `expected_providers` in
  `tests/llms/test_provider.py::TestProviderFactory::test_known_provider_types`; it asserts the
  exact registry key set and fails until updated.

## 7. Documentation

- Add `docs/providers/<name>.md`.
- Add a row/link to `docs/providers/overview.md`.
- Add the page to `nav:` in `mkdocs.yml` and the provider list in `README.md`.

## 8. Verify

```bash
uv run pytest tests/llms -q
ruff check yaicli tests
# black-box check that the key is registered and can be instantiated:
PYTHONPATH=. python -m yaicli.entry --list-providers
# with an isolated config/HOME, exercise the provider name:
HOME=/tmp/yaicli-dev uv run python -m yaicli.entry --version
```

`ai --list-providers` reads the registry, so a key missing there is a registration bug, not a
documentation bug.
