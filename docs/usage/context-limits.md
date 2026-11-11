# Context & Limits

Long agent tasks have a failure mode that chat tools do not: a single tool result (a log file, a
directory listing, a web page) can be larger than the model's context window. YAICLI bounds this on
three levels — per-tool truncation, a per-request token budget, and turn-group-aligned history
trimming — and heals a context-length rejection instead of failing permanently.

## 1. Tool-output truncation

Every tool result is truncated before it enters the conversation:

- only the **head and tail** of the output are kept, with a marker in the middle;
- the **full output is written to disk** so nothing is lost;
- the marker tells the model where the full text is and how to page through it.

The default cap is `TOOL_OUTPUT_MAX_CHARS=32000` characters (≈8k tokens). Built-in tools have
per-tool caps on top of the global default:

| Tool | Approx. cap |
| --- | --- |
| `fs_read_file` | 64 KB |
| `fetch_webpage` (body) | 100 KB |
| `fs_search_files`, `fs_list_directory` | 48 KB |
| `execute_shell_command` | 32 KB |
| `web_search`, MCP tools, default | 32 KB |

Full outputs are stored under `TOOL_OUTPUT_DIR`, which defaults to a `tool-outputs/` directory in
the legacy chat scratch directory (`<tempdir>/yaicli/chats/tool-outputs`) — independent of the
per-project session store. The truncated text includes the path so the model can read the rest:

```json
{"file_paths": ["/path/to/tool-outputs/20261104-123456-execute_shell_command.txt"], "offset": 20000, "limit": 12000}
```

`fs_read_file` accepts two optional paging arguments (character based, applied per file):

| Argument | Meaning |
| --- | --- |
| `offset` | First character to return (`0` = beginning of the file). |
| `limit` | Maximum number of characters to return (`0` = read to the end). |

The response keeps the usual `path`/`success`/`content`/`size`/`error` fields and adds
`offset`/`limit` (the requested window), `total_chars` (full file length), `returned_chars` and
`truncated` (whether `content` is only a window of the file). Paging works on the original file as
well as on a spilled tool output; when reading a spilled output, remember it is the JSON *text* of
the tool result, not the original file. `fs_read_file` results are themselves capped at 64 KB, so
pass a `limit` comfortably below that (e.g. `limit: 12000`) to avoid the page being truncated again.

Notes:

- Set `TOOL_OUTPUT_MAX_CHARS=0` to disable truncation (not recommended for agent loops).
- The **terminal preview** is a separate, much tighter display-only limit:
  `TOOL_DISPLAY_MAX_LINES=15` lines and `TOOL_DISPLAY_MAX_CHARS=4000` characters. Tool results are
  rendered head-only with a `… +N lines · Ctrl+O to expand` marker, so a 1 MB shell result does not
  flood your screen. This never changes what the model receives — the model still gets up to
  `TOOL_OUTPUT_MAX_CHARS` characters; set both display limits to `0` to show everything.
- `Ctrl+O` (or `/show-output`) opens a **full-screen viewer** with every tool output of the current
  turn: left pane lists the entries (tool name, size and a command/path caption), right pane shows
  the selected result. `↑/↓` select, `Tab`
  switches pane, `PgUp/PgDn` scroll, `f` toggles between the model-visible text and the spilled full
  file (capped at 1 MB), and `q`/`Esc`/`Ctrl+O` closes it, restoring the REPL. Non-interactive runs
  fall back to the inline last-output panel.
- The same shortcut works **while the assistant is generating** an answer: the viewer opens without
  waiting for the turn to finish and the generation keeps running in a background worker thread
  while it is open; closing it redraws the accumulated answer and streaming continues. Typed-ahead
  text is kept and pre-filled into the next prompt.
- Long tool-call arguments on the `@Function call:` line are summarized
  (`TOOL_CALL_PREVIEW_MAX_CHARS=300`); a large `content`/`command` value appears as `<N chars>`.
- If the spill file cannot be written (read-only disk, permission error), YAICLI degrades to plain
  truncation without the path — the request still succeeds.
- Spilled files are created with mode `0600` on POSIX (file output may contain secrets); clean the
  `TOOL_OUTPUT_DIR` up periodically.

## 2. Token budget

Three numbers decide how much of the conversation is sent in one request:

| Term | Meaning |
| --- | --- |
| **Window** | The model's total context window (input + output) — e.g. `128,000` tokens for `gpt-4o`, `1,000,000` for Gemini 2.5 Pro. |
| **Budget** | How many *input* tokens one request may use: `min(window, max_input) - MAX_TOKENS - CONTEXT_SAFETY_TOKENS`. |
| **Reserve** | Output headroom kept out of the budget: `MAX_TOKENS + CONTEXT_SAFETY_TOKENS` (default `1024 + 1024 = 2048`). |

