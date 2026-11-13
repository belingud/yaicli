# LLM Provider Guidelines

Everything under `yaicli/llms/` is the provider layer. Read this file before changing a provider,
adding one, or touching the tool-call loop:

- `yaicli/llms/provider.py` — the `Provider` ABC and `ProviderFactory` (39 registry keys today).
- `yaicli/llms/providers/` — 39 provider classes across 32 modules; most providers are thin.
- `yaicli/llms/client.py` — `LLMClient`, the provider-agnostic tool loop, confirmation gate.
- `yaicli/schemas.py` — `LLMResponse`, `ToolCall`, `ChatMessage`, `ToolPolicy`; the only types
  that cross the provider/client boundary.

## The Provider Contract

`Provider` in `yaicli/llms/provider.py` declares only two abstract methods; the rest is convention
enforced by tests and by `LLMClient`.

| Member | Obligation |
| --- | --- |
| `completion(messages, stream=False, tool_policy=None)` | abstract. Must be a generator of `LLMResponse`. `LLMClient` always calls it as `provider.completion(messages, stream=..., tool_policy=...)`, so keep the `tool_policy` keyword even when the provider ignores it. |
| `detect_tool_role()` | abstract. Role used for tool-result messages: `"tool"` everywhere except Gemini, which returns `"user"` because it has no tool role. |
| `_convert_messages(messages)` | default implementation emits OpenAI dicts (`role`, `content`, `name`, `tool_calls`, `tool_call_id`, `reasoning`, image blocks). Override only when the wire format differs. |
| `get_default_tool_policy()` / `resolve_tool_policy(tool_policy)` | concrete. Reads `self.enable_function` / `self.enable_mcp` set in `__init__`, then ANDs with the per-request policy. Never read `ENABLE_FUNCTIONS` directly in `completion()`. |
| `filter_excluded_params(params, config, verbose, console)` | static helper. Call it on the final request dict so `EXCLUDE_PARAMS` works for this provider. |
| `CLIENT_CLS` + `get_client_params()` | convention, not declared on the ABC. `__init__` builds `self.client` from `get_client_params()`: OpenAI/Anthropic-family classes use `self.CLIENT_CLS(**self.client_params)`, native-SDK providers construct their own client or add a `create_client()` hook (Cohere). |

`LLMResponse.tool_calls` is the plural view (v0.21 K14): a response may carry zero or more complete
`ToolCall` values. The legacy `LLMResponse.tool_call` field is kept in sync by `__post_init__`
(`tool_call is tool_calls[0]`; constructing with either fills the other) so older providers/callers keep
working, but new code should emit/read `tool_calls`. `LLMClient` never inspects `finish_reason`; it
collects every call from every response, dedups repeated snapshots by `tool_call.id`, filters by tool
policy and executes each call once (`tool_calls: dict[str, ToolCall]`, `yaicli/llms/client.py`).

## Provider Families

Inherit the narrowest family and override only what its protocol changes.

| Family | Base | Members | What differs |
| --- | --- | --- | --- |
| OpenAI-compatible | `openai_provider.OpenAIProvider` | `xai`, `together`, `siliconflow`, `chutes`, `modelscope`, `moonshot`, `openrouter`, `targon`, `yi` | only `DEFAULT_BASE_URL`, sometimes `COMPLETION_PARAMS_KEYS` |
| OpenAI wire, different SDK client | `OpenAIProvider` | `doubao` (`Ark`), `cerebras` (`Cerebras`), `fireworks` (`Fireworks`) | `CLIENT_CLS` + `get_client_params()`; `cerebras` also strips unsupported schema keys in `get_tools()` |
| Generic OpenAI endpoint | `openai_compatible_provider.OpenAICompatibleProvider` | `openai-compatible` | only `_handle_stream_response()`, with complete-JSON tool-call detection |
| OpenAI wire transport | `openai_wire.OpenAIWireProvider` | `openai_provider.OpenAIProvider` (SDK), `lite_transport.LiteChatClient` (httpx) | transport-agnostic logic: params/tools/messages/handlers/errors. Subclasses implement `create_client()` |
| Anthropic-compatible | `anthropic_provider.AnthropicProvider` | `anthropic-bedrock`, `anthropic-vertex`, `longcat-anthropic` | `get_client_params()`: AWS env map, GCP project/region, or a `Bearer` `Authorization` header |
| Gemini-compatible | `gemini_provider.GeminiProvider` | `vertexai` | `vertexai` only swaps `get_client_params()` (`vertexai=True`, `project`, `location`) |
| Native SDK | `Provider` directly | `ollama`, `cohere` (+ `cohere-bedrock`/`cohere-sagemaker`), `mistral` | own `completion()`, message conversion, streaming, and request params |

