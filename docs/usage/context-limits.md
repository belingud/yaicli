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

Full outputs are stored under `TOOL_OUTPUT_DIR`, which defaults to a `tool-outputs/` directory
under the chat-history directory. The truncated text includes the path so the model can read the
rest:

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
  turn: left pane lists the entries, right pane shows the selected result. `↑/↓` select, `Tab`
  switches pane, `PgUp/PgDn` scroll, `f` toggles between the model-visible text and the spilled full
  file (capped at 1 MB), and `q`/`Esc`/`Ctrl+O` closes it, restoring the REPL. Non-interactive runs
  fall back to the inline last-output panel.
- Long tool-call arguments on the `@Function call:` line are summarized
  (`TOOL_CALL_PREVIEW_MAX_CHARS=300`); a large `content`/`command` value appears as `<N chars>`.
- If the spill file cannot be written (read-only disk, permission error), YAICLI degrades to plain
  truncation without the path — the request still succeeds.
- Spilled files are created with mode `0600` on POSIX (file output may contain secrets); clean the
  `TOOL_OUTPUT_DIR` up periodically.

## 2. Token budget

Before each provider request, YAICLI estimates the tokens in the conversation (a stdlib heuristic:
~3.5 characters per token with corrections for CJK text, plus a fixed per-message overhead) and
compares it with the budget:

| Setting | Meaning |
| --- | --- |
| `CONTEXT_BUDGET_TOKENS` | Token budget for one request. Default `0` = derive 70% of the model context window (fallback 128k tokens when the model is unknown). |
| `MAX_TOOL_CALL_DEPTH` / `--max-turns` | Bounds how many tool rounds one request may run (default `8`). |

If the conversation is over budget, YAICLI first trims mechanically — no extra API call, no extra
cost — then sends the request. Trimming by message count alone is not enough: a `tool_calls`
message must never be separated from its `tool` results, or every provider rejects the payload.
YAICLI therefore trims by **turn group**:

- a turn group is one user message plus the assistant/tool messages that follow it;
- whole groups are dropped, oldest first;
- an assistant message with `tool_calls` is always kept together with its tool results
  (zero orphan `tool` messages);
- leading system/context messages are preserved;
- one line is printed to stderr when trimming happens, so you know why old context disappeared.

## 3. Context-length self-healing

Even with estimation, a provider can reject a request with a `context_length` error (the exact
window differs per model). When that happens, YAICLI:

1. drops one more turn group (or trims further to the budget);
2. retries the request **once**;
3. if it still fails, prints an actionable error (provider, cause, suggestion) and exits with the
   usual error code — instead of the previous behaviour of failing every subsequent request.

In the REPL you can also recover manually with `/clear` or `/compact`.

## 4. Inspecting and compacting the conversation

In the interactive REPL:

| Command | Description |
| --- | --- |
| `/context` or `/ctx` | Show the estimated context usage: system prompt, history, tool output, remaining budget, and the budget being used. |
| `/compact [keep_rounds]` | Manually compact the conversation, keeping the last *N* turns (turn groups); older ones are dropped from the outgoing request. Without an argument the default retention applies. |
| `/clear` | Start over with an empty history. |

Use `/context` when a session starts behaving as if it forgot earlier steps; then `/compact` to
reclaim budget deliberately, or raise `CONTEXT_BUDGET_TOKENS` if your model has a larger window.

## 5. Session and memory limits

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
# Leave at 0 to auto-derive 70% of the model window; set explicitly for small windows
CONTEXT_BUDGET_TOKENS=0
# Lower to reduce tokens per tool result if your model has a small window
TOOL_OUTPUT_MAX_CHARS=16000
# More tool rounds before the depth limit stops the run
MAX_TOOL_CALL_DEPTH=12
```

## Related configuration

| Key | Default | Purpose |
| --- | --- | --- |
| `TOOL_OUTPUT_MAX_CHARS` | `32000` | Per-tool-result character cap (`0` = unlimited) |
| `TOOL_OUTPUT_DIR` | `<chat history>/tool-outputs` | Where full tool outputs are spilled |
| `TOOL_DISPLAY_MAX_LINES` | `15` | Terminal preview lines (`0` = unlimited; model unaffected) |
| `TOOL_DISPLAY_MAX_CHARS` | `4000` | Terminal preview characters (`0` = unlimited; model unaffected) |
| `TOOL_CALL_PREVIEW_MAX_CHARS` | `300` | Max characters of the `@Function call:` argument line (`0` = raw) |
| `CONTEXT_BUDGET_TOKENS` | `0` (70% of window) | Per-request token budget |
| `MAX_TOOL_CALL_DEPTH` | `8` | Tool rounds per request (`--max-turns` overrides per run) |
| `EXIT_ON_DEPTH_LIMIT` | `true` | One-shot run exits non-zero when the tool-round limit is reached |
| `INTERACTIVE_ROUND` | `25` | Chat turns kept in the REPL |

## See Also

- [Headless & Scripting](headless.md)
- [Permissions & Safety](permissions.md)
- [Configuration](configuration.md)
- [Conversation & History](../advanced/history.md)