Before each provider request, YAICLI estimates the tokens in the conversation (a stdlib heuristic:
~3.5 characters per token with corrections for CJK text, plus a fixed per-message overhead) and
compares it with the budget. If the conversation is over budget, YAICLI first trims mechanically —
no extra API call, no extra cost — then sends the request. Trimming by message count alone is not
enough: a `tool_calls` message must never be separated from its `tool` results, or every provider
rejects the payload. YAICLI therefore trims by **turn group**:

- a turn group is one user message plus the assistant/tool messages that follow it;
- whole groups are dropped, oldest first;
- an assistant message with `tool_calls` is always kept together with its tool results
  (zero orphan `tool` messages);
- leading system/context messages are preserved;
- one line is printed to stderr when trimming happens, so you know why old context disappeared.

### How the window is resolved

`yaicli/model_limits.py` resolves the window in six short-circuiting layers: the first hit wins, and
every result carries a `source` saying where the number came from.

| # | `source` | Where the number comes from |
| --- | --- | --- |
| 1 | `user` | `MODEL_CONTEXT_WINDOWS` (`YAI_MODEL_CONTEXT_WINDOWS`): an explicit override, always highest priority. |
| 2 | `learned` | The real limit parsed from a provider context-length error in a previous request (cached 30 days). |
| 3 | `metadata` | Provider-advertised metadata — OpenRouter `/models`, Gemini `models.get`, Ollama `/api/show` (cached 7 days). |
| 4 | `catalog` | The bundled snapshot `yaicli/data/model_limits.json`. |
| 5 | `heuristic` | Provider-scoped family prefix, longest match wins (`gpt-4-32k` is not `gpt-4`); Ollama falls back to 8,192. |
| 6 | `default` | `128,000` tokens for a model nothing else knows, plus a one-time warning. |

`/context` shows the result on the `window` line: the value, the `source`, and a short `detail` when
the layer provides one (`source: metadata · openrouter /models`). `source: user` means your config
won; `source: default` means the model is unknown (see below).

#### Normalization and matching

Model ids are normalized before the static layers see them: lower-cased; up to two vendor prefixes
removed (`openrouter/`, `anthropic/`, `openai/`, `google/`, `mistralai/`, `meta-llama/`, `qwen/`,
`deepseek/`, `moonshotai/`, `x-ai/`, `cohere/`, `nvidia/`); a `-YYYYMMDD` / `@YYYYMMDD` suffix
removed; OpenRouter variant suffixes (`:free`, `:batch`, `:extended`, `:nitro`, `:online`) removed;
and a `[1m]` marker stripped (the raw id with `[1m]` resolves to `1,000,000` as a heuristic hit).

The catalog is matched **exactly** on the normalized id (it is a curated snapshot, not a fuzzy
table); the heuristic layer matches **provider-scoped prefixes, longest match first**. This ordering
is deliberate: an exact catalog entry for `grok-4` (256,000) does not silently apply to `grok-4.7` —
that id falls through to the `grok` family heuristic (131,072) until a catalog entry, provider
metadata or a `MODEL_CONTEXT_WINDOWS` override exists for it.

Ollama is special-cased: generic cloud families (`qwen`, `mistral`, ...) are ignored there because a
local server serves those names with its own runtime window, so an unknown local model resolves to
`OLLAMA_DEFAULT_CONTEXT_WINDOW` (8,192). The provider's `NUM_CTX` option is **not** used as a window;
only configured values, learned values, provider metadata and the catalog are authoritative.

#### Heuristic family table

Longest prefix wins, so `gpt-4-32k` beats `gpt-4` and `o1-mini` beats `o1`. The table lives in
`HEURISTIC_CONTEXT_WINDOWS` in `yaicli/model_limits.py`; anything that does not match any row falls to
the default.

| Window | Family prefixes |
| --- | --- |
| 1,048,576 | `gemini` |
| 1,047,576 | `gpt-4.1` |
| 400,000 | `gpt-5` |
| 245,760 | `minimax` |
| 200,000 | `claude`, `o1`, `o3`, `o4` |
| 131,072 | `moonshot`, `kimi`, `qwen`, `grok` |
| 128,000 | `gpt-4o`, `gpt-4-turbo`, `o1-mini`, `deepseek`, `glm`, `chatglm`, `mistral`, `command`, `cohere` |
| 32,768 | `gpt-4-32k`, `mixtral` |
| 16,385 | `gpt-3.5` |
| 8,192 | `gpt-4` (plain `gpt-4`; the longer `gpt-4*` rows win), `llama` (Ollama only) |