Minimal real example — `yaicli/llms/providers/xai_provider.py` is the whole class:

```python
class XaiProvider(OpenAIProvider):
    """Xai provider implementation based on openai-compatible API"""

    DEFAULT_BASE_URL = "https://api.xai.com/v1"
```

`DeepSeekProvider` (`yaicli/llms/providers/deepseek_provider.py`, 29 lines) is the model for a
non-cosmetic OpenAI-compatible provider: it changes `COMPLETION_PARAMS_KEYS` (DeepSeek takes
`max_tokens`, not OpenAI's `max_completion_tokens`) and overrides `_convert_messages()` to send
assistant history with `reasoning_content`. `CerebrasProvider` shows the client swap:
`CLIENT_CLS = Cerebras` plus a `get_client_params()` override.

Registry keys and class names are independent: the class may be named `OpenAIAzure` and is still
keyed `openai-azure`; `CohereBadrockProvider` (sic) is keyed `cohere-bedrock`. The key is the only
user-facing name.

## Transports: openai SDK vs lite (v0.24 P1-c)

The OpenAI Chat Completions wire logic is shared by two transports. Which one a
provider uses is decided **once at construction time**, never per request:

| Backend | Class | Selected when |
| --- | --- | --- |
| httpx lite transport | `yaicli.llms.lite_transport.LiteChatClient` | config `LITE_TRANSPORT` is true **and** the exact provider class name is in `LITE_TRANSPORT_PROVIDER_CLASSES` (`OpenAIProvider`, `OpenAICompatibleProvider`) |
| openai SDK | `openai.OpenAI` (or subclass `CLIENT_CLS`) | everything else: every other OpenAI-family provider, custom-`CLIENT_CLS` subclasses, `openai-azure`, user subclasses, and `LITE_TRANSPORT=false` |

Rules for changing this area:

- **Wire logic lives in `yaicli/llms/openai_wire.py`.** Do not fork params/tools/handlers/error
  wrapping into a backend. A backend only implements `create_client()`, whose result must expose
  `client.chat.completions.create(**params)` exactly like the SDK.
- **No SDK import at module import time.** `openai_wire.py` and `lite_transport.py` are imported on
  the one-shot path; importing `openai` there re-introduces the ~0.6s startup cost. `openai` is
  imported only inside `create_client()`. Regression test: subprocess `python -c "import
  yaicli.llms.lite_transport, sys; assert 'openai' not in sys.modules"` (both new modules).
- **Duck-typed parity contract.** The handlers read SDK attributes; `lite_transport` reproduces
  exactly those fields on `LiteCompletion`/`LiteMessage`/`LiteToolCall`/`LiteChunk`/`LiteDelta`
  (`choices`, `message.content`, `reasoning_content`, `tool_calls[].function.name/arguments`,
  `usage` as a Mapping, `model_extra` for extras/`{"error": ...}`). When a handler starts reading a
  new field, add it to the lite objects in the same change and extend
  `tests/llms/test_lite_parity.py` (SDK `model_validate` vs `MockTransport` lite, normalized
  `LLMResponse` sequences must be identical).
- **HTTP/error parity.** `LiteAPIError` carries the real `httpx.Response`, so
  `errors.wrap_provider_exception`/`retry_after_seconds` classify HTTP failures identically;
  network/timeout exceptions are pre-classified (`NETWORK`/`TIMEOUT`, retryable). Streaming
  `stream_options` rejections keep the SDK's one retry without the parameter. A `200` response
  whose first SSE chunk contains `{"error": ...}` must raise, never render as content.
- **No hidden retries in the transport.** `LLMClient`'s `RETRY_*` layer owns retry semantics; the SDK
  retries internally but the lite transport must not, or one failure would back off twice.
- **Startup budget is a gate.** `scripts/bench.py --gate` enforces `oneshot_local` (1000ms P50).
  Any change touching `openai_wire.py`, `lite_transport.py`, `openai_provider.py` or the provider
  factory must keep that gate green; the reference result is `oneshot_local` P50 ≈580ms locally
  (~622ms in CI before the lite transport existed).
- **Scope changes are config-driven, not implicit.** Adding a provider class to
  `LITE_TRANSPORT_PROVIDER_CLASSES` is a behavior change for its users: add parity coverage for it
  and a docs note, and keep the SDK path working for `LITE_TRANSPORT=false`.

## Streaming and Tool Calls

- Stream text immediately: yield one `LLMResponse(content=delta)` per chunk; see
  `_handle_stream_response()` in `yaicli/llms/providers/openai_provider.py`.
- Tool-call arguments arrive in fragments. Use the shared stdlib accumulator
  `yaicli/llms/tool_calls.py::ToolCallAccumulator` instead of hand-rolled slots: it merges by
  `delta.tool_calls[i].index`, falls back to id-based merging (with id↔index folding), keeps same-name
  calls **without ids** distinct, continues a nameless fragment on the last call, supports AI21-style
  replace semantics, and `finalize()`s an ordered list with stable generated ids. Parallel calls must
  never be merged into one `ToolCall` or silently dropped; a response may emit the complete list either
  as `LLMResponse(tool_calls=[...])` or as one `LLMResponse` per call.
- `OpenAIProvider` accumulates by index and emits each call as its own `LLMResponse` when
  `finish_reason == "tool_calls"`. `OpenAICompatibleProvider` finalizes once the accumulated arguments
  parse as JSON (some proxies never send a finish reason) and emits each call once. The legacy
  `_process_tool_call_chunk()` helper is kept for subclasses that override streaming.
- Re-yielding the same accumulated tool call is safe because `LLMClient` dedups by id; dropping or
  reusing ids is not, because two calls sharing an id collapse into one.
- Anthropic streams `text` deltas and `partial_json` deltas separately, finalizes calls on
  `content_block_stop` with `repair_json()`, and emits the complete plural list at message end (never a
  partial call); `stop_reason` comes from `message_delta`
  (`yaicli/llms/providers/anthropic_provider.py`).
- Gemini has no tool-call deltas: accumulate `function_call` parts across chunks, synthesize ids as
  `call_<uuid4>`, unwrap proxy-shaped args in `_normalize_fc_args()`, merge dict fragments via
  `merge_argument_mapping()`, and disable `automatic_function_calling`
  (`yaicli/llms/providers/gemini_provider.py`).
- Native SDK / single-slot streaming providers (ollama, chatglm/huggingface, minimax, ai21, mistral)
  emit the complete call list after the stream ends in a separate `LLMResponse`; never yield per-chunk
  partial tool calls.
- Never yield a tool call whose `arguments` are partial JSON — `execute_tool_call()` runs
  immediately.

## Reasoning Content

Any provider-specific thinking field is normalized into `LLMResponse.reasoning`.
`OpenAIProvider._get_reasoning_content()` already covers `reasoning_content`
(DeepSeek/InfiniAI/NVIDIA) and `reasoning` (OpenRouter); ChatGLM parses `<think>` blocks; MiniMax
parses `reasoning_details`; Gemini maps `part.thought`.

When history is replayed, the base `_convert_messages()` writes a `"reasoning"` key on assistant
messages. A provider whose API uses another field must override it — `DeepSeekProvider` pops
`"reasoning"` and writes `"reasoning_content"`; `MinimaxProvider` writes `reasoning_details`.
LongCat strips `<longcat_tool_call>...</longcat_tool_call>` out of reasoning before yielding.

## Params, Config, EXCLUDE_PARAMS

- `COMPLETION_PARAMS_KEYS` maps API parameter name → uppercase `DEFAULT_CONFIG_MAP` key.
  `get_completion_params()` skips `None` and `""` config values, then runs
  `Provider.filter_excluded_params()` (comma-separated, case-insensitive, default `""` in
  `yaicli/const.py`).
- Do not copy the OpenAI map blindly. Anthropic has no `frequency_penalty` parameter; it was
  removed from `AnthropicProvider.COMPLETION_PARAMS_KEYS` in commit `6d21e6a`. Anthropic-specific
  keys are `top_k`, `stop_sequences`, `metadata`.
- Providers whose request is not Chat Completions (Gemini `GenerateContentConfig`, Ollama
  `options`, Cohere/Mistral request dicts) build their own dict, but must still run
  `filter_excluded_params()` on it.
- An override of `get_completion_params()` inside the OpenAI family must keep the `tool_policy`
  keyword; four providers were broken until `a47d619` fixed their signatures.
- Provider-specific keys such as `AK`, `SK`, `AWS_REGION`, `HF_PROVIDER` are read with
  `config.get()`. The config file's `[core]` section loads arbitrary keys, but a key is only
  settable through `YAI_*` environment variables after it is registered in `DEFAULT_CONFIG_MAP`
  (`yaicli/const.py`).
- Validate credentials early: `OpenAIProvider`/`AnthropicProvider.__init__` raise
  `ValueError("API_KEY is required")`; `OpenAIAzure.get_client_params()` raises `ProviderError` or
  `ValueError`; `AnthropicBedrockProvider`/`AnthropicVertexProvider` raise `ConfigMissingError` for
  missing AWS/GCP settings. Ollama needs no key.
- Do not swallow API errors: providers must let failures raise a classified error, never return error
  text as assistant content. Wrap request-time and mid-stream failures with
  `yaicli.errors.wrap_provider_exception(exc, "<Provider name>")` (or
  `provider_response_error(provider, body)` for HTTP-200 in-band error bodies); the resulting
  `AgentError` carries `kind`, `status_code`, `retryable` and a user-facing `.user_message`. The
  client retries only retryable kinds before any content was streamed, and `entry.py`/`cli.py` map the
  failure to an actionable stderr message and a script-friendly exit code. Regression tests:
  `tests/test_errors.py` (39-provider matrix) and the `tests/llms/test_*provider*.py` error cases.

## Errors, Retries & Timeouts

- `yaicli/errors.py` is the single vocabulary: `ErrorKind` (`auth`, `rate_limit`, `context_length`,
  `network`, `timeout`, `bad_request`, `provider`, `tool`, `config`, `depth_limit`, `interrupted`,
  `unknown`), `AgentError` (subclass of `ProviderError`) with `.kind/.status_code/.retryable/.hint/
  .user_message`, `classify_exception(exc)` (duck-typed: explicit `exc.kind` → HTTP status → exception
  class name → message patterns), `is_retryable`, `retry_after_seconds`, `backoff_delay`, and the
  `EXIT_*` process codes.
- Providers should not import heavy SDK exception types just to classify them; `classify_exception`
  works on duck-typed attributes (`status_code`, `response.headers`) and class names.
- Uniform timeout: every provider must forward the configured `TIMEOUT` to its SDK/HTTP client where
  the API accepts one (OpenAI `timeout`, Anthropic `timeout`, ChatGLM/Mistral/Cohere/Ollama request
  options). Providers that ignore `TIMEOUT` are considered buggy.
- Retry policy lives in `LLMClient` (not providers): only `RATE_LIMIT`/`NETWORK`/`TIMEOUT`/`PROVIDER`
  failures, only before content has been yielded to the printer; `RETRY_ENABLED`, `RETRY_MAX`,
  `RETRY_BASE_DELAY`, `RETRY_MAX_DELAY` configure it and `Retry-After` is honored (capped).
  `context_length` is never retried blindly: the client trims one turn group and retries once.
- A mid-stream failure after content was emitted must raise a clear classified error — never silently
  stop the stream or duplicate already-rendered content.

## Adding a Provider

1. Create `yaicli/llms/providers/<name>_provider.py` extending the narrowest base; put defaults in
   class constants (`DEFAULT_BASE_URL`, `CLIENT_CLS`, `COMPLETION_PARAMS_KEYS`).
2. Register it in `ProviderFactory.providers_map` in `yaicli/llms/provider.py`: the key is the
   exact `PROVIDER=` value users set (only lowercased before lookup). `yaicli/llms/providers/__init__.py`
   is empty — the CLAUDE.md step "Add to provider imports in
   `yaicli/llms/providers/__init__.py`" is stale; the factory lazy-imports the module with
   `importlib.import_module(..., package="yaicli.llms")`.
3. Add the key to `test_known_provider_types` in `tests/llms/test_provider.py`; it asserts the exact
   `providers_map` key set and fails until updated.
4. Add `tests/llms/test_<name>_provider.py`; copy the fixture/mock shape of
   `tests/llms/test_deepseek_provider.py`.
5. If the SDK is optional, add an extra in `pyproject.toml` (`[project.optional-dependencies]` and
   `all`) so slim installs keep working — the lazy factory import is what makes that possible.
6. Add `docs/providers/<name>.md` for user-facing providers and update the tables in
   `docs/providers/overview.md`.
7. If the provider cannot take images, add its key to `NO_VISION_PROVIDERS` in `yaicli/const.py`;
   `yaicli/cli.py` warns and ignores images for those providers.
8. Verify with `ruff check yaicli tests` and `uv run pytest tests/llms -q`.

## Response Contracts

- Tool execution is driven by a non-empty `LLMResponse.tool_calls` list (the legacy singular
  `tool_call` mirrors `tool_calls[0]`), not by `finish_reason`; `finish_reason` is surfaced for
  outcomes such as `depth_limit` (client) and may be reported by providers.
- `LLMResponse` has no usage field yet (token/cost accounting is a later milestone); headless JSON
  output reports `usage` as zeros. Do not add provider-specific usage handling ad hoc.

## Testing Rules

- Never call a real API. Construct providers with `patch.object(<Provider>, "CLIENT_CLS",
  MagicMock())` or `patch("openai.OpenAI")`, then assign `provider.client = mock_client` before
  calling `completion()`. Since v0.24 the openai SDK is imported lazily inside
  `OpenAIProvider.create_client()`, so `patch("openai.OpenAI")` **does** intercept SDK construction
  (there is no `yaicli.llms.providers.openai_provider.openai` module attribute to patch any more).
  SDK-path tests must also set `"LITE_TRANSPORT": False` in the mock config, otherwise the provider
  builds a `LiteChatClient` and the SDK mock is never used.
- Patch tool-schema loaders at the provider module, not at `yaicli.tools`:
  `@patch("yaicli.llms.providers.openai_provider.get_openai_schemas", return_value=[])`,
  `patch("yaicli.llms.providers.gemini_provider.get_functions_gemini_format")`. OpenAI-family providers
  do `from ...tools import get_openai_schemas` at module import, so patching `yaicli.tools.*` after
  import does not change the provider's bound name — verified against
  `yaicli/llms/providers/openai_provider.py`. Exception: `anthropic_provider.py` imports
  `get_anthropic_schemas` lazily inside `completion()`, so patch `yaicli.tools.get_anthropic_schemas`
  (`tests/llms/test_anthropic_provider.py`).
- The config fixture must be a complete dict for the provider: providers index keys directly
  (`self.config["ENABLE_FUNCTIONS"]`), so copy the fixture from `tests/llms/test_streaming.py` and
  add provider-specific keys.
- Streaming tests feed a list of `MagicMock` chunks and assert that no partial tool call is emitted and
  that complete calls appear only on the finishing chunk / after the stream ends. Parallel-call coverage
  lives in `tests/llms/test_multi_tool_calls.py` (two anthropic blocks, gemini same-name stream, ollama
  multiple calls, single-slot providers, end-to-end `LLMClient` two-call turn); the shared accumulator
  rules are locked in `tests/llms/test_tool_calls.py`.
- `tests/llms/test_client.py` patches `ProviderFactory.create_provider` or uses a `MockProvider`;
  `tests/llms/test_tool_confirmation.py` uses a `FakeProvider` plus `generator.send(decision)` to
  drive `ConfirmToolCall` — test the client there, not inside a provider.

## Anti-Patterns

- Sending credentials a client does not accept: Cohere Bedrock/Sagemaker authenticate via AWS
  credentials, so `CohereBadrockProvider.create_client()` pops `api_key` from `client_params`
  before constructing the SDK client (commit `9b77aa1`).
- Copying OpenAI-only parameters into another API's payload (Anthropic `frequency_penalty`,
  commit `6d21e6a`).
- Emitting a `ToolCall` with partial `arguments`, or an id that changes between chunks.
- Assuming `finish_reason` is present; handle proxy/error chunks without `choices` the way
  `_handle_stream_response()` does in `openai_provider.py`.
- Returning a list from `completion()` instead of yielding, or dropping the `tool_policy` keyword
  from an override.
- Importing another provider's optional SDK from shared code. Optional SDKs are imported at the top
  of their own provider module; the factory imports only the selected module.
- Registering a provider without updating `test_known_provider_types` or without a test file.
- Catching `Exception` in `completion()` and yielding the error text as an `LLMResponse` — that was
  the v0.18 cohere/ollama bug; raise the classified error instead (`tests/test_errors.py`).

Run `uv run pytest tests/llms -q` and `ruff check yaicli tests` after any change here.