### Overriding the window (`MODEL_CONTEXT_WINDOWS`)

Set `MODEL_CONTEXT_WINDOWS` (a JSON object; the `YAI_MODEL_CONTEXT_WINDOWS` env var works too) to pin
a window yourself. Keys may name a bare model (applies to any provider), a `provider:model` pair, or
a `provider/model` pair; values may be an integer or an object with `window` / `max_input` /
`max_output`:

```ini
[core]
# JSON: keys may be "model", "provider:model" or "provider/model";
# values may be an int or an object with window / max_input / max_output.
MODEL_CONTEXT_WINDOWS={"my-gateway-model": 200000, "openrouter/anthropic/claude-sonnet-5.5": 1000000, "ollama/qwen2.5:7b": {"window": 32768, "max_output": 4096}}
```

An explicit entry always wins over everything below it, and `/context` then reports `source: user`.
Remove the entry to fall back to the learned/metadata/catalog/heuristic layers.

### Provider metadata probes

When no user or learned value exists, YAICLI asks the provider for the real limit. The probe is lazy
(only when the budget is first needed), single-attempt, bounded to 2 seconds, and completely silent
on errors or timeouts — it simply falls through to the catalog:

| Provider | Probe | Fields used |
| --- | --- | --- |
| OpenRouter | `GET {BASE_URL}/models` | `context_length`, `top_provider.max_completion_tokens` |
| Gemini | `models.get` | `input_token_limit`, `output_token_limit` |
| Ollama | `/api/show` | the largest positive `model_info.*.context_length` |

The result is cached per `(provider, base_url, model)`. Failed or empty probes are also remembered
in-process for 5 minutes (`METADATA_MISS_TTL_SECONDS=300`), so an offline or metadata-less provider
pays the ≤2 s timeout on the first request only instead of on every turn. Set
`ENABLE_MODEL_METADATA=false` to skip probes entirely (no extra network calls at all).

### Learning the real limit from a context-length error

Even with estimation, a provider can reject a request as too long (the exact window differs per
model). When the error text carries the real limit (for example `maximum context length is 200000
tokens`), YAICLI parses it and records it as a `learned` value — in memory immediately and on disk
for the next session (30 days). The request is re-trimmed to the new budget and retried **once**; the
stderr notice names the learned number:

```text
Provider rejected the request as too long; learned the real context limit (200,000 tokens), dropped 1 older message(s) and retrying once (210,000 -> 197,952 est. tokens).
```

The next `/context` then reports `source: learned`, and subsequent requests use the corrected window.

### Cache

Resolved windows are cached in `<config-dir>/cache/model_limits.json` (next to `config.ini`):

- provider metadata: 7 days;
- learned limits: 30 days.

Set `ENABLE_MODEL_LIMITS_CACHE=false` to keep the cache in memory only — nothing is read from or
written to disk. Deleting the file is always safe: it is a pure cache and is rebuilt on demand.

### Explicit budget override and safety headroom

| Setting | Meaning |
| --- | --- |
| `CONTEXT_BUDGET_TOKENS` | `0` (default) = derive from the window (`window - MAX_TOKENS - CONTEXT_SAFETY_TOKENS`). A value `> 0` overrides the derived budget **verbatim** — the legacy behaviour, useful as a hard cap or a fallback. |
| `CONTEXT_SAFETY_TOKENS` | Extra headroom kept below `window - MAX_TOKENS` for tokenizer/request drift (default `1024`). Raise it if you still hit "too long" errors; `0` disables the headroom. |
| `MAX_TOKENS` | The requested output limit. It is reserved from the window but never rewritten by YAICLI. |

### Unknown-model warning

When the resolved `source` is `default` and a model is configured, the first request of every session
prints a two-line warning to **stderr**; the numbers are still shown and the message says how to fix
them:

```text
Context window for model "my-gateway-model" is unknown; assuming 128,000 tokens (source: default).
Set MODEL_CONTEXT_WINDOWS={"my-gateway-model": 200000} or CONTEXT_BUDGET_TOKENS to override.
```

## 3. Context-length self-healing

Even with estimation, a provider can reject a request with a `context_length` error (the exact
window differs per model). When that happens, YAICLI:

1. parses the real limit from the error text when present (for example `maximum context length is
   200000 tokens`) and records it as a `learned` value — in memory and in the on-disk cache — so the
   next request, `/context` and `/compact` all use the corrected window;
2. re-trims the payload to the new budget, dropping whole turn groups;
3. retries the request **once**;
4. if it still fails, prints an actionable error (provider, cause, suggestion) and exits with the
   usual error code — instead of the previous behaviour of failing every subsequent request.

A single turn that is already too large cannot be trimmed: YAICLI still records the learned limit,
then prints the actionable error instead of retrying forever. In the REPL you can also recover
manually with `/clear` or `/compact`.

## 4. Inspecting and compacting the conversation

In the interactive REPL:

| Command | Description |
| --- | --- |
| `/context` or `/ctx` | Show the estimated context usage: resolved window and its source, role prompt, project context, `/add` context, history/tool output, total vs budget, remaining and reserve. Subcommands: `list`, `clear`, `add <path>`, `remove <path>`, `budget`. |
| `/compact [keep_rounds]` | Manually compact the conversation, keeping the last *N* turns (turn groups); older ones are dropped from the outgoing request. Without an argument the default retention applies. |
| `/clear` | Start over with an empty history. |

Bare `/context` prints the usage block and then the legacy `/add` file list; `/context budget`
(aliases `stats` / `usage`) prints only the usage block. The subcommand list is printed only for an
unknown subcommand (`Available: list, clear, add <path>, remove <path>, budget`):

```text
Context usage (estimated):
  window        : 1,000,000 tokens (source: metadata · openrouter /models)
  role prompt   : 12 tokens
  project ctx   : 1,234 tokens
  /add context  : 0 tokens
  history       : 2,175 tokens (tool output 1,148)
  overhead      : 3 tokens
  total         : 3,424 / 997,952 tokens (0.3%)
  remaining     : 994,528 tokens
  reserve       : 2,048 (MAX_TOKENS 1,024 + safety 1,024)
  Use /compact [keep_rounds] to drop older turn groups.
```

- `window` is the resolved model window plus where it came from (`source: metadata · openrouter
  /models` above). An unknown model renders `source: default · assumed for unknown model; set
  MODEL_CONTEXT_WINDOWS to override`.
- `role prompt`, `project ctx`, `/add context` and `history` are the token buckets the next request
  carries (`tool output` is the part of history that came from tools).
- `overhead` is the fixed request priming tokens (`REQUEST_OVERHEAD_TOKENS = 3`) that are not part of
  any message; it is counted in `total` and shown so the rows add up to the total.
- `total` is checked against the request budget; `remaining` is what is left of it.
- `reserve` is the output headroom kept out of the window (`MAX_TOKENS` + `CONTEXT_SAFETY_TOKENS`).

Use `/context` when a session starts behaving as if it forgot earlier steps (check the window source
first — an unknown model may be budgeted far below its real window); then `/compact` to reclaim
budget deliberately, pin a window with `MODEL_CONTEXT_WINDOWS`, or raise `CONTEXT_BUDGET_TOKENS` to
a hard value.

## 5. Tokens & cost

YAICLI measures what a run actually costs (v0.22 K17). Token counts come from the provider
response whenever the provider reports them, so they are exact for the request. When a provider
does not report usage (or an OpenAI-compatible proxy rejects the streaming usage option), YAICLI
falls back to the same heuristic as the budget estimator and marks the numbers as **estimated**
instead of hiding them.

- per request: prompt/completion/total tokens, plus prompt-cache hits (`cached_tokens`) and
  reasoning tokens (`reasoning_tokens`) when the provider reports them;
- per session: totals **per model**, request count, and tool metrics (call count, total wall-clock
  duration, result characters the model saw);
- per run: the last provider `finish_reason` (so a `"length"` truncation is visible).

### Cost

Cost is an **estimate** in USD, computed as `tokens / 1M × price` per model. The built-in price
table covers common OpenAI, Anthropic, Gemini, DeepSeek, Qwen and GLM models (approximate public
list prices). Override it for exact accounting — and to price models the table does not know — with
`MODEL_PRICING`, a JSON object of model-prefix to USD-per-1M-token prices:

```ini
[core]
# JSON; prefixes are matched longest-first, and override the built-in table
MODEL_PRICING={"gpt-4o": {"input": 2.5, "output": 10}, "my-local-model": {"input": 0, "output": 0}}
```

Unknown models are reported as "unknown model pricing" (and `cost_usd: null` in JSON output)
instead of a guessed number. With cache pricing the estimate is intentionally conservative: cached
tokens are still billed at the full input price.

### Showing usage

| Where | What |
| --- | --- |
| `SHOW_USAGE` (default `true`) | One dim line after each interactive turn, e.g. `tokens 1,234 in / 567 out · $0.0021 · 1.2s · stop`. Unknown cost is simply omitted; machine/headless output never prints it. |
| `/cost` (interactive) | Session totals, per-model breakdown, estimated USD cost, tool call metrics and the last finish reason. |
| `--output-format json` | The full `usage` object + `finish_reason` (see [Headless & Scripting](headless.md)). |
| `--output-format stream-json` | A final `usage` event with the same numbers. |

When `finish_reason` is `"length"` the answer was truncated by the output token limit: YAICLI
prints one `MAX_TOKENS` warning to stderr in every mode and reports `finish_reason: "length"` in
structured output. Raise `MAX_TOKENS` (or reduce the context/tool output sent) to get complete
answers.

## 6. Session and memory limits

- `INTERACTIVE_ROUND` (default `25`) is the number of chat turns kept in the REPL
  (×2 messages), not a token limit. Token trimming is described above.
- `MAX_HISTORY` (default `500`) is the number of entries in the prompt history file — it has no
  effect on the conversation context.
- Tool outputs already spilled to `TOOL_OUTPUT_DIR` are not re-sent automatically; they only enter
  the context if the model reads them back.
- Image input is bounded by the provider; keep images reasonably small (the local cache also holds
  the base64 payload in the session).

## Recommended settings for long tasks

```ini
[core]
# Budget: 0 = derive from the resolved window (window - MAX_TOKENS - safety);
# a value > 0 overrides it verbatim as a hard cap.
CONTEXT_BUDGET_TOKENS=0
# Extra headroom below window - MAX_TOKENS; raise it if you still hit "too long" errors.
CONTEXT_SAFETY_TOKENS=1024
# Pin a window when the provider/catalog does not report the model correctly.
# MODEL_CONTEXT_WINDOWS={"my-gateway-model": 200000}
# Lower to reduce tokens per tool result if your model has a small window
TOOL_OUTPUT_MAX_CHARS=16000
# More tool rounds before the depth limit stops the run
MAX_TOOL_CALL_DEPTH=12
```

## Related configuration

| Key | Default | Purpose |
| --- | --- | --- |
| `TOOL_OUTPUT_MAX_CHARS` | `32000` | Per-tool-result character cap (`0` = unlimited) |
| `TOOL_OUTPUT_DIR` | `<tempdir>/yaicli/chats/tool-outputs` | Where full tool outputs are spilled (independent of the per-project session store) |
| `TOOL_DISPLAY_MAX_LINES` | `15` | Terminal preview lines (`0` = unlimited; model unaffected) |
| `TOOL_DISPLAY_MAX_CHARS` | `4000` | Terminal preview characters (`0` = unlimited; model unaffected) |
| `TOOL_CALL_PREVIEW_MAX_CHARS` | `300` | Max characters of the `@Function call:` argument line (`0` = raw) |
| `CONTEXT_BUDGET_TOKENS` | `0` (derive from window) | Per-request token budget (`> 0` = verbatim override) |
| `MODEL_CONTEXT_WINDOWS` | - (empty map) | JSON per-model context-window overrides (`model` / `provider:model` / `provider/model` keys) |
| `ENABLE_MODEL_METADATA` | `true` | Probe provider metadata (OpenRouter / Gemini / Ollama) for the model window |
| `CONTEXT_SAFETY_TOKENS` | `1024` | Extra headroom below `window - MAX_TOKENS` when deriving the budget |
| `ENABLE_MODEL_LIMITS_CACHE` | `true` | Cache resolved windows in `<config-dir>/cache/model_limits.json` (7-day metadata / 30-day learned TTLs) |
| `MAX_TOOL_CALL_DEPTH` | `8` | Tool rounds per request (`--max-turns` overrides per run) |
| `EXIT_ON_DEPTH_LIMIT` | `true` | One-shot run exits non-zero when the tool-round limit is reached |
| `INTERACTIVE_ROUND` | `25` | Chat turns kept in the REPL |
| `SHOW_USAGE` | `true` | Print one dim token/cost line after each interactive turn |
| `MODEL_PRICING` | `{}` | JSON price overrides (`{"model-prefix": {"input": x, "output": y}}`, USD per 1M tokens) |

## See Also

- [Headless & Scripting](headless.md)
- [Permissions & Safety](permissions.md)
- [Configuration](configuration.md)
- [Conversation & History](../advanced/history.md)
