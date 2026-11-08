
---
## [0.22.0](https://github.com/belingud/yaicli/compare/v0.21.2..v0.22.0) - 2026-11-08

### ⚠️ Behaviour changes

- `--output-format json` now carries real token counts, estimated cost and tool metrics in its
  `usage` object, plus a new `finish_reason` field (`length` also prints an stderr warning).
- Tool-output spill files and saved/resumed sessions are redacted by default (`REDACT_SECRETS`);
  set `REDACT_SECRETS=false` to keep raw bytes on disk. The model still sees the real content.
- The interactive prompt now shows the model, role and context usage; `/model`, `/role`, `/retry`
  and `/cost` are available and `/` triggers command completion.

### ⛰️  Features

- feat(repl): show model/role/context in the prompt, add /model /role /retry and slash completion - ([c34620c](https://github.com/belingud/yaicli/commit/631f305801794e24d3925d9ba4023dd93ba2f698)) - Belingud
- feat(tools): narrow offered tool schemas with ENABLED_TOOLS/--tools - ([98cd3b7](https://github.com/belingud/yaicli/commit/101b097dad01e7548d08e42dda3df3ac825500f6)) - Belingud
- feat(usage): surface provider token usage, cost and finish reasons - ([64ae9c6](https://github.com/belingud/yaicli/commit/cdb8158cd6dd0ecdd834134f055b98bb5c7e478f)) - Belingud
- feat(security): redact secrets before tool output and sessions hit disk - ([4274473](https://github.com/belingud/yaicli/commit/1ff622d4b9e26ecfd3f884c31574e279308e1b95)) - Belingud
- feat(mcp): harden MCP config, timeouts, tool caps and result handling - ([f61da5d](https://github.com/belingud/yaicli/commit/f61da5d053cf917364153cf964f7b81809a96f9d)) - Belingud
- feat(config): add v0.22 keys for MCP hardening, usage and redaction - ([cf823fb](https://github.com/belingud/yaicli/commit/cf823fb015cd73fbc7b40340db9f099ac1e90ad6)) - Belingud

### 📚 Documentation

- docs: document the v0.22 observability, MCP, redaction and REPL features - ([83ef2ab](https://github.com/belingud/yaicli/commit/64f2e405b51974a8814315889a5edf8b17d1531c)) - Belingud
- docs(changelog): update changelog for v0.21.2 release - ([d142223](https://github.com/belingud/yaicli/commit/d142223a6a8e783dd0e19434f87e93beb431841f)) - Belingud


---
## [0.21.2](https://github.com/belingud/yaicli/compare/v0.21.1..v0.21.2) - 2026-11-08

### 🐛 Bug Fixes

- fix(config): type provider/retry keys and keep the docs in sync

Two settings were read straight from the config dict without a typed
DEFAULT_CONFIG_MAP entry, so a config-file `false` arrived as the truthy
string "false": toggling DISABLE_PARALLEL_TOOL_USE never re-enabled Anthropic
parallel tool calls, and RETRY_MAX_DELAY was invisible (no template line, no
YAI_ alias). Both are now typed map keys with environment aliases and template
entries, and the Anthropic provider coerces the flag with str2bool for direct
dict configs.

MINIMAX_REASONING_SPLIT was documented but missing from `ai --template`; it is
now part of the shipped template. (It stays MiniMax-specific: only that
provider sends `reasoning_split`.)

Docs: the README reference table gains the four keys it had missed (TOOL_POLICY,
TOOL_DISPLAY_MAX_LINES/CHARS, TOOL_CALL_PREVIEW_MAX_CHARS) plus the new keys;
configuration.md documents DISABLE_PARALLEL_TOOL_USE/RETRY_MAX_DELAY and the
file-structure snippet matches the template; the provider pages note the
Anthropic switch, Azure OPENAI_API_VERSION and the programmatic-only
AZURE_AD_TOKEN_PROVIDER/DEFAULT_HEADERS.

tests/test_docs_config.py is the drift guard: docs table, README table, shipped
template and docs snippet must all match DEFAULT_CONFIG_MAP (keys, env vars and
defaults). - ([5f0ddbe](https://github.com/belingud/yaicli/commit/5f0ddbe0bf3692615c266f2b334bf96c95d20550)) - Belingud

### 📚 Documentation

- docs(changelog): update changelog for v0.21.1 release - ([e6ed590](https://github.com/belingud/yaicli/commit/e6ed5909f65f74efc1f1142eb184977e3ef2ca84)) - Belingud


---
## [0.21.1](https://github.com/belingud/yaicli/compare/v0.21.0..v0.21.1) - 2026-11-08

### ⛰️  Features

- feat(provider)!: drop Yi (01.AI) provider support

Yi (01.AI) is no longer supported, so stop shipping the provider: remove the
yi_provider module and the "yi" ProviderFactory key, delete the provider docs
page plus its overview matrix rows and mkdocs nav entry, and drop the related
tests. README no longer lists Yi in the compatibility list or the
configuration examples.

BREAKING CHANGE: PROVIDER=yi now fails with "Unknown provider: yi". Consumers
that still need a Yi-compatible endpoint can use PROVIDER=openai-compatible
with BASE_URL set. - ([37d5775](https://github.com/belingud/yaicli/commit/37d57758056f6b0c2985a100c832fb56c4c6175d)) - Belingud

### 📚 Documentation

- docs(changelog): update changelog for v0.21.0 release - ([dc52fa1](https://github.com/belingud/yaicli/commit/dc52fa1b93b011108c93f4bb222cea6f1ec8ab5e)) - Belingud

### ⚙️ Miscellaneous Tasks

- chore(task): archive the v0.21.0 safety foundation milestone

Moves the v0.21 parent task and K10-K14 subtasks to the archive, marks the
milestone acceptance complete, and records the v0.21.0 release session
(K10-K14, verification, release evidence, v0.22 next steps) in the
developer journal. - ([161de73](https://github.com/belingud/yaicli/commit/161de738e63ebf94d37680681213be219bf09987)) - Belingud
- chore: record journal - ([5e3a8ee](https://github.com/belingud/yaicli/commit/5e3a8eeab89368f956b7d8b03da3639e3f002988)) - Belingud


---
## [0.21.0](https://github.com/belingud/yaicli/compare/v0.20.0..v0.21.0) - 2026-11-07

### ⛰️  Features

- feat(chat): isolate sessions per project, stamp metadata and add --resume (K13)

Sessions now live under ~/.yaicli/sessions/<sha256(cwd)[:16]>/ (0700 dirs,
0600 atomic files) unless CHAT_HISTORY_DIR is explicitly overridden, which
keeps the old flat directory. Each session records model/provider/role/cwd
and created/updated timestamps (legacy JSON loads fine and is backfilled on
save). New --resume continues the newest session of the current project
with a one-line notice; no session starts a new one explicitly. A missed
--chat title now prints an explicit notice instead of silently starting a
new session. The prompt history file is created 0600 with 0700 dirs and
legacy 0644 files are repaired on append/trim. Old temp-dir sessions are
left in place (no auto-migration); tests cover path keying, modes,
metadata, resume/miss semantics and the history privacy. - ([7def9ad](https://github.com/belingud/yaicli/commit/7def9adad9b3e503ab5dcc726e3ceb69b13a61aa)) - Belingud
- feat(context): auto-load project AGENTS.md context into the system prompt (K12)

New stdlib yaicli/project_context.py discovers AGENTS.md / CLAUDE.md /
.yaicli.md from the current directory up to the git root (inclusive),
outermost first so the most specific instructions come last, deduping
symlinked files. The bounded block is appended to the role system message
(config: ENABLE_PROJECT_CONTEXT default true, PROJECT_CONTEXT_MAX_CHARS
default 20000, YAI_ env keys); truncation prints one stderr notice and
unreadable files are skipped. With no project files the message payload is
byte-identical to before, disabled mode does zero filesystem reads, and
nothing is written at import. - ([001258f](https://github.com/belingud/yaicli/commit/001258f3a667cbc264654690a17cfef4a4d8f25f)) - Belingud
- feat(tools): confine writes to the workspace, back up mutations and add /undo (K11)

fs_write_file / fs_edit_file / fs_file_operations now go through a stdlib
workspace guard before execution: resolved targets must stay strictly inside
WORKSPACE_ROOT (cfg/env, default cwd), symlink escapes are refused, and
.git/.ssh/.aws/.gnupg components plus .env*/*.pem/*.key basenames are
protected. Existing targets are backed up to .yaicli-backups (0600/0700)
before the mutation; a failed backup fails closed. Successful mutations are
pushed onto a bounded in-memory stack and /undo restores the last change or
deletes files the agent created. Denials are in-band JSON the model can act
on; fs_edit_file(dry_run) creates no backup/undo. - ([d305e92](https://github.com/belingud/yaicli/commit/d305e924e8bd6a79daa069ef4d043c49b04f39c1)) - Belingud
- feat(permissions): add TOOL_POLICY readonly/standard/trusted modes (K10)

The session-wide TOOL_POLICY mode (YAI_TOOL_POLICY env > config.ini >
default standard) is a hard ceiling/floor in the tool gate: readonly
auto-allows read/network tools and denies write/exec even when they are
pre-approved or confirmation is disabled; trusted auto-allows every
non-dangerous tool; danger-classified shell commands keep their existing
confirmation/denial precedence in every mode. Every audit line now records
the effective policy. Invalid values fall back to standard with one
stderr warning.

Also fixes a test-hygiene issue where the permission test suite appended
to the real user audit log by default. - ([09a41ad](https://github.com/belingud/yaicli/commit/09a41ad29f71177d7474dc22f664738764e1ba35)) - Belingud

### 🐛 Bug Fixes

- fix(providers): keep every tool call in multi-call turns (K14)

A provider response can now carry multiple calls: LLMResponse.tool_calls
(legacy .tool_call is kept in sync via explicit dual-set) and a shared
stdlib accumulator handles streaming index/id merging, same-name calls
without ids, id-then-index folding and dedupe. LLMClient collects and
executes every call, appending all assistant tool_calls and matching tool
results while filtering by tool policy.

Fixes silent drops: Anthropic non-stream/stream parallel tool_use blocks,
Gemini streamed same-name function calls, Ollama multiple calls, and the
single-slot streaming providers (chatglm/huggingface, minimax, ai21,
mistral, openai-compatible) which also no longer surface partial arguments
mid-stream. New helper/schema/provider/end-to-end tests under tests/llms. - ([7d5fa88](https://github.com/belingud/yaicli/commit/7d5fa88f7291707c7c2cc954634c4b4abee176aa)) - Belingud

### 📚 Documentation

- docs: document v0.21 project context, per-project sessions and parallel tool calls

Adds docs/usage/project-context.md (AGENTS.md discovery/cap/disable and
untrusted-input note) and docs/usage/sessions.md (per-project store, 0700/
0600, metadata, --resume, missed-title notice, no auto-migration, history
file privacy). Updates configuration/cli/commands/history/architecture and
the v0.21 upgrade section for K12-K14, refreshes the stale --help snapshot,
and extends README/index feature lists and mkdocs nav. - ([0bf4c55](https://github.com/belingud/yaicli/commit/0bf4c55e7572c4de7bc77f3c86c19d6f09868337)) - Belingud
- docs(spec): record v0.21 K13 per-project sessions and --resume contract

Adds the session-isolation openspec (per-project store, 0600/0700 privacy,
metadata, --resume, explicit missed-title notice, no auto-migration) and
updates the Python specs: session paths/keying/override semantics, prompt
history privacy, --resume/--chat CLI semantics, chat/const module map.
Marks K13 accepted in the milestone PRD. - ([363a561](https://github.com/belingud/yaicli/commit/363a561628df4af603b11409d08e7c2ca953d6cb)) - Belingud
- docs(spec): document the plural tool_calls contract and shared accumulator (K14)

Provider guidelines now describe LLMResponse.tool_calls with the legacy
tool_call mirror, the shared yaicli/llms/tool_calls.py accumulator rules,
the no-partial-call streaming rule for native providers, and the new
multi-call test coverage. Marks K14 accepted in the milestone PRD. - ([7a5adfa](https://github.com/belingud/yaicli/commit/7a5adfade2b284e5f67111737091adbeb47f37df)) - Belingud
- docs(spec): record v0.21 K12 project context auto-load contract

Adds the project-context openspec (discovery to the git root, bounded block
with truncation notice, disable switch, no-import-writes) and documents the
new module/config keys plus the CLI message-assembly insertion point.
Marks K12 accepted in the milestone PRD. - ([3580931](https://github.com/belingud/yaicli/commit/3580931ae6a68f4878ddd3abbf90ee04bf795f1f)) - Belingud
- docs: document v0.21 permission modes, workspace write safety and /undo

Adds docs/usage/workspace-safety.md (confinement, protected paths, backups,
/undo, denial reasons, limits), a Permission modes section with the
readonly/standard/trusted table and audit policy field, the TOOL_POLICY
config key, the /undo command, a v0.21 upgrade section describing the
default-on workspace confinement behavior change, and README/index safety
mentions. - ([116166c](https://github.com/belingud/yaicli/commit/116166ca4806f2047282f9fdfac8d560f31ef17c)) - Belingud
- docs(spec): record v0.21 K10 tool policy modes and K11 workspace write safety

Adds the workspace-write-safety openspec (confinement, protected paths,
backups, /undo, in-band denial contract) and the session-wide TOOL_POLICY
requirements + audit policy field to tool-execution-confirmation. Updates
the Python layer specs (function-tool guidelines, CLI/REPL commands,
config/paths, module map) and marks K10/K11 accepted in the milestone PRD. - ([fd25b83](https://github.com/belingud/yaicli/commit/fd25b8393dedd63d3f80d115c0e005db96d79200)) - Belingud
- docs(changelog): update changelog for v0.20.0 release

Sync docs/changelog.md, refresh uv.lock for 0.20.0, and teach git-cliff to
group build(deps) commits so the K09 packaging change is listed. - ([5e69202](https://github.com/belingud/yaicli/commit/5e69202d06bd8a31d35daa27f4cd983040a19ccd)) - Belingud

### ⚙️ Miscellaneous Tasks

- chore(task): record v0.21 K10-K14 implementation tasks and acceptance

Adds the per-item Trellis subtasks (K10-K14) with their PRDs/context and
marks every milestone acceptance item checked in the parent PRD. Release
bookkeeping (archives/journal) follows the v0.21.0 tag. - ([e52b44d](https://github.com/belingud/yaicli/commit/e52b44de1c915598e65fcc49e391a1fba510c9c8)) - Belingud
- chore: record journal - ([0feeb96](https://github.com/belingud/yaicli/commit/0feeb96851226b10d95cb1482236d89ed6afd26f)) - Belingud
- chore(task): plan the v0.21 safety foundation milestone - ([c59f197](https://github.com/belingud/yaicli/commit/c59f197194c9a6043309958aaabb48c4bb787747)) - Belingud
- chore(task): archive 11-05-v020-lightweight-safety - ([a852c58](https://github.com/belingud/yaicli/commit/a852c58f086384b380d2b71e86ac620b1f1a4e96)) - Belingud


---
## [0.20.0](https://github.com/belingud/yaicli/compare/v0.19.1..v0.20.0) - 2026-11-07

### 🐛 Bug Fixes

- fix(viewer): show full tool names in the output list

The compact labels from 2f026ca (shell/read/web/...) hid which tool actually ran.
The list and header now show the raw tool name again (execute_shell_command,
fs_read_file, fetch_webpage, _mcp__<tool>, ...), with the call caption line and
result size unchanged so mixed-tool turns stay scannable. - ([641d7cf](https://github.com/belingud/yaicli/commit/641d7cf8194675297a088955bc4a898f4f5d6e9b)) - Belingud

### 📦 Build

- build(deps): keep tools complete in base and split Anthropic cloud extras (K09)

- base keeps ddgs/trafilatura/fastmcp so every builtin tool and MCP works on a
  plain 'pip install yaicli'; only the cloud SDK closure moves out
- anthropic[bedrock,vertex] -> [bedrock]/[vertex] extras; [all] stays complete
- ProviderFactory maps missing optional SDKs to a classified AgentError with the
  'pip install "yaicli[<extra>]"' hint; Anthropic Bedrock/Vertex fast-fail with
  the right extra and no longer forward the shared api_key to the cloud clients
- tests/test_packaging.py locks the tools-complete base policy (3.10-compatible
  parser); install/upgrade/provider docs updated
- verified: wheel METADATA + fresh venv base install imports all 12 builtin tool
  modules, fastmcp/trafilatura/ddgs, and ai --list-functions lists builtin tools - ([d874b09](https://github.com/belingud/yaicli/commit/d874b091287e0efcf852041d051bf2a835b66ac4)) - Belingud

### 📚 Documentation

- docs: refresh lightweight claims and v0.20 upgrade notes

- README/docs index: v0.20 measured numbers (entry/lazy client: REPL ready
  ~0.55-0.65s, --help no longer imports the CLI stack, 95 dist base with the
  cloud SDK closure opt-in)
- upgrade notes: v0.20 is current; startup/viewer/cloud-extras migration list
- install docs point at the v0.20 + v0.19 change lists - ([a9f347d](https://github.com/belingud/yaicli/commit/a9f347d24cd9e4fe03512a3f6b4c6418d5314c30)) - Belingud
- docs(spec): require raw tool names in the Ctrl+O viewer chrome

Capture the 641d7cf lesson so abbreviated viewer labels do not come back:
- function-tool-guidelines.md: new 'Viewer chrome must show the raw tool name'
  rule (entry.name in list + header, caption/size are supplements, no aliases,
  no _mcp__ stripping, wrong/correct examples, locking test names)
- cli-and-rendering.md: Ctrl+O viewer bullet points at the rule - ([9be64e2](https://github.com/belingud/yaicli/commit/9be64e27caa0928f9f29761bcbf3dc9d5ccbc770)) - Belingud
- docs(changelog): update changelog for v0.19.1 release - ([fc8b98c](https://github.com/belingud/yaicli/commit/fc8b98cf0a821f2cfc592b57d7d89d24586ac291)) - Belingud

### ⚡ Performance

- perf(startup): defer heavy imports and build the LLM client lazily (K08)

- entry.py: lazy option-callback proxies for role/chat/functions/provider so
  --help/--template no longer import the CLI stack (entry import 563ms -> 311ms)
- cli.py: prompt_toolkit, @path completer and file history are imported on first
  REPL/exec use; no PromptSession is built in __init__ (REPL builds the only one)
- cli.py: LLM client constructed on first access via a client property, so the REPL
  shows its first prompt before the provider SDK import (proxy ~1.55s -> ~0.55s)
- scripts/bench.py + bench.yml: cold-start gate (version/help/template/entry import/
  REPL readiness/one-shot-to-first-request) with P50 limits - ([3d33651](https://github.com/belingud/yaicli/commit/3d33651a88ab54175f5b654bc2388e0fc49d0a57)) - Belingud

### ⚙️ Miscellaneous Tasks

- ci(bench): widen the one-shot local-overhead gate to 2200 ms for shared runners - ([390e045](https://github.com/belingud/yaicli/commit/390e045e5b8caf1838f75f877a395b09ec0ee127)) - Belingud
- chore(task): mark W1 (K08+K09) acceptance in the v0.20 PRD - ([b42c5a1](https://github.com/belingud/yaicli/commit/b42c5a16afbf00a8dd33d08cbf5e53dd1aea224c)) - Belingud
- chore(task): archive 11-05-k09-tools-complete-packaging - ([7000679](https://github.com/belingud/yaicli/commit/70006791f280af7e9daf380477f51295e8d62a11)) - Belingud
- chore(task): archive 11-05-k08-startup-latency - ([58032af](https://github.com/belingud/yaicli/commit/58032aff67e49cc6a0c9e881d44bcce99fc1332c)) - Belingud
- chore: record journal - ([fddffba](https://github.com/belingud/yaicli/commit/fddffba96dc070bd4add807c8ba0ba803ac7dcd7)) - Belingud
- chore(task): archive 11-05-background-generation-verify - ([dfae6fe](https://github.com/belingud/yaicli/commit/dfae6fe9b66f83f7763ee89f40022bec73e9f78c)) - Belingud
- chore(task): archive 11-05-background-generation-cancel - ([133bb3d](https://github.com/belingud/yaicli/commit/133bb3d999947cc9280fd722a5e79f0078f556e7)) - Belingud
- chore(task): archive 11-05-background-generation-cli - ([9b5355c](https://github.com/belingud/yaicli/commit/9b5355c2dba3613b11228f11d59d2dbf037a49d2)) - Belingud
- chore(task): archive 11-05-worker-console-routing - ([b0d359e](https://github.com/belingud/yaicli/commit/b0d359ea657766cf4db7d3bc3749938eb57c4b84)) - Belingud
- chore(task): archive 11-05-tool-output-viewer - ([3f7f1ac](https://github.com/belingud/yaicli/commit/3f7f1ac634d3499a7080f60cf61bfa819bfe094c)) - Belingud
- chore(task): archive 11-05-stream-bridge - ([748550f](https://github.com/belingud/yaicli/commit/748550fa3aa42333bcb2fefff7382b89d46d4534)) - Belingud


---
## [0.19.1](https://github.com/belingud/yaicli/compare/v0.19.0..v0.19.1) - 2026-11-05

### ⛰️  Features

- feat(viewer): use compact tool labels in the output list - ([2f026ca](https://github.com/belingud/yaicli/commit/2f026cafa3609dd85f9db053fee8451c8a0677ea)) - Belingud
- feat(viewer): show tool-call captions in the output list

The left pane only showed '4. execute_shell_command (314c)', which made
repeated shell/MCP calls indistinguishable. Each entry now renders two lines:
the tool name + result size, and a one-line caption derived from the decoded
arguments (command, file_path/path, url, query, pattern, title; whitespace
collapsed and clipped). Entries fall back to the compact argument summary when
no identifying key exists, the list keeps the selection in a 10-entry window
with '… N more above/below' markers, and the header bar now shows the selected
entry ([2/4] name · kind · chars · truncated) next to the turn label.

Output-history entries carry the caption (computed in execute_tool_call from the
repaired argument dict), so it never re-parses a truncated argument string. - ([573f6d8](https://github.com/belingud/yaicli/commit/573f6d806b9c663ab57a196dc5c1299570d1dc94)) - Belingud
- feat(cli): run interactive generation on a worker thread

Interactive TTY turns now consume the completion generator through
ThreadedStream: the provider/tool pipeline runs on a worker thread while the
REPL thread renders, so Ctrl+O can open the tool-output viewer mid-answer and
generation continues; closing the viewer redraws the accumulated content.

Worker console output is routed through WorkerConsole into the bridge so the
main thread replays it in order; client/provider consoles are swapped for the
turn and restored afterwards. ThreadedStream now starts lazily on the first
next(), letting the CLI install console routing and register the active bridge
before the worker produces anything. Headless/machine paths are unchanged. - ([b9337bd](https://github.com/belingud/yaicli/commit/b9337bd9966f2cc4f3944ff2d6bc0f767eb9a951)) - Belingud
- feat(stream): route worker-thread console output through the bridge

WorkerConsole dispatches print() by thread: main-thread writes pass through to
the real console, generation-worker writes are queued on the active
ThreadedStream (with a stderr flag) and replayed in order by the UI thread, and
late writes from an aborted worker are dropped. install_worker_console_routing()
swaps the module consoles captured by the generation path and returns a
restorable handle. Bridge console events now carry the stderr target. Still not
wired into the CLI (task T2). - ([c0874a8](https://github.com/belingud/yaicli/commit/c0874a87b0ceb2b6c1b5165847352bfa42363d1b)) - Belingud
- feat(stream): add threaded stream bridge for background generation

ThreadedStream runs a completion generator on a worker thread and exposes the
generator protocol (__next__/send) to the UI thread over a FIFO event queue:
chunks, worker console prints, done/error. ConfirmToolCall waits for the
decision sent back by the UI thread; abort() cancels at the next chunk boundary
and drops late console events. Isolated module with unit tests (not wired into
the CLI yet, tracked as task T1). - ([b6709cf](https://github.com/belingud/yaicli/commit/b6709cf9d101b7820ea75fda6afae154e44b6bd8)) - Belingud
- feat(cli): toggle the tool-output viewer during generation

While a turn streams there is no prompt reading the keyboard, so install a
cbreak GenerationKeyWatcher (ISIG stays on: Ctrl+C still cancels) that captures
Ctrl+O. Printer.display_stream() gains pause_requested/on_pause hooks: it stops
the live region, opens the viewer, then redraws the accumulated content and
continues. The provider stream is paused while the viewer is open for now;
typed-ahead text is kept and pre-filled into the next prompt.

Headless/machine runs never start the watcher. - ([7fcea5f](https://github.com/belingud/yaicli/commit/7fcea5f431ac3c5980ccd2db9e9b44a74b8ced1c)) - Belingud
- feat(tools): add full-screen Ctrl+O tool-output viewer

Replace the inline Ctrl+O print (a0db5eb) with an alternate-screen two-pane
viewer: the left pane lists every tool output of the current turn (function and
MCP), the right pane shows the selected result. Keys: up/down select, Tab
switches pane, PgUp/PgDn/Home/End scroll, f toggles the spilled full file
(1 MB cap), q/Esc/Ctrl+O closes and restores the REPL.

Tool results are recorded in a turn-tagged history with spill metadata
(begin_turn from CLI._process_user_input); truncate_tool_output_meta adds the
metadata without changing the model-facing text. /show-output opens the same
viewer; non-TTY/headless and viewer failures fall back to the inline
last-output panel.

Docs, README, py specs and tests updated (turn grouping, fallbacks, viewer
app driven with pipe input). - ([d77e190](https://github.com/belingud/yaicli/commit/d77e190d6ebc351131c5cf9b7656375fcf829c09)) - Belingud
- feat(tools): render tool results as a compact head-only preview

Tool results and call arguments could flood the terminal even though the
model-facing result is already capped. Add a display-only layer that is
independent from TOOL_OUTPUT_MAX_CHARS: the panel shows only the first
TOOL_DISPLAY_MAX_LINES (15) lines / TOOL_DISPLAY_MAX_CHARS (4000) chars and a
'… +N lines · Ctrl+O to expand' marker, while the model still receives the
full capped result.

- The '@Function call:' line summarizes arguments (TOOL_CALL_PREVIEW_MAX_CHARS,
  default 300); large content/command values render as <N chars>.
- execute_tool_call records the last result; Ctrl+O in the REPL and
  /show-output re-print it in full (same renderer).
- New config keys + env vars, config template, docs, spec and tests.

Terminal display only: short outputs are unchanged (no marker). - ([a0db5eb](https://github.com/belingud/yaicli/commit/a0db5ebf8431babd954dc3d42aee81be1d625a05)) - Belingud

### 🐛 Bug Fixes

- fix(keys): stop macOS VDISCARD from swallowing Ctrl+O during generation

On macOS the tty driver keeps ^O bound to VDISCARD even in cbreak mode: the
key was consumed before GenerationKeyWatcher could read it and toggled
"discard output" instead, which matches the captured TUI (a missing
@Function call line between two tool panels) and a debug log that showed
watcher.start cbreak=True but no watcher.ctrl-o event. The viewer could
therefore never open and output silently went missing until the key was
pressed again.

- Disable VDISCARD (^O) and IXON (^S/^Q flow control) for the watcher window,
  restoring the saved termios on stop; log discard_disabled/flow_control_disabled.
- Decode CSI-u / modifyOtherKeys Ctrl+O encodings used by extended keyboard
  protocols (kitty/xterm) in addition to the plain 0x0f byte.
- Log every received byte in YAI_DEBUG_LOG mode and add generation.begin/end +
  prompt.begin breadcrumbs so a future freeze can be correlated with keypresses.
- Document the new events in docs/dev/debug-cli.md. - ([28f29f7](https://github.com/belingud/yaicli/commit/28f29f71b76ee3d39098829cd0cb46008aaf3618)) - Belingud
- fix(cli): service Ctrl+O between background stream chunks

The REPL blocked on the bridge queue waiting for the next chunk, so a Ctrl+O
request was only handled after the provider/tool produced something. During
long reasoning or a slow tool that looked like a frozen screen with no viewer,
and pressing Ctrl+O again did nothing until output resumed.

- ThreadedStream.poll_next(timeout) polls the event queue and returns None on
  timeout (chunks/errors/StopIteration behave like next()).
- Printer.display_stream() now polls background streams every 50ms and
  re-checks the viewer request each round, so the viewer opens promptly.
- Ctrl+O during a turn with no tool output yet prints a dim hint instead of
  silently doing nothing.
- Add opt-in YAI_DEBUG_LOG breadcrumbs (watcher start/skip, Ctrl+O byte,
  pause/resume ack, printer pause, viewer run begin/end/error) and document
  them in docs/dev/debug-cli.md for terminal-specific reproductions. - ([cba65ee](https://github.com/belingud/yaicli/commit/cba65eef4cac2d2fe37f6b78b11c13d3b3efc549)) - Belingud
- fix(stream): keep aborting/lingering workers from corrupting state

Cancellation and history safety (T4): background turns now pass the worker a
copy of the message list and adopt it only on success, so an aborted or
failed turn returns the untouched original (a lingering worker cannot pollute
the next turn's history). Each worker thread is registered with its owning
bridge, so late console output from an abandoned worker is dropped instead of
leaking into a newer generation; close() reports whether the worker is still
alive and the CLI keeps the routed consoles installed in that case (with a dim
notice) instead of restoring them under a running worker. Console wrappers are
unwrapped before re-wrapping to avoid chains across repeated abandons. - ([d598955](https://github.com/belingud/yaicli/commit/d598955927159c0728853b4ad52902bc2f24ea3b)) - Belingud

### 🚜 Refactor

- refactor(tools)!: rename execute_shell_command argument to command

The shell tool's model-facing argument was 'shell_command'; shorten it to
'command' so a call reads execute_shell_command(command=...). Update the builtin
schema/execute signature, the approval/risk/canonical-argument lookups, the
confirmation preview, and the affected tests.

BREAKING: models/roles that still pass shell_command will get a missing-argument
error; the tool name (execute_shell_command) is unchanged. - ([2eaaadf](https://github.com/belingud/yaicli/commit/2eaaadf5ce27044f54cd45afc33706a404538ffd)) - Belingud

### 📚 Documentation

- docs(tools): document background generation Ctrl+O behavior

Ctrl+O during an in-flight answer now opens the tool-output viewer while the
generation keeps running on a background worker thread; closing the viewer
redraws the accumulated answer. Update README, usage pages (cli, interactive,
commands, context-limits) and the py specs (background pipeline, cancellation,
abandoned-worker handling, worker-thread tool output rules). - ([f437f7e](https://github.com/belingud/yaicli/commit/f437f7e67edf142ccbf9c13a5b590e3187f520d9)) - Belingud

### ⚙️ Miscellaneous Tasks

- chore(task): record post-T5 Ctrl+O and tool-schema hotfixes - ([969b11b](https://github.com/belingud/yaicli/commit/969b11bd3ff7b81266b236377666d16a17ae928e)) - Belingud
- chore(task): complete T5 background generation verification - ([77acac9](https://github.com/belingud/yaicli/commit/77acac95cb4826e6d950d451d3fc02d3ae78db27)) - Belingud
- chore(task): complete T4 cancellation and history safety plan - ([1553c50](https://github.com/belingud/yaicli/commit/1553c50a427c5e044bec2ad51bd720aa8e91fcd4)) - Belingud
- chore(task): complete T3 background generation wiring plan - ([099ab94](https://github.com/belingud/yaicli/commit/099ab94b4ac2949baa20ca6f62df18c5ec5f26a2)) - Belingud
- chore(task): complete T2 worker console routing plan - ([6b3822f](https://github.com/belingud/yaicli/commit/6b3822f87f875694a57eacd1cf4de649ee364bc6)) - Belingud
- chore(task): complete T1 stream bridge plan - ([4dbd116](https://github.com/belingud/yaicli/commit/4dbd11602703d856c026f90dd86bdbddb5b961ef)) - Belingud
- chore(task): plan background generation as subtasks T1-T5 - ([13eb196](https://github.com/belingud/yaicli/commit/13eb1960a16c5012288daccc1d5fc9a1ff572efe)) - Belingud
- chore: record journal - ([e654434](https://github.com/belingud/yaicli/commit/e654434e0ad6bb3f9d087b95b9c9191aba9b3d43)) - Belingud


---
## [0.19.0](https://github.com/belingud/yaicli/compare/v0.18.0..v0.19.0) - 2026-11-04

### ⛰️  Features

- feat(cli): exit the REPL on a double Ctrl-C

Single Ctrl-C at the prompt still clears the current input line / cancels the current turn and keeps the session alive, but pressing Ctrl-C a second time within ~2 seconds now exits the REPL normally (like Ctrl-D); a completed prompt read resets the window, so a stray interrupt can never kill an interactive session. Generation interrupts follow the same counter: cancel the turn first, exit on the next Ctrl-C. One-shot SIGINT keeps exiting 130.
Update the REPL help banner, README/docs (keyboard shortcuts, commands, SIGINT section) and the cli-and-rendering spec; add REPL tests for double-press exit, single-press survival and window reset. - ([3c401ae](https://github.com/belingud/yaicli/commit/3c401ae0490c0ee72653276e494acfb14b04b9b6)) - Belingud
- feat(permissions): risk-aware confirmation, rule-based allowlist and audit log

K06: tool risk classes (read/write/network/exec) and a shlex-based danger classifier gate execution: dangerous shell commands always need explicit confirmation (non-interactive => deny, even with TOOL_CONFIRM=false), --yes auto-allows only read risk, --allowed-tools grants globs for one run. tool_permissions.json v2 adds argv_prefix/path_glob rules while still reading the v1 always_allow format; writes are atomic and 0600. The confirmation prompt now shows the canonical arguments that will execute (shell command + danger reasons, fs_write target/mode, fs_edit diff head 40). Denied calls return structured {error: tool_denied, reason} results and tool_denied feeds --fail-on-tool-denied (exit 3). Every decision is appended to tool_audit.jsonl (best-effort, secret-redacted) and /permissions can list/revoke. - ([c83c87c](https://github.com/belingud/yaicli/commit/c83c87c02f82c507a6a28df70568be4fc9f48640)) - Belingud
- feat(agent): context economy, retries and classified provider errors

K02: single truncation point for tool output (per-tool caps, head/tail marker, full text spilled to TOOL_OUTPUT_DIR), heuristic token estimator + model-window budget, turn-group-aligned history trimming that never orphans role=tool messages, context-length 400 self-heal (trim one group, retry once), bounded exponential retry for rate-limit/network/timeout/5xx before any content is streamed, depth-limit finish_reason/flag, /context usage summary and /compact.
K05: all 39 provider registry keys now raise classified AgentError (kind/status/retryable) instead of returning API errors as assistant content or silently stopping; request-time and mid-stream failures are wrapped, empty/in-band error bodies raise, and TIMEOUT is forwarded consistently. - ([3b8e27d](https://github.com/belingud/yaicli/commit/3b8e27d4e7bff982128072bd645d80cdd55650da)) - Belingud
- feat(cli): headless scripting contract and side-effect-free startup

K04: new -p/--print, --output-format text|json|stream-json, --json (shorthand), -q/--quiet, --max-turns, -y/--yes, --allowed-tools, --cwd and --fail-on-tool-denied flags; stdout carries only the result/events while warnings, errors and progress go to stderr; non-TTY runs skip prompt_toolkit/banner/Live; JSON object and NDJSON event contracts; exit codes 0/1/2/3/130/141; SIGINT semantics (one-shot 130, REPL clears/cancels); POSIX SIGPIPE restore so 'ai --help | head' no longer exits 1; --shell non-TTY only prints the command unless --yes.
K21: new _faststart console entry answers --version from the static __version__ without importing config/role/CLI (zero writes), python -m yaicli works, config/role/chat imports are write-free and lazy, ensure_config_file() creates config.ini 0600 under dir 0700 on first real run only, config dir resolution honours YAI_CONFIG_DIR/XDG/APPDATA and never writes /.config for an empty HOME. Includes the v0.19 error taxonomy/retry backbone (errors.py) and stderr console/EPIPE handling. - ([978eec5](https://github.com/belingud/yaicli/commit/978eec5a58fb976bed40bcea6964491ab3c56b09)) - Belingud
- feat(functions): load built-in tools out of the box and harden shell execution

K01/K15: load the 12 packaged builtins directly, let same-named user copies override them, and warn about stale exported copies via functions_manifest.json (version+sha256). A broken function file is skipped with one warning instead of bricking every tool. --install-functions now exports editable copies; --reinstall-functions refreshes them. K03: shell tool gains timeout (default 120s, process-group kill), workspace-bounded cwd, env allowlist (TOOL_ENV_INHERIT opt-in), output cap and exits 124 on timeout; the old 3-substring danger blacklist is replaced by shlex/argv classification in tools/risk.py. - ([77bd086](https://github.com/belingud/yaicli/commit/77bd086bb83c89faaefa278eb7ddc497b816b674)) - Belingud

### 🐛 Bug Fixes

- fix(runtime): keep config imports write-free and make tests environment-safe

D7: key migrations for legacy config files are detected read-only at import and appended only by ensure_config_file() on a real run (deduped per CONFIG_PATH, skipped when the key already exists), so 'import yaicli.config' and '--help' no longer mutate an existing config.ini.
T1: tests/conftest.py now sets the mock provider/credential environment before any yaicli module is imported, so the full suite is green in a fresh HOME/clean CI environment instead of failing five test_image tests with 'API_KEY is required'; the original environment is restored at session teardown.
_faststart: flags after '--' are no longer treated as --version/-v (ai -- --version is a prompt).
New regression tests for deferred migration, --help write-freedom and --/version parsing. - ([bf39624](https://github.com/belingud/yaicli/commit/bf39624a1e1572df14bbde7aaf46c8d98f626e9e)) - Belingud
- fix(agent): implement tool-output paging and harden shell env/spill handling

D6: fs_read_file gains optional offset/limit (characters, 0 = start/no limit) with per-file paging metadata (total_chars/returned_chars/truncated), so the truncation marker and docs that point the model at fs_read_file(offset/limit) for spilled tool output are truthful; legacy single-string/tuple inputs and the existing single/multi-file JSON shapes stay compatible.
--cwd now wins over a stale exported YAI_WORKSPACE_ROOT: shell guardrail config is exported from cfg unconditionally (empty values skipped), matching entry._apply_cwd.
Spill files for full tool outputs are created with 0600 permissions (best effort).
Docs: context-limits paging table/semantics. Tests: schema contracts (OpenAI/Anthropic/Gemini), paging/edge cases, end-to-end tool-call paging, env precedence and spill mode. - ([f19cac6](https://github.com/belingud/yaicli/commit/f19cac6d25211264cc45b8b556fbf6606419d814)) - Belingud
- fix(permissions): block path-glob traversal and shell-syntax rule bypasses

D4: path_glob candidates are derived only from normalized paths (workspace-resolved with strict=False); the raw '..'-containing string is never a candidate and workspace-relative candidates that escape the workspace are rejected, so a rule like allowed/* can no longer be bypassed with allowed/../../victim.txt. Legitimate relative/absolute matches and the every-path-argument-must-match semantics are preserved.
D5: argv_prefix rules only match a single simple command; the raw command is rejected when it contains shell control/expansion syntax (; | & < > backtick $( ${ <( >( CR/LF), so 'git status $(touch /tmp/x)' or piped/backtick variants require normal confirmation.
17 new regression tests (traversal/absolute/symlink escapes, parametrized control/substitution cases, legit plain args). - ([4735f3d](https://github.com/belingud/yaicli/commit/4735f3d267979e54246f54b552acf8a468bc252f)) - Belingud
- fix(cli): keep machine-readable stdout clean in headless modes

D1/D2: re-point both the LLM client and its provider at the stderr console in machine-output mode, so provider verbose dumps ('Messages:', tools JSON) and API error bodies ('Error Response: {...}') can no longer corrupt --json/stream-json stdout; client/provider construction warnings are redirected to stderr as well.
D3: compute headless intent in the CLI constructor (new defaulted print_mode/output_format/quiet kwargs) before the console, printer, client and prompt_toolkit session are created, so '-p --json' on a TTY never builds a PromptSession nor prints verbose config to stdout; entry.main passes the flags.
D8: move the Gemini/MCP '@Function call'/'@MCP call' debug prints to stderr and drop ANSI escapes.
Regression tests: polluting provider/client consoles under json/stream-json/--verbose, construction redirect, simulated-TTY constructor behaviour. - ([5fd62bc](https://github.com/belingud/yaicli/commit/5fd62bc9f3c4305c004172b078b75d6bf5caaf13)) - Belingud

### 📚 Documentation

- docs(changelog,spec): record v0.19 verification fixes

Regenerate the v0.19.0 changelog section with the four post-verification fix commits (headless stdout purity, permission-rule hardening, tool-output paging/env/spill handling, write-free config + environment-safe tests) and update the py-layer specs for the new contracts: CLI headless constructor intent + provider console sync, fs_read_file paging/spill mode/cfg-to-env shell precedence, deferred legacy-config key migration, and setting test credentials before importing yaicli. - ([1868067](https://github.com/belingud/yaicli/commit/18680675495e8b528f0c5ed3516d7745211b0d88)) - Belingud
- docs: restore "Your AI assistant in command line" positioning

Revert the first-screen positioning copy to the v0.18 assistant wording kept by the project: README title/intro/footer, docs index title/intro, the PyPI description (A simple CLI tool to interact with LLM) and mkdocs site_description (An advanced CLI tool for interacting with AI models). The v0.19 functional documentation is unchanged and still shipped: headless/scripting, permissions, context & limits, upgrade pages, quick start, and the measured lightweight table. - ([bc8d7fb](https://github.com/belingud/yaicli/commit/bc8d7fb90953c3bb992c25933ad2de49f7ddb2d5)) - Belingud
- docs: reposition YAICLI as a lightweight agent and document v0.19

Rewrite README/docs index around the agent-first, lightweight-first positioning; add a 3-step quick start and the measured footprint table (with the sandbox measurement caveat). New pages: usage/headless (stdout/stderr contract, JSON/NDJSON, exit codes), usage/permissions (risk classes, rules v2, audit, /permissions), usage/context-limits (truncation, budget, /context, /compact), advanced/upgrade (v0.19 changes, reinstall, XDG config dirs). Move the 30+ provider matrix to a Compatibility section and sync mkdocs nav. - ([dbd0a0b](https://github.com/belingud/yaicli/commit/dbd0a0b4a95dd30e15b54484721705baa4153a7c)) - Belingud
- docs(trellis): sync release spec with v0.18.0 release flow - ([84d9a13](https://github.com/belingud/yaicli/commit/84d9a13c3c2e72a8a6728ec789971f4279b35960)) - Belingud
- docs: update CHANGELOG for v0.18.0 release - ([7e947dd](https://github.com/belingud/yaicli/commit/7e947dde8d7d0c73cba44d1e0486a3a0e61cea30)) - Belingud

### ⚙️ Miscellaneous Tasks

- chore: record journal - ([2720fef](https://github.com/belingud/yaicli/commit/2720fef5bb73f8ea410633ca06bc9b9e49bba8f0)) - Belingud
- chore(release): sync uv.lock with v0.19.0

Refresh the editable package version recorded in uv.lock (0.18.0 -> 0.19.0) after the release bump; no dependency changes. - ([42643ea](https://github.com/belingud/yaicli/commit/42643ea97b9ce55389364866258b0a03a247c829)) - Belingud
- chore: record journal - ([3d0b28e](https://github.com/belingud/yaicli/commit/3d0b28ebafdb77e95e019863498ad0fa0fea6502)) - Belingud
- chore(task): archive 11-04-v019-lightweight-agent - ([a5b7d84](https://github.com/belingud/yaicli/commit/a5b7d8438f7f08a00301efb9be6988c7d87e9bb0)) - Belingud
- chore(trellis): record v0.19 lightweight-agent task and refresh specs

Add the v0.19.0 PRD/design/implement plan-of-record and update the py-layer specs for the new behavior: builtin direct-load + manifest, headless/exit-code contract, lazy write-free config/role/chat startup, error taxonomy/retries, context budget/truncation, risk-aware permissions and audit, and the new module map. - ([b928de8](https://github.com/belingud/yaicli/commit/b928de8510ef5dc45a2038f8817f77750272a4b7)) - Belingud
- chore(release): v0.19.0

Bump to 0.19.0 and point ai/yaicli console scripts at yaicli._faststart:main; update the PyPI description to 'A lightweight agent in your terminal'. The static __version__ in yaicli/__init__.py is now kept in sync with pyproject.toml by bump2version. - ([e9eb123](https://github.com/belingud/yaicli/commit/e9eb1238b2562478edd6901f339db6d7d4f5c214)) - Belingud
- chore: refresh uv.lock for v0.18.0 release - ([b7b868f](https://github.com/belingud/yaicli/commit/b7b868fc2359712c7d042cf4cc7999897b9d2d9e)) - Belingud

---
## [0.18.0](https://github.com/belingud/yaicli/compare/v0.17.0..v0.18.0) - 2026-11-02

### ⛰️  Features

- feat(functions): read multiple files in a single fs_read_file call

Advertise fs_read_file's file_paths as a JSON array instead of
Union[str, List[str]], so OpenAI/Anthropic schemas no longer emit anyOf
and Gemini's callable-derived declaration becomes ARRAY/STRING instead of
an invalid OBJECT + any_of. execute() keeps accepting a single path
string (and tuples) for backward compatibility and returns an in-band
JSON error for other argument types.

Add schema-contract, end-to-end tool-call, Gemini regression and
compatibility tests, and document batch reads in README and docs. - ([0d2d943](https://github.com/belingud/yaicli/commit/0d2d943385d1cdf3f88bae4441c1ab27d9a5ad6a)) - Belingud

### 🐛 Bug Fixes

- fix(tools): harden fetch_webpage redirect handling - ([cfddf81](https://github.com/belingud/yaicli/commit/cfddf8169c8db4e09171edc7174197d5425a6e63)) - Belingud
- fix(chat): keep old session until replacement is written - ([ee0c125](https://github.com/belingud/yaicli/commit/ee0c125ec52cdf40036e169dd06c9c1d202060c2)) - Belingud
- fix(render): escape role names and prompts in role command output - ([a4258e6](https://github.com/belingud/yaicli/commit/a4258e63024f9e540f02f61216f7031e06a6fd0e)) - Belingud
- fix(gemini): group parallel tool responses into one function_response turn - ([fde4264](https://github.com/belingud/yaicli/commit/fde4264a16e4c583a0e2b68660ff555ff3556775)) - Belingud
- fix(tools): reject CGNAT/shared address space in fetch_webpage SSRF guard - ([a4b7fea](https://github.com/belingud/yaicli/commit/a4b7feae6f885688ea4fe7ddf15222f42fc70f34)) - Belingud
- fix(tools): block SSRF in fetch_webpage with URL validation and redirect checks - ([a437dc9](https://github.com/belingud/yaicli/commit/a437dc9bef88f2cc5199e762c03e39fb835dd6a5)) - Belingud
- fix(tools): never disable TLS verification on retry in fetch_webpage - ([451d878](https://github.com/belingud/yaicli/commit/451d878c389a23d055151a1f1b36b16ae4489a4a)) - Belingud
- fix(render): never interpret untrusted text as Rich markup - ([159b8e0](https://github.com/belingud/yaicli/commit/159b8e090e74fc13834a3e539a8132e4c5f99795)) - Belingud
- fix(cli): exit non-zero on handled failures - ([f344a93](https://github.com/belingud/yaicli/commit/f344a9370f0ece0a704ab5fe4e974fc7758dd2a9)) - Belingud
- fix(chat): persist full message fields in saved sessions - ([5a04fa7](https://github.com/belingud/yaicli/commit/5a04fa72de676d12dbc982c9d67979356d274709)) - Belingud
- fix(providers): support parallel tool calls in OpenAI-compatible providers - ([58d11e6](https://github.com/belingud/yaicli/commit/58d11e61cae5b51bde44a5c8429f6f4bae387a12)) - Belingud
- fix(gemini): send tool results as function_response and stop resending last turn - ([34d4139](https://github.com/belingud/yaicli/commit/34d4139d0d5af0c74f55d7fdb9bae2acc5ab4e6b)) - Belingud
- fix(providers): tolerate missing reasoning_content in ChatGLM/HuggingFace responses - ([1b59b9a](https://github.com/belingud/yaicli/commit/1b59b9abef5f2efe507fa6a28c62f714a4f53490)) - Belingud
- fix(functions): keep permission checks before atomic fs_edit_file write - ([7f0d414](https://github.com/belingud/yaicli/commit/7f0d4140ba73e74b25bd7f6d1cd8fc0685aef86d)) - Belingud
- fix(functions): prevent fs_edit_file data loss on invalid replace edits - ([215688e](https://github.com/belingud/yaicli/commit/215688ef4738cacb37ea2242d9443b8621a70911)) - Belingud
- fix(functions): array-first fs_read_image schema

Mirror the fs_read_file fix: advertise image_paths as List[str] so OpenAI,
Anthropic and Gemini no longer receive an anyOf/OBJECT+any_of declaration;
execute() normalizes legacy str/tuple input and returns in-band errors for
other types. - ([92a4d05](https://github.com/belingud/yaicli/commit/92a4d0528a1c27b0b1029d029c7acd9608848b29)) - Belingud
- fix(cli): send a minimal prompt for image-only invocations

`ai --image photo.jpg` now sends "Describe the image." (plural for several
images) instead of aborting in CLI.run() with an empty prompt. - ([c6df177](https://github.com/belingud/yaicli/commit/c6df1773d23974f1a1f926f354d43c50b73a5b0b)) - Belingud
- fix(context): replace '[' sentinel with structured FileReadResult

_read_file() now returns FileReadResult(content, error) instead of magic
strings, so real text starting with '[' is included again in @refs and
directory context; read failures are warned about and skipped. - ([8703514](https://github.com/belingud/yaicli/commit/8703514d239faca1a78cd25cacd1a202ebf7dcdc)) - Belingud
- fix(cli): wire MAX_HISTORY and ROLE_MODIFY_WARNING

- prompt history now uses cfg["MAX_HISTORY"] instead of INTERACTIVE_ROUND
- MAX_HISTORY=0 disables history saving as documented
- warn when a built-in role is created/overwritten or deleted, gated by
  ROLE_MODIFY_WARNING
- remove the broken, unused RoleManager.print_roles() - ([defdf80](https://github.com/belingud/yaicli/commit/defdf80d5d26ad2e72e49bf5164cd8b985779291)) - Belingud
- fix(config): parse default config on first run and read YAI_PROVIDER

- add PROVIDER to DEFAULT_CONFIG_MAP with the YAI_PROVIDER env key
- parse DEFAULT_CONFIG_INI after writing it on a first run instead of
  returning early, so PROVIDER and friends are present immediately
- treat empty file/env values as unset and fall back to the typed map
  default (EXTRA_HEADERS/EXTRA_BODY become dicts, REASONING_EFFORT None)
- drop the unused const.CODE_MODE constant - ([097b6b4](https://github.com/belingud/yaicli/commit/097b6b415b9156c4ad9c0753e78cca4dcf052a56)) - Belingud

### 📚 Documentation

- docs(changelog): record unreleased changes since v0.17.0 and sync docs page - ([714b839](https://github.com/belingud/yaicli/commit/714b839f602a2f6483503f516cf3ca6fda7732f5)) - Belingud
- docs(dev): fill developer guides, fix navigation and spec drift - ([bee2c03](https://github.com/belingud/yaicli/commit/bee2c0332466688d149028305fa161ac198cff97)) - Belingud
- docs: fix provider/config examples and defaults drift - ([c715832](https://github.com/belingud/yaicli/commit/c715832f408ea7166ebe3807d637875c92ba23b2)) - Belingud
- docs: document post-P0 behaviour (session format, exit codes, fetch/fs_edit safety) - ([491369c](https://github.com/belingud/yaicli/commit/491369c1ea6d8aa055dab3a59ac4ad4ec6b38fa7)) - Belingud
- docs(functions): add complete function install/update guide - ([bdb8784](https://github.com/belingud/yaicli/commit/bdb8784680c57e692b21acfd6af0c9905a2b842c)) - Belingud
- docs: document image-only prompts and multi-image reads

- note the minimal prompt used when --image is passed without a prompt
- document the fs_read_image image_paths list contract - ([37d46a7](https://github.com/belingud/yaicli/commit/37d46a7dba202f8054563ef0447d445fec99a5ce)) - Belingud
- docs: document tool execution confirmation for v0.17.0 - ([530c774](https://github.com/belingud/yaicli/commit/530c77440d4723337c11d33d4765e63259804e94)) - Belingud
- docs: update CHANGELOG for v0.17.0 release - ([9273693](https://github.com/belingud/yaicli/commit/92736937dc1855d2de54a485e4572845fdfdf238)) - Belingud

### ⚙️ Miscellaneous Tasks

- chore(task): archive 11-01-fix-bootstrap-known-defects - ([a191828](https://github.com/belingud/yaicli/commit/a191828cd13f45370820a7b594ce7bcc50c8d456)) - Belingud
- chore: record journal - ([0949f40](https://github.com/belingud/yaicli/commit/0949f40b436b2beb1cc3a549b7f69f5f6d892414)) - Belingud
- chore(trellis): record fixed bootstrap defects in spec and task

- update py/ specs to the fixed behaviour (first-run config, typed
  defaults, MAX_HISTORY/ROLE_MODIFY_WARNING, image-only prompt,
  FileReadResult context reads, fs_read_image array schema)
- mark the bootstrap PRD's known-defect list as fixed with commit refs
- add the 11-01-fix-bootstrap-known-defects task artifacts - ([2011b37](https://github.com/belingud/yaicli/commit/2011b37c8cb7058e088e6765e7114585d716e1f1)) - Belingud
- chore: record journal - ([331f4a8](https://github.com/belingud/yaicli/commit/331f4a8be8a9fc860b8a4504032faa06572bb526)) - Belingud
- chore(task): archive 00-bootstrap-guidelines - ([9a61200](https://github.com/belingud/yaicli/commit/9a6120064a7da293bda48a61c00cf406bdfcb717)) - Belingud
- chore(trellis): install Trellis workflow and bootstrap project spec

Add the Trellis AI development workflow for Claude Code and DeepSeek
Harness (dsh): .trellis/ (workflow, scripts, tasks, workspace, spec),
.agents/skills/ shared skill catalog, .dsh/ entry skills, the Claude Code
surface (.claude/ hooks, agents, commands, skills, settings.json), the
union-merge .gitattributes rule, and the managed Trellis block in
CLAUDE.md (AGENTS.md symlink follows it).

Complete the 00-bootstrap-guidelines task: reshape the generated
backend/web spec scaffold into layers that match the repository - py/
(architecture, providers, function calling/tools, CLI/rendering,
config/context, quality) and repo/ (conventions, build/CI/release) - with
every rule grounded in real source files, tests, and commits. The spec
records current defects found while writing (first-run PROVIDER KeyError,
unused CODE_MODE, dead MAX_HISTORY/ROLE_MODIFY_WARNING, --image-only
abort, context "[" sentinel, role.print_roles, fs_read_image Union debt).

Verified: no placeholders, index<->file coverage, relative links, and
`get_context.py --mode packages` -> py, repo; independently reviewed by a
read-only verifier. - ([cb6abd8](https://github.com/belingud/yaicli/commit/cb6abd8050d415e9d8c136e58289b09a1cd6a690)) - Belingud

---
## [0.17.0](https://github.com/belingud/yaicli/compare/v0.16.0..v0.17.0) - 2026-06-23

### ⛰️  Features

- feat!: confirm tool calls before execution

Add a confirmation gate before each tool/function call with four outcomes:
allow once, allow for the session, allow permanently, or deny. Approvals
are keyed by tool name (MCP prefix preserved); permanent approvals persist
to ~/.config/yaicli/tool_permissions.json via an atomic write. Denied calls
return a matched tool result so the provider request stays valid, and
non-interactive sessions deny unapproved tools instead of blocking.

Also stream reasoning as append-only text rather than re-rendering it in the
live region, fixing duplicated 'Thinking:' frames after large tool output.

BREAKING CHANGE: tool calls now require confirmation by default. Set
TOOL_CONFIRM=false (env YAI_TOOL_CONFIRM=false) to restore silent execution. - ([7cc64f0](https://github.com/belingud/yaicli/commit/7cc64f02978b50594fda319f4648f725c4d88094)) - Belingud

### 🐛 Bug Fixes

- fix: drop api_key for Cohere
  Bedrock/Sagemaker clients

Bedrock and Sagemaker authenticate via AWS credentials; the Cohere api_key injected by the base initializer is not a valid argument for those
  clients and caused client creation to fail. - ([9b77aa1](https://github.com/belingud/yaicli/commit/9b77aa103cd3a351e7dc4004e33673d11e6a979e)) - Belingud

### 📚 Documentation

- docs: update CHANGELOG for v0.16.0 release - ([1a0dfd6](https://github.com/belingud/yaicli/commit/1a0dfd62992c5bcd3e10c01f3c8e882abba95f7b)) - Belingud

### 🧪 Testing

- test: expand coverage across CLI, context, tools, and providers

Add tests for functions init, render, and tools init modules, and extend
anthropic, longcat, chat manage, CLI, command handler, context, fetch
webpage, and fs file operation test suites. - ([8fe3871](https://github.com/belingud/yaicli/commit/8fe387105c33e8fec3adfc939168fa87c87c1105)) - Belingud
- test: expand provider test coverage

Add tests for openai-compatible, sambanova, and targon providers, and extend ai21, cohere, minimax, and simple provider test suites. - ([14b38cb](https://github.com/belingud/yaicli/commit/14b38cb3e30597e602bfdd0eb3f49815c7734fe0)) - Belingud


---
## [Unreleased]

### ⛰️  Features

- feat!: confirm tool/function calls before execution — allow once, allow for the session, allow permanently, or deny. **BREAKING:** tool calls now require confirmation by default; set `TOOL_CONFIRM=false` (env `YAI_TOOL_CONFIRM=false`) to restore the previous silent execution. Permanent approvals are stored per tool name in `~/.config/yaicli/tool_permissions.json`.


---
## [0.16.0](https://github.com/belingud/yaicli/compare/v0.15.2..v0.16.0) - 2026-05-10

### ⛰️  Features

- feat: support DeepSeek thinking mode - ([2980316](https://github.com/belingud/yaicli/commit/2980316e9ee2a0a9521113c07d3742ffdc03bb99)) - Belingud

### 📚 Documentation

- docs: update changelog for v0.5.2 release - ([4e96660](https://github.com/belingud/yaicli/commit/4e96660fc222e9a71281125c0a311ac91396b276)) - Belingud


---
## [0.15.2](https://github.com/belingud/yaicli/compare/v0.15.1..v0.15.2) - 2026-04-28

### 🐛 Bug Fixes

- fix: add tool_policy parameter to completion params - ([a47d619](https://github.com/belingud/yaicli/commit/a47d619ee7dfa5de2e4e2e30ab74cc385149608f)) - Belingud
- fix: fall back to httpx when trafilatura extraction fails - ([1bdd254](https://github.com/belingud/yaicli/commit/1bdd2549b3ec86ecb0aec16b922fbbac2de629cd)) - Belingud


---
## [0.15.2](https://github.com/belingud/yaicli/compare/v0.15.1..v0.15.2) - 2026-04-28

### 🐛 Bug Fixes

- fix: add tool_policy parameter to completion params - ([a47d619](https://github.com/belingud/yaicli/commit/a47d619ee7dfa5de2e4e2e30ab74cc385149608f)) - Belingud
- fix: fall back to httpx when trafilatura extraction fails - ([1bdd254](https://github.com/belingud/yaicli/commit/1bdd2549b3ec86ecb0aec16b922fbbac2de629cd)) - Belingud


---
## [0.15.0](https://github.com/belingud/yaicli/compare/v0.14.2..v0.15.0) - 2026-03-24

### ⛰️  Features

- feat: add -v/--version flag to show version and exit - ([bae66c2](https://github.com/belingud/yaicli/commit/bae66c2cd4e59b8c82158adffa742b7601958ebf)) - Belingud


---
## [0.10.0](https://github.com/belingud/yaicli/compare/v0.9.0..v0.10.0) - 2026-01-20

### ⛰️  Features

- add longcat provider support and improve anthropic tool call handling - ([6ca2e8e](https://github.com/belingud/yaicli/commit/6ca2e8e35b28855c884a1d99f602be258ca16bba)) - Belingud
- add default empty string to command handlers - ([0c6ebed](https://github.com/belingud/yaicli/commit/0c6ebedeef0a40cfccc35659e74a4b48ea45fc13)) - Belingud
- update file/dir context help text - ([698fd61](https://github.com/belingud/yaicli/commit/698fd61b93572b5bb6873052cebfe170d661d99d)) - Belingud
- add support for @-prefixed paths in AtPathCompleter - ([1b43712](https://github.com/belingud/yaicli/commit/1b43712e5b4fe447b96e490cab63e7d6321d62b5)) - Belingud

### 🐛 Bug Fixes

- compatible with /context add - ([e60333d](https://github.com/belingud/yaicli/commit/e60333decb220d63914e9ceb2cbe4e353c989b6b)) - Belingud

### 📚 Documentation

- add LongCat provider documentation - ([a3e4a79](https://github.com/belingud/yaicli/commit/a3e4a796ffdb9150f94c45fd6f4568b519b88ebc)) - Belingud
- add context management and path completion features - ([1bc7c74](https://github.com/belingud/yaicli/commit/1bc7c74136fe09cab8eb0775752cd4a604941ba7)) - Belingud
- add file context management feature documentation - ([4f53c73](https://github.com/belingud/yaicli/commit/4f53c739b3769270b37892389be602631f05ab22)) - Belingud
- add changelog entries for v0.9.0 and v0.8.12 - ([8fbfb27](https://github.com/belingud/yaicli/commit/8fbfb27eb36398995b7fecb9ad2cad4caaf85ce7)) - Belingud

### 🧪 Testing

- add LongCat provider tests and improve Anthropic provider testing - ([5b950db](https://github.com/belingud/yaicli/commit/5b950db7b16d4ba5d08eb734161edd1131f42eee)) - Belingud
- add message filtering and context management tests - ([43b226d](https://github.com/belingud/yaicli/commit/43b226dfd5702666fccdcd24b6ca9b593377fd6e)) - Belingud

### ⚙️ Miscellaneous Tasks

- update uv.lock - ([5fa5af4](https://github.com/belingud/yaicli/commit/5fa5af479810e3164fce82b3aad866901dc48f8c)) - Belingud


---
## [0.9.0](https://github.com/belingud/yaicli/compare/v0.8.12..v0.9.0) - 2026-01-10

### ⛰️  Features

- add EXCLUDE_PARAMS configuration option - ([d36ce77](https://github.com/belingud/yaicli/commit/d36ce774406b37cef7767a70329df4185256fa51)) - Belingud

### 📚 Documentation

- add implementation plan for EXCLUDE_PARAMS feature - ([ac3f743](https://github.com/belingud/yaicli/commit/ac3f743220f9ed8f602510ef6748473ec639e84c)) - Belingud
- add changelog entries for v0.8.12 and v0.8.11 - ([94c09e6](https://github.com/belingud/yaicli/commit/94c09e6f766efb31a61867b1869bd2d6f3b80a54)) - Belingud

### 🎨 Styling

- format py files - ([6a6cea8](https://github.com/belingud/yaicli/commit/6a6cea8467cb9a95e5e8fe1a70d41c8741e6384d)) - Belingud

### ⚙️ Miscellaneous Tasks

- update uv sync command to include all groups and extras - ([c025d72](https://github.com/belingud/yaicli/commit/c025d72e87bd9bf7c3ab63112a359e1dce1d1b24)) - Belingud


---
## [0.8.12](https://github.com/belingud/yaicli/compare/v0.8.11..v0.8.12) - 2026-01-08

### ⛰️  Features

- **(fetch_webpage)** enhance webpage fetching with retries and trafilatura support - ([cf64899](https://github.com/belingud/yaicli/commit/cf64899af3e87be038767381a81c8d8153025736)) - Belingud
- **(filesystem)** add builtin filesystem functions for CLI - ([55a7039](https://github.com/belingud/yaicli/commit/55a7039dde531de4277eed80f78e4bc9ff86cb70)) - Belingud
- add verbose logging for raw tool call names - ([fe1e1a0](https://github.com/belingud/yaicli/commit/fe1e1a0e4bcd0f6a189d10d7598e354921beaa85)) - Belingud

### 🐛 Bug Fixes

- improve security checks for file operations and refactor path handling - ([ca0ae47](https://github.com/belingud/yaicli/commit/ca0ae47d85d1c1bfe06406e76969af1e73f5c7f6)) - Belingud

### 📚 Documentation

- add changelog entry for v0.8.11 - ([4077b27](https://github.com/belingud/yaicli/commit/4077b2735f3a76e639e96634f21853c897093fd8)) - Belingud

### 🧪 Testing

- remove unused imports from test files - ([f736c04](https://github.com/belingud/yaicli/commit/f736c043e3febdf18c05916ca888c346db936efd)) - Belingud
- add test files for filesystem operations - ([aec5980](https://github.com/belingud/yaicli/commit/aec5980e2b9089f298aea26a2bb89116df5370a6)) - Belingud


---
## [0.8.11](https://github.com/belingud/yaicli/compare/v0.8.10..v0.8.11) - 2025-08-03

### 📚 Documentation

- update changelog for v0.8.10 release - ([c212daa](https://github.com/belingud/yaicli/commit/c212daad1807648ce5f96b576dbd336ee24c278a)) - Belingud


---
## [0.8.10](https://github.com/belingud/yaicli/compare/v0.8.9..v0.8.10) - 2025-07-24

### ⛰️  Features

- update wrap_gemini_function to add gemini func call log - ([f34d322](https://github.com/belingud/yaicli/commit/f34d32277638e272cd4b1909fa0f5540029736b3)) - Belingud

### 📚 Documentation

- update changelog for v0.8.9 release - ([73e9ab8](https://github.com/belingud/yaicli/commit/73e9ab8c835c9d227ec824af33bd2710d8812088)) - Belingud


---
## [0.8.9](https://github.com/belingud/yaicli/compare/v0.8.8..v0.8.9) - 2025-07-22

### ⛰️  Features

- add OpenAICampatibleProvider and update Config imports - ([72f8d91](https://github.com/belingud/yaicli/commit/72f8d914ba19a3818520542c7f43da4310b59de6)) - Belingud

### 📚 Documentation

- update changelog for v0.8.8 release - ([063faf7](https://github.com/belingud/yaicli/commit/063faf7cddeca9709924b3ac6e8791c6b83cd26d)) - Belingud

### 🧪 Testing

- add openai-compatible provider to test cases - ([4f75278](https://github.com/belingud/yaicli/commit/4f75278faf06f2ad83206707996a584210f0590c)) - Belingud

### ⚙️ Miscellaneous Tasks

- update uv lock - ([e339adf](https://github.com/belingud/yaicli/commit/e339adfae55d0834082dde3ae0be94ca6f17394b)) - Belingud


---
## [0.8.8](https://github.com/belingud/yaicli/compare/v0.8.7..v0.8.8) - 2025-07-21

### 🐛 Bug Fixes

- remove frequency_penalty from AnthropicProvider - ([6d21e6a](https://github.com/belingud/yaicli/commit/6d21e6ad8a17bda94faac6a38ebea84dc5485c14)) - Belingud

### 📚 Documentation

- update changelog for v0.8.7 release - ([b788c6c](https://github.com/belingud/yaicli/commit/b788c6c1a3bac58fb68e22ba1393c9519302357b)) - Belingud


---
## [0.8.7](https://github.com/belingud/yaicli/compare/v0.8.6..v0.8.7) - 2025-07-20

### ⛰️  Features

- add error handling for first chunk in OpenAIProvider - ([c6e3eae](https://github.com/belingud/yaicli/commit/c6e3eae356d69b71926c843269ddb26c2a2afd49)) - Belingud

### 📚 Documentation

- update changelog for v0.8.6 release - ([1104d0f](https://github.com/belingud/yaicli/commit/1104d0fbfac7d7b3d74c69dce8500dd901fdf30c)) - Belingud


---
## [0.8.6](https://github.com/belingud/yaicli/compare/v0.8.5..v0.8.6) - 2025-07-19

### 🚜 Refactor

- remove frequency_penalty for cerebras and add get_tools method - ([c6a16a5](https://github.com/belingud/yaicli/commit/c6a16a5739c71b8768102f4655aa0618f83d546d)) - Belingud

### 📚 Documentation

- update changelog for v0.8.5 release - ([a4e358b](https://github.com/belingud/yaicli/commit/a4e358b32aa4837c8ec6e72b04ad9e0bfd8601a2)) - Belingud


---
## [0.8.5](https://github.com/belingud/yaicli/compare/v0.8.4..v0.8.5) - 2025-07-17

### ⛰️  Features

- add FireworksProvider and frequency penalty support - ([a316006](https://github.com/belingud/yaicli/commit/a3160067410a07b07d75de969dd294a61c089254)) - Belingud

### 📚 Documentation

- add frequency penalty configuration to README - ([8fe3836](https://github.com/belingud/yaicli/commit/8fe3836f027853b9b8048de2940de5c8d34c2800)) - Belingud
- update changelog for v0.8.4 release - ([afd4f95](https://github.com/belingud/yaicli/commit/afd4f950c20bed8ab3bd4d8159e22b18e8d477a1)) - Belingud

### 🧪 Testing

- add frequency_penalty to llm provider tests - ([8f4da43](https://github.com/belingud/yaicli/commit/8f4da43d067ef819ad873e3339dde9436c226a18)) - Belingud
- add Fireworks provider tests - ([cfc189f](https://github.com/belingud/yaicli/commit/cfc189fb9423049ddfe00588a127b3742cecefc1)) - Belingud

### ⚙️ Miscellaneous Tasks

- add fireworks-ai dependency - ([0ff81af](https://github.com/belingud/yaicli/commit/0ff81af3a5723f94f4c4a86a00310eb35b51701f)) - Belingud


---
## [0.8.4](https://github.com/belingud/yaicli/compare/v0.8.3..v0.8.4) - 2025-07-17

### 📚 Documentation

- add Fireworks to README.md - ([ba80dbc](https://github.com/belingud/yaicli/commit/ba80dbcc8233f4382eec8becd1c7a87a6f38d583)) - Belingud
- add Fireworks AI provider documentation - ([27df748](https://github.com/belingud/yaicli/commit/27df7486fd352cf45b22b4fafc35fdc8e3d1c72c)) - Belingud
- update changelog for v0.8.3 release - ([4851cd0](https://github.com/belingud/yaicli/commit/4851cd0f20643113522cc7266d7271164d61acc6)) - Belingud


---
## [0.8.3](https://github.com/belingud/yaicli/compare/v0.8.2..v0.8.3) - 2025-07-16

### ⛰️  Features

- add new configuration options and refactor CLI options - ([a52ee92](https://github.com/belingud/yaicli/commit/a52ee9211a28c09f6bf2eef88edb113236beef55)) - Belingud

### 📚 Documentation

- add `MAX_TOOL_CALL_DEPTH` configuration option - ([c1cf420](https://github.com/belingud/yaicli/commit/c1cf420777abdbb9a7156f08fecda23a454fe421)) - Belingud
- update changelog for v0.8.2 release - ([5f27d5d](https://github.com/belingud/yaicli/commit/5f27d5d58cdffa4adaefffa64d924c42a2d12c46)) - Belingud

### 🧪 Testing

- update test cases for AnthropicProvider and CLI - ([367ea89](https://github.com/belingud/yaicli/commit/367ea891e96a95fa8474fb569d64ca862cd089a6)) - Belingud


---
## [0.8.2](https://github.com/belingud/yaicli/compare/v0.8.1..v0.8.2) - 2025-07-15

### 🐛 Bug Fixes

- add tool result handling in AnthropicProvider and update tool schema - ([8e27965](https://github.com/belingud/yaicli/commit/8e2796502c16435b1c60779801dd2d85e7e321b5)) - Belingud

### 📚 Documentation

- update changelog for v0.8.1 release - ([1c546cd](https://github.com/belingud/yaicli/commit/1c546cd318a918716a98ee95c6a6192f4bb858f7)) - Belingud

### 🧪 Testing

- add test for converting messages with tool results - ([3b04a71](https://github.com/belingud/yaicli/commit/3b04a71640fe721f50e33e53230cdee11f1d36b5)) - Belingud

### ⚙️ Miscellaneous Tasks

- update deploy-docs.yml for better readability - ([17ad8eb](https://github.com/belingud/yaicli/commit/17ad8eb32bb5d5781a9beb15713d4261308e6028)) - Belingud
- add GitHub Actions workflow for deploying MkDocs - ([a653a29](https://github.com/belingud/yaicli/commit/a653a29c26bb4a1ca234102af1525b2b07eff50d)) - Belingud


---
## [0.8.1](https://github.com/belingud/yaicli/compare/v0.8.0..v0.8.1) - 2025-07-15

### 🚜 Refactor

- add conditional newline in tool call content - ([7bb167f](https://github.com/belingud/yaicli/commit/7bb167f6078d797bcfd4e3c069de9fcd5e2ce196)) - Belingud

### 📚 Documentation

- update documentation for providers - ([f36de06](https://github.com/belingud/yaicli/commit/f36de0692129ac941954b9aa839e39e23907c430)) - Belingud
- update changelog for v0.8.0 release - ([1cd2fc4](https://github.com/belingud/yaicli/commit/1cd2fc4148597755280511896abf2ab5ea71562b)) - Belingud


---
## [0.8.0](https://github.com/belingud/yaicli/compare/v0.7.17..v0.8.0) - 2025-07-14

**Disable time sleep in streaming response content from this version.**

### ⛰️  Features

- add run shell directly cmd in chat - ([126f5df](https://github.com/belingud/yaicli/commit/126f5dfc3c6bd6262672c5841cea81be1df1cf92)) - Belingud

### 🚜 Refactor

- improve chat history display and tool call handling - ([145fdc6](https://github.com/belingud/yaicli/commit/145fdc60ca8dd999d0de7b401b7a27ce4eafc4cd)) - Belingud

### 📚 Documentation

- add shell command execution feature to CLI and usage docs - ([fd22f9d](https://github.com/belingud/yaicli/commit/fd22f9d75bfa973ac05c8baf7a30a8e0f48b6445)) - Belingud
- update changelog for v0.7.17 release - ([f1165a6](https://github.com/belingud/yaicli/commit/f1165a673f15ee5d727b6f4b677d8c8e737bb2b2)) - Belingud

### 🧪 Testing

- update test case for run shell command - ([9a2f2b7](https://github.com/belingud/yaicli/commit/9a2f2b71df051d1f63172e558c1245e3816e86af)) - Belingud


---
## [0.7.17](https://github.com/belingud/yaicli/compare/v0.7.16..v0.7.17) - 2025-07-13

### ⛰️  Features

- add moonshot provider support - ([8109255](https://github.com/belingud/yaicli/commit/81092559488aebb09dadd714bb88f90e74417159)) - Belingud

### 📚 Documentation

- add more provider docs - ([30e981d](https://github.com/belingud/yaicli/commit/30e981d728c309fae1bc0b42c639d427fed73a96)) - Belingud
- update changelog for v0.7.16 release - ([e10b79a](https://github.com/belingud/yaicli/commit/e10b79a0968fb068b83eb821da197daa2a0205f7)) - Belingud

### ⚙️ Miscellaneous Tasks

- update uv lock - ([794305a](https://github.com/belingud/yaicli/commit/794305ab264602b2ec6811eca342d5dd45028d7c)) - Belingud


---
## [0.7.16](https://github.com/belingud/yaicli/compare/v0.7.15..v0.7.16) - 2025-07-12

### 🐛 Bug Fixes

- ensure live stop and remove update interval - ([f9bb0aa](https://github.com/belingud/yaicli/commit/f9bb0aa780ee66fa147f401c760a1beda7f674e0)) - Belingud

### 📚 Documentation

- add new release notes for v0.7.15 - ([a347b64](https://github.com/belingud/yaicli/commit/a347b64b35d2488ec0e4f304fbcf3178f2404c55)) - Belingud


---
## [0.7.15](https://github.com/belingud/yaicli/compare/v0.7.14..v0.7.15) - 2025-07-12

### ⛰️  Features

- enable openai azure provider and add docs - ([7be0da3](https://github.com/belingud/yaicli/commit/7be0da3523f44d8ad7296911b1c2a5897b868b7a)) - Belingud
- add openai azure provider support - ([6384d1f](https://github.com/belingud/yaicli/commit/6384d1fc99801c6035d981f82335e48898d3ffb5)) - Belingud

### 📚 Documentation

- update CHANGELOG with new release notes - ([a2aa596](https://github.com/belingud/yaicli/commit/a2aa596273f14c17b904c9704388f269403d6648)) - Belingud


---
## [0.7.14](https://github.com/belingud/yaicli/compare/v0.7.13..v0.7.14) - 2025-07-10

### ⛰️  Features

- add cerebras provider support - ([d6cc354](https://github.com/belingud/yaicli/commit/d6cc35480de2e939d08a0d8570b9ea4f3054d057)) - Belingud

### 📚 Documentation

- update CHANGELOG with new release notes - ([f4bd8d3](https://github.com/belingud/yaicli/commit/f4bd8d34cb4c08565b45a44cb1b7a3c0366e8328)) - Belingud


---
## [0.7.13](https://github.com/belingud/yaicli/compare/v0.7.12..v0.7.13) - 2025-07-09

### 🐛 Bug Fixes

- update APP_REFERER and improve type annotations in OpenAIProvider - ([a04a2c5](https://github.com/belingud/yaicli/commit/a04a2c51b040fdb842b488dc149240c286adccb6)) - Belingud

### 📚 Documentation

- update CHANGELOG with new release notes - ([b18aaea](https://github.com/belingud/yaicli/commit/b18aaeae8e1de14a9d5656cf6017e2265af088e9)) - Belingud

### ⚙️ Miscellaneous Tasks

- remove unused GitHub Actions workflow - ([87e802c](https://github.com/belingud/yaicli/commit/87e802c43dad6b2a3e455b520d19cd1603b86514)) - Belingud


---
## [0.7.12](https://github.com/belingud/yaicli/compare/v0.7.11..v0.7.12) - 2025-07-09

### 🐛 Bug Fixes

- Indent tool choice print statement - ([f70ba3a](https://github.com/belingud/yaicli/commit/f70ba3a04851b95ba8c7395ec7de67a2b33e09e9)) - Belingud

### 📚 Documentation

- update CHANGELOG with new release notes - ([c53150f](https://github.com/belingud/yaicli/commit/c53150f1fa841c2f283dba2453cde8ed915b868a)) - Belingud


---
## [0.7.11](https://github.com/belingud/yaicli/compare/v0.7.10..v0.7.11) - 2025-07-09

### 📚 Documentation

- update CHANGELOG with new release notes - ([2a1ea8c](https://github.com/belingud/yaicli/commit/2a1ea8c90d481ee5ce663ccbf87b928d649a7e85)) - Belingud

### ⚙️ Miscellaneous Tasks

- remove docs.yml workflow - ([b2e6aed](https://github.com/belingud/yaicli/commit/b2e6aed8e9e43c18a5cacdc2a9326068741ce6bb)) - Belingud
- remove google-cloud-aiplatform dependency - ([6118c85](https://github.com/belingud/yaicli/commit/6118c85f9bdc6cd130bbd07f38ac03f366b04466)) - Belingud


---
## [0.7.10](https://github.com/belingud/yaicli/compare/v0.7.9..v0.7.10) - 2025-07-09

### 📚 Documentation

- update provider documentation and navigation - ([bffb3c6](https://github.com/belingud/yaicli/commit/bffb3c6572cc185c73db4a5c93a7dab5747d100e)) - Belingud
- correct logo path in index.md - ([97b94cb](https://github.com/belingud/yaicli/commit/97b94cbc10253f0faf5ef80683c4b3e8d85e37b1)) - Belingud
- update function calling and MCP documentation - ([030129b](https://github.com/belingud/yaicli/commit/030129bc0bf08f3cb2ab3345bda43cf21ce6a19f)) - Belingud
- update CHANGELOG with new release notes - ([4845ca0](https://github.com/belingud/yaicli/commit/4845ca0b2e628c31bb9b9ec7d35e8196b9938469)) - Belingud
- add more doc files - ([8c5fffe](https://github.com/belingud/yaicli/commit/8c5fffee74cd893f0308c140332df9371f7a36c6)) - Belingud

### ⚙️ Miscellaneous Tasks

- add vertex support to anthropic dependency - ([80e8252](https://github.com/belingud/yaicli/commit/80e82525ada61cf3565125b3348efb53d240a124)) - Belingud
- add new dependencies for anthropic and google-cloud-aiplatform - ([9f9ceaf](https://github.com/belingud/yaicli/commit/9f9ceaf288ef0314157969bc771b9aabfad24575)) - Belingud
- add debug steps to docs.yml - ([1a7e4f1](https://github.com/belingud/yaicli/commit/1a7e4f1142487b4c355df48503e2c4e4c189370d)) - Belingud
- update GitHub Actions workflow for docs deployment - ([cb3af0f](https://github.com/belingud/yaicli/commit/cb3af0f9eeb28370af87c91b5bc3f25329ba4683)) - Belingud
- update docs.yml to trigger on master branch - ([6df9996](https://github.com/belingud/yaicli/commit/6df9996cc77a048e450ccff2d61565f090ea3c29)) - Belingud
- update GitHub Actions workflow and docs - ([f371d11](https://github.com/belingud/yaicli/commit/f371d1155070f1c86ab4211b33d6d02371db3b6f)) - Belingud
- update docs.yml to trigger on docs branch - ([d87644b](https://github.com/belingud/yaicli/commit/d87644bd4420d813ebe7db348a684bd30bfea41e)) - Belingud
- update GitHub Actions dependencies - ([60ab515](https://github.com/belingud/yaicli/commit/60ab515b785409b5813f2fe7fe13fe229dea8be1)) - Belingud
- add main branch to docs workflow and update dependencies - ([bc5e312](https://github.com/belingud/yaicli/commit/bc5e3127e20b079447f7c08ff187f76a2f2d21e0)) - Belingud
- add mkdocs workflow - ([f566602](https://github.com/belingud/yaicli/commit/f566602bb2f26862091902748c180b86ddc1a069)) - Belingud


---
## [0.7.9](https://github.com/belingud/yaicli/compare/v0.7.8..v0.7.9) - 2025-07-07

### ⛰️  Features

- add support for Anthropic, Anthropic Vertex and Anthropic Bedrock providers - ([88c879e](https://github.com/belingud/yaicli/commit/88c879e37fc3fcbe82a91349a9d0be7674f8bc13)) - Belingud

### 📚 Documentation

- add Anthropic/Claude provider details - ([3f95754](https://github.com/belingud/yaicli/commit/3f95754510add560e64f19236497470dc6b9a85b)) - Belingud
- update CHANGELOG with new release notes - ([f24a550](https://github.com/belingud/yaicli/commit/f24a550add43d2340172f1fd01dad69e1c2636e1)) - Belingud

### 🧪 Testing

- add tests for AnthropicProvider and setup test environment - ([5aa0986](https://github.com/belingud/yaicli/commit/5aa0986618444f95a1b9a69448f90bcac975ad4d)) - Belingud


---
## [0.7.8](https://github.com/belingud/yaicli/compare/v0.7.7..v0.7.8) - 2025-07-03

### 📚 Documentation

- update CHANGELOG with new release notes - ([78761d4](https://github.com/belingud/yaicli/commit/78761d48bd2ff612c32e92852d6d83c36cafcc97)) - Belingud

### ⚙️ Miscellaneous Tasks

- update fastmcp dependency to 2.10.1 - ([9fb6818](https://github.com/belingud/yaicli/commit/9fb681885abe52b8b0ead8fa621fefb31482162d)) - Belingud


---
## [0.7.7](https://github.com/belingud/yaicli/compare/v0.7.6..v0.7.7) - 2025-07-01

### ⛰️  Features

- add fetch_webpage buildin function - ([09ec366](https://github.com/belingud/yaicli/commit/09ec36645da0cd8fcfe59ab27c7646012f0aace9)) - Belingud

### 📚 Documentation

- update CHANGELOG with new release notes and documentation updates - ([2ff0056](https://github.com/belingud/yaicli/commit/2ff00568febcb4dcc149d280027e870693b803eb)) - Belingud


---
## [0.7.6](https://github.com/belingud/yaicli/compare/v0.7.5..v0.7.6) - 2025-07-01

### ⛰️  Features

- add default role configuration - ([91c72f0](https://github.com/belingud/yaicli/commit/91c72f0835bc3d68c14c5c3d45724536ffcc4905)) - Belingud

### 🚜 Refactor

- remove unused imports and trailing whitespace - ([cad95fe](https://github.com/belingud/yaicli/commit/cad95fed1a72d687a65e655b99dcbaaf8ccd77ac)) - Belingud

### 📚 Documentation

- add DEFAULT_ROLE to README.md - ([6308eea](https://github.com/belingud/yaicli/commit/6308eea1b7ced3aed51df5419c6fab838286ebfb)) - Belingud
- update README.md with improved descriptions and requirements - ([25e32bc](https://github.com/belingud/yaicli/commit/25e32bcbb2c98091c329792dd6a24b3e8bd776dd)) - Belingud
- update README with new provider and formatting - ([da056ca](https://github.com/belingud/yaicli/commit/da056ca8bf88a1e77ad9cd7b786ad7697d3e315b)) - Belingud
- update CHANGELOG with v0.7.5 release notes - ([566a85c](https://github.com/belingud/yaicli/commit/566a85c9c8b6791754a961bee1a335a2e3fd405f)) - Belingud


---
## [0.7.5](https://github.com/belingud/yaicli/compare/v0.7.4..v0.7.5) - 2025-07-01

### ⛰️  Features

- add get_weather buildin function - ([876efb7](https://github.com/belingud/yaicli/commit/876efb79856be4328c2fe8119ce696d9a17ccbc0)) - Belingud

### 📚 Documentation

- add Spark and Together to README - ([e26ea59](https://github.com/belingud/yaicli/commit/e26ea59f15abd20c5a190dd67e4b5d1f1a5b2d19)) - Belingud
- update CHANGELOG with v0.7.4 release notes - ([966e443](https://github.com/belingud/yaicli/commit/966e443465ea74dcc44626f88b2302c63e1e6582)) - Belingud

### ⚙️ Miscellaneous Tasks

- remove pydantic deprecation warnings - ([ce2c18c](https://github.com/belingud/yaicli/commit/ce2c18cb583816558df9b7e12e55c53c8f8412d3)) - Belingud
- add warnings import and filter deprecation warnings - ([7003144](https://github.com/belingud/yaicli/commit/700314496bd26c4927a86285cb12f3ce1ef58595)) - Belingud


---
## [0.7.4](https://github.com/belingud/yaicli/compare/v0.7.3..v0.7.4) - 2025-06-30

### 🐛 Bug Fixes

- handle LLM client creation errors gracefully - ([6c8cbed](https://github.com/belingud/yaicli/commit/6c8cbed702a93df53afdad04892c51b3c4873730)) - Belingud

### 📚 Documentation

- add MCP Calling documentation to README - ([70b5a86](https://github.com/belingud/yaicli/commit/70b5a8646fcc6002d9e0c72ec578c05c1d462291)) - Belingud
- update CHANGELOG.md for v0.7.3 release - ([ddae983](https://github.com/belingud/yaicli/commit/ddae983f072dafbd065e33085841f05d1cd7ace8)) - Belingud

### 🧪 Testing

- add Together provider tests and improve line formatting - ([560330e](https://github.com/belingud/yaicli/commit/560330e64083c50ac07e52b1c7e6d3dc9935fb94)) - Belingud


---
## [0.7.3](https://github.com/belingud/yaicli/compare/v0.7.2..v0.7.3) - 2025-06-29

### ⛰️  Features

- add bailian, bailian-intl, spark and nvida providers - ([106214b](https://github.com/belingud/yaicli/commit/106214b581c9eeda34494b8bb06f906ab59995e7)) - Belingud

### 📚 Documentation

- add documentation for new providers - ([5fd9662](https://github.com/belingud/yaicli/commit/5fd9662f7ebe1676865d61075dd5dc32f88a033c)) - Belingud
- update CHANGELOG.md for v0.7.2 release - ([44b8702](https://github.com/belingud/yaicli/commit/44b8702e092c7c8c4bec169048438807cc96963e)) - Belingud

### 🧪 Testing

- add new provider types to TestProviderFactory - ([dbf4572](https://github.com/belingud/yaicli/commit/dbf457245cec79347c8d5ef267749c44efe59941)) - Belingud
- add tests for Bailian, Mistral, Nvidia, and Spark providers - ([f75a7f6](https://github.com/belingud/yaicli/commit/f75a7f61a5b2ce0cc068ec37060ca7f125b241ce)) - Belingud


---
## [0.7.2](https://github.com/belingud/yaicli/compare/v0.7.1..v0.7.2) - 2025-06-28

### ⛰️  Features

- add MCP tools error handling and reasoning effort options - ([68b9258](https://github.com/belingud/yaicli/commit/68b9258cdf5820ee45373fa616d169122f9bd7cf)) - Belingud

### 🐛 Bug Fixes

- handle errors in get_openai_mcp_tools and MCPClient methods - ([251961f](https://github.com/belingud/yaicli/commit/251961f509d25b17171b66f1d3e3df920dac0730)) - Belingud

### 🚜 Refactor

- standardize completion parameter keys across providers - ([f294f75](https://github.com/belingud/yaicli/commit/f294f758f484b33a7dd825e325bd3bc0543094e3)) - Belingud

### 📚 Documentation

- add Mistral to README - ([0d72f37](https://github.com/belingud/yaicli/commit/0d72f37969c54b9dc24204f7ee7753a97af59ee5)) - Belingud
- update CHANGELOG.md for v0.7.1 release - ([72a2107](https://github.com/belingud/yaicli/commit/72a21073f094491ff5670e48f6f1b65b1d1027ed)) - Belingud

### 🧪 Testing

- add tests for MistralProvider and update imports - ([c297bef](https://github.com/belingud/yaicli/commit/c297bef27342fcc5e8e294c92d886e0f1ca551b5)) - Belingud

### ⚙️ Miscellaneous Tasks

- add mistralai and tox-uv dependencies - ([d753356](https://github.com/belingud/yaicli/commit/d753356c4ac14458bea60269bc0e2532d5e30f63)) - Belingud


---
## [0.7.1](https://github.com/belingud/yaicli/compare/v0.7.0..v0.7.1) - 2025-06-27

### 📚 Documentation

- update CHANGELOG.md for v0.7.0 release - ([782e0de](https://github.com/belingud/yaicli/commit/782e0de7f45821ffc37ba648b845916b21f05f8e)) - Belingud

### ⚙️ Miscellaneous Tasks

- add fastmcp dependency - ([e1dfcbb](https://github.com/belingud/yaicli/commit/e1dfcbbc47a64c756a9070b2bfecf67e61955ddd)) - Belingud


---
## [0.7.0](https://github.com/belingud/yaicli/compare/v0.6.4..v0.7.0) - 2025-06-27

[!IMPORTANT]
- Add MCP support.

### ⛰️  Features

- add MCP support in functions module - ([224c408](https://github.com/belingud/yaicli/commit/224c4084fe4990bc5cc640e94886630d79f38ec8)) - Belingud
- add --list-mcp option to main function - ([4a536d4](https://github.com/belingud/yaicli/commit/4a536d43a04cb7bbc135f84e0fe22ee52c6c9da3)) - Belingud
- add MCP options to CLI entry point - ([d7f3978](https://github.com/belingud/yaicli/commit/d7f397850a49af17cd03c32e27a434427ad6fee5)) - Belingud
- add MCP support to LLMClient and providers - ([58a4609](https://github.com/belingud/yaicli/commit/58a4609521ee5bcc97c285b0d28055b740b247a7)) - Belingud
- add asyncio utilities and function wrapper - ([fb9e02b](https://github.com/belingud/yaicli/commit/fb9e02bc4d345bb0b7feb9ba5407de2083d63503)) - Belingud

### 🐛 Bug Fixes

- Add tool call chunk processing in AI21Provider - ([df78c4f](https://github.com/belingud/yaicli/commit/df78c4ff733a5483cf60cf207e09677674c140a7)) - Belingud

### 🚜 Refactor

- simplify tool call creation and update default provider - ([225e066](https://github.com/belingud/yaicli/commit/225e0666666908b4e2fbbbbfb4fd1bc5ae97ab36)) - Belingud
- remove unused imports and simplify DoubaoProvider constructor - ([5effa9d](https://github.com/belingud/yaicli/commit/5effa9d2559257578932b9c82f8f95d06764864f)) - Belingud
- update parse_choice_from_content to support ChoiceChunk - ([7f2194f](https://github.com/belingud/yaicli/commit/7f2194f60ab592608c9ea4012e442dc9737e4a02)) - Belingud
- refactor tools module for MCP integration - ([62ab778](https://github.com/belingud/yaicli/commit/62ab77895b4f7f4cd9246226af3c03b096a86186)) - Belingud

### 📚 Documentation

- add default HF_PROVIDER to README - ([98e0066](https://github.com/belingud/yaicli/commit/98e0066efe7fb9c7f05beab41a2420db4bae2301)) - Belingud
- add MCP support and documentation - ([adfdd62](https://github.com/belingud/yaicli/commit/adfdd62637fc17b83b431581580d123589420d56)) - Belingud
- update CHANGELOG.md for v0.6.4 release - ([d16a66b](https://github.com/belingud/yaicli/commit/d16a66b30150440a009c4d1febf72d1806b4cf5e)) - Belingud

### 🧪 Testing

- update test case for new config key - ([f38024c](https://github.com/belingud/yaicli/commit/f38024cbcf1b6b9ce085bce62c1f1f967d2a5f86)) - Belingud
- add tests for get_or_create_event_loop - ([594b671](https://github.com/belingud/yaicli/commit/594b6717f83ce0feea2571008337e24afc701694)) - Belingud
- update provider names and default value handling - ([013a989](https://github.com/belingud/yaicli/commit/013a98988a041c8e61b9793fb8b174f0cf444af2)) - Belingud


---
## [0.6.4](https://github.com/belingud/yaicli/compare/v0.6.3..v0.6.4) - 2025-06-24

### ⛰️  Features

- add new Cohere providers and improve type handling - ([5d5f53c](https://github.com/belingud/yaicli/commit/5d5f53cda18eea77f1e83e8ec24f519c6cd6a01f)) - Belingud
- add HuggingFace provider to ProviderFactory - ([a08cd70](https://github.com/belingud/yaicli/commit/a08cd7094ed3af11d754bd788730f6a130bcfade)) - Belingud
- add HuggingFaceProvider class - ([d81b42c](https://github.com/belingud/yaicli/commit/d81b42c9ad884489b50aae17696910a02666c22e)) - Belingud

### 🐛 Bug Fixes

- handle empty content in CLI methods - ([26ed101](https://github.com/belingud/yaicli/commit/26ed101e899e1b9de3d6af36dabcfbd3e190c8f3)) - Belingud

### 🚜 Refactor

- standardize completion params keys in providers - ([6802dfd](https://github.com/belingud/yaicli/commit/6802dfd61760ea66e494f776a5e85ecea1de2b91)) - Belingud

### 📚 Documentation

- update installation commands and supported providers - ([9034c98](https://github.com/belingud/yaicli/commit/9034c9876f5268a3073c2cad0db503324207e819)) - Belingud
- add new models and configurations - ([f2b02b8](https://github.com/belingud/yaicli/commit/f2b02b83e604e82ed9a913b1da54c99b9cfbae02)) - Belingud
- update CHANGELOG.md for v0.6.3 release - ([8370366](https://github.com/belingud/yaicli/commit/8370366f1bb0bf48cb12488f9e222e0526aff305)) - Belingud

### 🧪 Testing

- add tests for HuggingFaceProvider and update provider factory - ([88f4a0b](https://github.com/belingud/yaicli/commit/88f4a0b8b62e8028f3b4bcb7fbb47512fc631614)) - Belingud

### ⚙️ Miscellaneous Tasks

- add new dependencies and keywords - ([f82a5b7](https://github.com/belingud/yaicli/commit/f82a5b7ea217e888cb621b19d34f11a6c5389d8a)) - Belingud


---
## [0.6.3](https://github.com/belingud/yaicli/compare/v0.6.2..v0.6.3) - 2025-06-23

### ⛰️  Features

- add error handling for better error show - ([ced63b8](https://github.com/belingud/yaicli/commit/ced63b81cc9339f4bd5569b5bd61d0455c4b2ab5)) - Belingud
- add gemini and vertexai providers - ([1cb56ad](https://github.com/belingud/yaicli/commit/1cb56ada4dde53146ff5a0ad3e2c932577b244d7)) - Belingud

### 🐛 Bug Fixes

- use display_stream return content for command execute - ([5443822](https://github.com/belingud/yaicli/commit/54438224cd6278b6281abe2c282ec79ad3dec276)) - Belingud
- ensure non-empty config values are used in completion params - ([c319ade](https://github.com/belingud/yaicli/commit/c319ade3d041243b445321c450a2efa7966ec2db)) - Belingud

### 🚜 Refactor

- remove unused BaseProvider class - ([1166114](https://github.com/belingud/yaicli/commit/116611461d621f68c85e7bc96d0faa8f30dd08eb)) - Belingud

### 📚 Documentation

- update CHANGELOG.md for v0.6.2 release - ([b9e6354](https://github.com/belingud/yaicli/commit/b9e63547d65eb0a0e875e7acb42917ad309ced14)) - Belingud

### 🧪 Testing

- add tests for gemini and vertexai providers - ([7a9f755](https://github.com/belingud/yaicli/commit/7a9f755a8a4de584db47e3408f9028eb0e71d982)) - Belingud

### ⚙️ Miscellaneous Tasks

- update default reasoning effort to empty string - ([e7f59c3](https://github.com/belingud/yaicli/commit/e7f59c3390f0e3aed443436d335b4ee1f114dec0)) - Belingud


---
## [0.6.2](https://github.com/belingud/yaicli/compare/v0.6.1..v0.6.2) - 2025-06-23

### ⛰️  Features

- update provider mappings in ProviderFactory - ([3dce344](https://github.com/belingud/yaicli/commit/3dce344a7b30de315fd69d7af692a0e160d7b58d)) - Belingud
- add XaiProvider class based on OpenAIProvider - ([f177da8](https://github.com/belingud/yaicli/commit/f177da88c35d5934bf14c111d7bf61e4e8a6cf73)) - Belingud

### 🚜 Refactor

- standardize completion parameter handling across providers - ([25be368](https://github.com/belingud/yaicli/commit/25be368ca67ac57c9beecb0c35223f9fe28c5244)) - Belingud

### 📚 Documentation

- update default settings and add XAI provider - ([1cef2f8](https://github.com/belingud/yaicli/commit/1cef2f8e558162536db8eb22cf58922db0f63b87)) - Belingud
- update CHANGELOG.md for v0.6.1 release - ([0c5ece3](https://github.com/belingud/yaicli/commit/0c5ece3c6da82267b280b96dbea8c52c86d1ca32)) - Belingud

### 🧪 Testing

- add xai to provider factory test - ([f89068f](https://github.com/belingud/yaicli/commit/f89068f401955de4f1f9fdcd862d3a4885d324bb)) - Belingud
- add tests for XaiProvider and new Role class - ([c77d070](https://github.com/belingud/yaicli/commit/c77d0708c395ab1a7dd78e44ed86f87d39ebdf66)) - Belingud
- update provider referer and add new providers - ([423cbbd](https://github.com/belingud/yaicli/commit/423cbbdb1e5bc6296f0262bee62337bd6e343cf6)) - Belingud


---
## [0.6.1](https://github.com/belingud/yaicli/compare/v0.6.0..v0.6.1) - 2025-06-22

### ⛰️  Features

- add error handling for empty choices in OpenAIProvider for better error message - ([9cd2a28](https://github.com/belingud/yaicli/commit/9cd2a285a52c0b1c5a646aadfbcc97eb71c44394)) - Belingud
- add minimax and targon providers - ([e8df86f](https://github.com/belingud/yaicli/commit/e8df86fdb7757e454162661051883a621066fc58)) - Belingud

### 🚜 Refactor

- Unify completion params handling in LLM providers - ([9132020](https://github.com/belingud/yaicli/commit/913202089e7763808ee45186563b332155dca98f)) - Belingud

### 📚 Documentation

- update CHANGELOG.md for v0.6.0 release - ([f9b9085](https://github.com/belingud/yaicli/commit/f9b908507c82b2ac0b03e51e7cbd5a833c6468a4)) - Belingud

### 🧪 Testing

- update mocking strategy for provider tests - ([4b9c410](https://github.com/belingud/yaicli/commit/4b9c41018504ffa4632b4d7af393979543532360)) - Belingud


---
## [0.6.0](https://github.com/belingud/yaicli/compare/v0.5.9..v0.6.0) - 2025-06-22

### ⛰️  Features

- refactor OllamaProvider and update default temperature - ([cf2dbe9](https://github.com/belingud/yaicli/commit/cf2dbe9d105f2731b1e08915027c12f3917d123e)) - Belingud

### 🚜 Refactor

- Update provider naming and Groq N param handling - ([309f70e](https://github.com/belingud/yaicli/commit/309f70e1794dc2f39bf9cd511c26ec0c22db1340)) - Belingud
- revamp LLM client and provider architecture - ([90f7d46](https://github.com/belingud/yaicli/commit/90f7d46ceb79b2ac8b35ce03a5da33ce533aa1bd)) - Belingud

### 📚 Documentation

- update README with installation options and provider configs - ([c7c088f](https://github.com/belingud/yaicli/commit/c7c088fe8b7bcb2e1f9b756913c8166824656484)) - Belingud
- update CHANGELOG.md for v0.5.9 release - ([ba73961](https://github.com/belingud/yaicli/commit/ba7396141440cdc175002356a52954af33e0aaf8)) - Belingud

### 🧪 Testing

- add llms package tests - ([9c3e5c2](https://github.com/belingud/yaicli/commit/9c3e5c2da6c74f274e860cc6c17350a93a9463ba)) - Belingud

### ⚙️ Miscellaneous Tasks

- Update optional dependencies in pyproject.toml - ([cc8f865](https://github.com/belingud/yaicli/commit/cc8f8657166223fc3589f2cde68f5406a90068e3)) - Belingud
- Configure ruff linting and add 'all' optional deps - ([3d660e3](https://github.com/belingud/yaicli/commit/3d660e3a428b4ac2fdbda9bb600ea58247892d98)) - Belingud
- Update project keywords for broader AI model support - ([5e09e7b](https://github.com/belingud/yaicli/commit/5e09e7b9fc2243fd15e129a5928516850e29b98e)) - Belingud


---
## [0.5.9](https://github.com/belingud/yaicli/compare/v0.5.8..v0.5.9) - 2025-06-12

### 📚 Documentation

- update CHANGELOG.md for v0.5.8 release - ([18a47d2](https://github.com/belingud/yaicli/commit/18a47d2a95c0d87b842c6c83884165dcd5fa89f0)) - Belingud

### ⚙️ Miscellaneous Tasks

- update click and typer dependencies - ([1f99298](https://github.com/belingud/yaicli/commit/1f992982905e280ecd676b315f73b184c83cc3c3)) - Belingud


---
## [0.5.8](https://github.com/belingud/yaicli/compare/v0.5.7..v0.5.8) - 2025-05-22

### 🚜 Refactor

- move schemas imports and update StrEnum compatibility - ([a8a5b3b](https://github.com/belingud/yaicli/commit/a8a5b3b8e5dd2d817e71aa4e4d6585d33724062c)) - Belingud

### 📚 Documentation

- update CHANGELOG.md for v0.5.7 release - ([a0a641a](https://github.com/belingud/yaicli/commit/a0a641a032eac9737d7c1f99544651f9f958e322)) - Belingud


---
## [0.5.7](https://github.com/belingud/yaicli/compare/v0.5.6..v0.5.7) - 2025-05-22

### ⛰️  Features

- add support for EXTRA_HEADERS and EXTRA_BODY configuration - ([7f8622f](https://github.com/belingud/yaicli/commit/7f8622fec170c31e9cb0116eb2f7f300ca1a62df)) - Belingud

### 📚 Documentation

- update README with new config options and dependencies - ([ebe2023](https://github.com/belingud/yaicli/commit/ebe202385bad3ae085f9a7e90f235fcbc1acfad0)) - Belingud
- update CHANGELOG.md for v0.5.6 release - ([2cf8e82](https://github.com/belingud/yaicli/commit/2cf8e823d42dfd0d45d6f1a219fda27db39854e4)) - Belingud


---
## [0.5.6](https://github.com/belingud/yaicli/compare/v0.5.5..v0.5.6) - 2025-05-22

### 🐛 Bug Fixes

- update project config and simplify printer logic - ([029b7e2](https://github.com/belingud/yaicli/commit/029b7e26c0502e4ae7f32931cdaa2dd2f1d167a8)) - Belingud

### 📚 Documentation

- Fix formatting in README - ([7e440da](https://github.com/belingud/yaicli/commit/7e440da0fe9492736bf1ad160095447d5fce010b)) - Belingud
- update CHANGELOG.md for v0.5.5 release - ([5d12c69](https://github.com/belingud/yaicli/commit/5d12c692d5f692f8d5ede2e57f0a2a81a16e75a8)) - Belingud

### ⚙️ Miscellaneous Tasks

- add 'ai' as alternative command in pyproject.toml - ([d1852f1](https://github.com/belingud/yaicli/commit/d1852f175ec3a821498640df8755f6e165d71fff)) - Belingud


---
## [0.5.5](https://github.com/belingud/yaicli/compare/v0.5.4..v0.5.5) - 2025-05-21

### 🚜 Refactor

- Improve case-insensitive command handling in CLI - ([a9f1382](https://github.com/belingud/yaicli/commit/a9f13829a66c7e9c3a7726222964f99aece1555b)) - Belingud

### 📚 Documentation

- add producthunt badge to README - ([3b2d98b](https://github.com/belingud/yaicli/commit/3b2d98b586b0d25917aba8c25d12c7f548b489f0)) - Belingud
- add example image for reasoning shell - ([99ff117](https://github.com/belingud/yaicli/commit/99ff1171e1ffef550d1ee3ba01137664428384b8)) - Belingud
- update CHANGELOG.md for v0.5.4 release - ([fb5d95a](https://github.com/belingud/yaicli/commit/fb5d95a145f23760b2b0d72c078014e5874a16c4)) - Belingud


---
## [0.5.4](https://github.com/belingud/yaicli/compare/v0.5.3..v0.5.4) - 2025-05-14

### 📚 Documentation

- Update CHANGELOG.md for v0.5.3 release - ([a0bf128](https://github.com/belingud/yaicli/commit/a0bf1286fce96ff4074c2b2284186e9261c8ca64)) - Belingud

### ⚙️ Miscellaneous Tasks

- Update dependencies - ([698a054](https://github.com/belingud/yaicli/commit/698a054224e49194b59cd6e096a91804a0b859d5)) - Belingud


---
## [0.5.3](https://github.com/belingud/yaicli/compare/v0.5.2..v0.5.3) - 2025-05-14

### 📚 Documentation

- update CHANGELOG.md for v0.5.2 release - ([4393332](https://github.com/belingud/yaicli/commit/4393332566110fa2c0ceac8b223923039987c579)) - Belingud


---
## [0.5.2](https://github.com/belingud/yaicli/compare/v0.5.1..v0.5.2) - 2025-05-14

### 📚 Documentation

- Update sologan and logo - ([1ccd4b5](https://github.com/belingud/yaicli/commit/1ccd4b56fcbd0fcc6f028c48e9b2b19a0f1972f5)) - Belingud
- Update CHANGELOG.md for v0.5.1 release - ([d7023dc](https://github.com/belingud/yaicli/commit/d7023dcb82b17e37c8e493c6209c04d3a7d893d1)) - Belingud


---
## [0.5.1](https://github.com/belingud/yaicli/compare/v0.5.0..v0.5.1) - 2025-05-14

### 🚜 Refactor

- remove unused command line argument - ([2daf0e0](https://github.com/belingud/yaicli/commit/2daf0e04c2ee2e9b1cbac030f19ea6a5653f03d7)) - Belingud

### 📚 Documentation

- add function call support to README - ([191b5ae](https://github.com/belingud/yaicli/commit/191b5aed9ea4d4b42747a258bf2fb8b8c41ebc83)) - Belingud
- Update CHANGELOG.md for v0.5.0 release - ([db7a328](https://github.com/belingud/yaicli/commit/db7a328746b45e2b99c176842fc157e0fc063cf3)) - Belingud


---
## [0.5.0](https://github.com/belingud/yaicli/compare/v0.4.0..v0.5.0) - 2025-05-14

### ⛰️  Features

[!IMPORTANT]
- Add Function Call support.

- Add reasoning effort configuration and function output panel - ([f21d29b](https://github.com/belingud/yaicli/commit/f21d29bcd1b9ebf411a6329dd98b659ded5ec1fa)) - Belingud
- refactor client and printer logic, add function call support - ([9f008be](https://github.com/belingud/yaicli/commit/9f008bed2f1ef42665da0c453474044bb809c9ce)) - Belingud
- add non-stream completion function call - ([572e2e2](https://github.com/belingud/yaicli/commit/572e2e212c1911155467bcc85274e6f536526899)) - Belingud
- add non-stream completion function call - ([13d6154](https://github.com/belingud/yaicli/commit/13d6154ff95a1622365efb49b2b48931c4fcc070)) - Belingud

### 📚 Documentation

- Enhance README with function calling and provider info - ([ab69e5c](https://github.com/belingud/yaicli/commit/ab69e5ca1befe0d14b974451ec96262a6db7a3c0)) - Belingud
- update changelog for v0.4.0 release - ([66db3ee](https://github.com/belingud/yaicli/commit/66db3eed4fd9866b1711477753092de6ab171d57)) - Belingud

### 🧪 Testing

- update test case for refactored project - ([26e0faf](https://github.com/belingud/yaicli/commit/26e0faf8ebf7ce9ebebcc096371f000183c00b4a)) - Belingud

### ⚙️ Miscellaneous Tasks

- update dependencies and script name - ([562d930](https://github.com/belingud/yaicli/commit/562d930fcddf5b874f1eefb9db08a1966490ef37)) - Belingud


---
## [0.4.0](https://github.com/belingud/yaicli/compare/v0.3.3..v0.4.0) - 2025-05-01

**From this version, yaicli will use provider sdk instead of httpx raw request**

Providers:
- OpenAI
- Cohere

### ⛰️  Features

- add provider-based API client architecture with OpenAI and Cohere support - ([9f68de1](https://github.com/belingud/yaicli/commit/9f68de1a545dc297abb2f5479820121cfd753099)) - Belingud
- add role modify warning config and optimize lru_cache - ([9c25162](https://github.com/belingud/yaicli/commit/9c25162f26f6767d90ce24cb8d64780ad45c0219)) - Belingud
- add role modification warnings and singleton pattern for RoleManager - ([e2f9596](https://github.com/belingud/yaicli/commit/e2f959665488b856acec863f121a1126f9529c7c)) - Belingud

### 🚜 Refactor

- reorganize imports and improve code formatting - ([c1ee133](https://github.com/belingud/yaicli/commit/c1ee13399d5cdd503821fadfe2dc8c4f56656854)) - Belingud

### 📚 Documentation

- refine README with updated configurations and provider info - ([90b8170](https://github.com/belingud/yaicli/commit/90b8170e1adefb21ab2fca88c15ca38aaa54ea91)) - Belingud
- update changelog for v0.3.3 release - ([3c73873](https://github.com/belingud/yaicli/commit/3c73873afad339f5d247299b6ffeb3526e1827b3)) - Belingud

### 🧪 Testing

- add provider tests for base, cohere, openai, and factory - ([26e6ef2](https://github.com/belingud/yaicli/commit/26e6ef2ec80763910fe4114a0a1f2f1f8c50e9f9)) - Belingud

### ⚙️ Miscellaneous Tasks

- add chat demo cast and use asciinema for example - ([36f3dea](https://github.com/belingud/yaicli/commit/36f3dea8fecfdc05601c86311a8069b60640c893)) - Belingud
- add yaicli to isort formatting in Justfile - ([d47def9](https://github.com/belingud/yaicli/commit/d47def9e4b021ba4eb7c63715cad2edb787195dd)) - Belingud


---
## [0.3.3](https://github.com/belingud/yaicli/compare/v0.3.2..v0.3.3) - 2025-04-29

### 🚜 Refactor

- remove redundant console print in CLI prompt logic - ([1cf8241](https://github.com/belingud/yaicli/commit/1cf824164db92cb7d91ab49ab44fd1e65ab35533)) - Belingud

### 📚 Documentation

- update changelog for v0.3.2 release - ([328f51b](https://github.com/belingud/yaicli/commit/328f51b79c7d1a982a942c833417841476ec70aa)) - Belingud


---
## [0.3.2](https://github.com/belingud/yaicli/compare/v0.3.1..v0.3.2) - 2025-04-29

### 🐛 Bug Fixes

- mode change in repl should also change role - ([9dea555](https://github.com/belingud/yaicli/commit/9dea5552da2026c5de90a8a9ae8bb77708539100)) - Belingud

### 📚 Documentation

- Update CHANGELOG.md for release 0.3.1 - ([4511255](https://github.com/belingud/yaicli/commit/4511255df1a0c9f3be43a7ecdbc67f6272eb20dc)) - Belingud

### 🧪 Testing

- add X-Title header to API client test - ([f786c48](https://github.com/belingud/yaicli/commit/f786c48cc08aa824126e877c35a4e29e94612eea)) - Belingud

### ⚙️ Miscellaneous Tasks

- configure GitHub Actions for PyPI publishing - ([b2d0cd4](https://github.com/belingud/yaicli/commit/b2d0cd46e77f3994ed0be49ab6a9ae0d943c7124)) - Belingud


---
## [0.3.1](https://github.com/belingud/yaicli/compare/v0.3.0..v0.3.1) - 2025-04-29

### ⛰️  Features

- Add X-Title header to API requests - ([e30060b](https://github.com/belingud/yaicli/commit/e30060b64eafa2ad361c28ef6471e9eebe5e955d)) - Belingud
- clarify --code option help message - ([74349c9](https://github.com/belingud/yaicli/commit/74349c9b38cd7773c53c211da955003294dcf04e)) - Belingud

### 🚜 Refactor

- simplify chat manager test setup - ([8650b05](https://github.com/belingud/yaicli/commit/8650b05df1e6228597be741a2d95c805cf6db0b9)) - Belingud

### 📚 Documentation

- refine CLI documentation and add code example - ([658ecf9](https://github.com/belingud/yaicli/commit/658ecf9444601277a5c63f57fe28ca6936365fba)) - Belingud
- Update README with new features and usage examples - ([756942b](https://github.com/belingud/yaicli/commit/756942b9a80b13dfc49e0e773b1ff98b086c9c3e)) - Belingud
- Update 0.3.0 feat changelog - ([34ad75a](https://github.com/belingud/yaicli/commit/34ad75ab026e44bd2749e9c99f97d187e4e50ca5)) - Belingud
- update CHANGELOG for v0.3.0 - ([ce27418](https://github.com/belingud/yaicli/commit/ce27418275697b8a6919285a153c89326477913a)) - Belingud

### ⚙️ Miscellaneous Tasks

- update Justfile commands and descriptions - ([0c5b841](https://github.com/belingud/yaicli/commit/0c5b841201060eb3dc87ff68c0f6edecce3bb182)) - Belingud


---
## [0.3.0](https://github.com/belingud/yaicli/compare/v0.2.0..v0.3.0) - 2025-04-28

1. Add roles create/delete/list/show commands
2. Add role management functionality
3. Improve configuration management
4. Add reasoning show config, justify config

### ⛰️  Features

- add roles and improve configuration management - ([fa883e9](https://github.com/belingud/yaicli/commit/fa883e9a39a9d72a60d1832b71c67a1bf6492b3c)) - Belingud

### 🚜 Refactor

- reorder imports and remove unused imports - ([28699dd](https://github.com/belingud/yaicli/commit/28699dde7df4c06ba252c5fa98923e373a28cfcd)) - Belingud
- Improve typing and streamline code for maintainability, add role funtion - ([7f7230b](https://github.com/belingud/yaicli/commit/7f7230b6cf5ef07f7bc857f5ba9f710565886107)) - Belingud

### 📚 Documentation

- improve documentation and configuration details - ([28287d0](https://github.com/belingud/yaicli/commit/28287d0a622e1934a7fcb7da0158d65bf3b70be9)) - Belingud
- Add reasoning example and update README - ([c80da0f](https://github.com/belingud/yaicli/commit/c80da0fdd957a13c91a6a55b4ee54dc10c5576ed)) - Belingud
- Update README.md - ([1c169e5](https://github.com/belingud/yaicli/commit/1c169e5895ca0533ab1cfbca948872af30cdb4af)) - belingud
- update CHANGELOG.md for v0.2.0 release - ([9cda1ea](https://github.com/belingud/yaicli/commit/9cda1eaa73c5e81e127eaac3ade8265a2a7ffb61)) - Belingud

### 🧪 Testing

- update CLI input handling and improve test cases for chat mode - ([7a12f71](https://github.com/belingud/yaicli/commit/7a12f716653db7e5215bfa421206951977d5a713)) - Belingud


---
## [0.2.0](https://github.com/belingud/yaicli/compare/v0.1.0..v0.2.0) - 2025-04-22

### ⛰️  Features

- enhance chat management and command-line interface - ([6898273](https://github.com/belingud/yaicli/commit/68982737221b18416ba1eb8201c328203ada2b72)) - Belingud
- add chat persistent - ([291d7b7](https://github.com/belingud/yaicli/commit/291d7b7a9c2595dcc2794e3b36617cb186a6dc56)) - Belingud

### 📚 Documentation

- improve documentation and add chat history features - ([c0f1545](https://github.com/belingud/yaicli/commit/c0f15453862bb23fca29c8f283dcd4c82181d1c5)) - Belingud
- Update README to clarify project description - ([21d6389](https://github.com/belingud/yaicli/commit/21d6389ea70a8770ff798c9b4d4ba22d7d075533)) - Belingud
- update CHANGELOG.md for v0.1.0 release - ([474aaa4](https://github.com/belingud/yaicli/commit/474aaa4a120366a607edc584a8d4b698a16390ca)) - Belingud

### 🧪 Testing

- Update chat management and CLI tests - ([1b3ccb0](https://github.com/belingud/yaicli/commit/1b3ccb027066ec3cd80e8a0d2f9fb0cc65908f50)) - Belingud
- update test case for chat persistent - ([af4f7e7](https://github.com/belingud/yaicli/commit/af4f7e76c2129373b5c3f9ec5971bda14bd961ea)) - Belingud

### Chroe

- Add format command to Justfile - ([676ba1b](https://github.com/belingud/yaicli/commit/676ba1b1759c5439593f57e26d67b7c47b9b26bd)) - Belingud


---
## [0.1.0](https://github.com/belingud/yaicli/compare/v0.0.19..v0.1.0) - 2025-04-20

### ⛰️  Features

- split content and reasoning content for better display - ([83c7cff](https://github.com/belingud/yaicli/commit/83c7cffb6a278320ef6d3884ac6ff9a8a7c4910f)) - Belingud

### 🚜 Refactor

- Replace "reasoning" with "thinking" in tests, fix CLI exit - ([519d210](https://github.com/belingud/yaicli/commit/519d21024993db434671375310ce0417610d30ee)) - Belingud
- Rename INTERACTIVE_MAX_HISTORY to INTERACTIVE_ROUND - ([ac17cad](https://github.com/belingud/yaicli/commit/ac17cadad1015cf4650a84f1ca566da4afc08e54)) - Belingud
- refactor yaicli, imporve logic - ([71d19d6](https://github.com/belingud/yaicli/commit/71d19d6f0acc4ea1f139392473ddc7a968b78896)) - Belingud
- extract completion response processing logic - ([d9f8d08](https://github.com/belingud/yaicli/commit/d9f8d085198bc1374f021f24204d81f23a923949)) - Belingud
- refactor yaicli structure - ([e2ad1be](https://github.com/belingud/yaicli/commit/e2ad1bec6426120bf2ff162a248a7cf6b82e21c7)) - Belingud

### 📚 Documentation

- improve README with detailed features and usage - ([555f2b7](https://github.com/belingud/yaicli/commit/555f2b7832649b6de035298454f3332f2d1917a2)) - Belingud
- add example artwork - ([8b40706](https://github.com/belingud/yaicli/commit/8b40706e644c9c7a1c31c19286accd23d055f578)) - Belingud
- update README with timeout option and improved help text - ([cd0f031](https://github.com/belingud/yaicli/commit/cd0f031148bc1dfe19602ea23ff0a98c75464ad0)) - Belingud
- update CHANGELOG for v0.0.19 release - ([4ff2781](https://github.com/belingud/yaicli/commit/4ff2781334957dd6b13dd694ac6f52f045094a95)) - Belingud

### 🧪 Testing

- add new options to mock CLI config - ([0279155](https://github.com/belingud/yaicli/commit/0279155bbb53db57c128834d35d17193970d2bbe)) - Belingud
- update test case for refactor - ([d6072b3](https://github.com/belingud/yaicli/commit/d6072b39bc4e798030fe28ed09fede9150cd933e)) - Belingud
- update tests for refactor - ([024edb7](https://github.com/belingud/yaicli/commit/024edb7f22fd479ecf2f225d5d8f7d59af4777e0)) - Belingud


---
## [0.0.19](https://github.com/belingud/yaicli/compare/v0.0.18..v0.0.19) - 2025-04-16

### ⛰️  Features

- enhance configuration handling with type support and improve default config initialization - ([34bc896](https://github.com/belingud/yaicli/commit/34bc896df1ae97f5a111cc95a4ebd58caafc6d07)) - Belingud

### 📚 Documentation

- update CHANGELOG.md for v0.0.18 release - ([bc19008](https://github.com/belingud/yaicli/commit/bc190086d5b1bcc9b083b057f891d3cdaff6ef0d)) - Belingud


---
## [0.0.18](https://github.com/belingud/yaicli/compare/v0.0.17..v0.0.18) - 2025-04-14

### ⛰️  Features

- add auto-suggest from history and improve config handling - ([22b31de](https://github.com/belingud/yaicli/commit/22b31ded71b4ecb87e1829076416b615affa38b4)) - Belingud

### 📚 Documentation

- update CHANGELOG.md for v0.0.17 release - ([af27d29](https://github.com/belingud/yaicli/commit/af27d29351d5c37c7473bb4021eaf31f2d7a2cfb)) - Belingud


---
## [0.0.17](https://github.com/belingud/yaicli/compare/v0.0.16..v0.0.17) - 2025-04-14

### 🐛 Bug Fixes

- Correct stdin TTY check and remove completer - ([e2ee703](https://github.com/belingud/yaicli/commit/e2ee7039c2f9fc707fe9a4eec57d2226a0e25254)) - Belingud

### 🚜 Refactor

- remove unused WordCompleter import - ([968e6f1](https://github.com/belingud/yaicli/commit/968e6f194aee2c1467b1e9b68bb118af614bd5ec)) - Belingud

### ⚙️ Miscellaneous Tasks

- update yaicli version to 0.0.16 in uv.lock and CHANGELOG.md - ([f9376c4](https://github.com/belingud/yaicli/commit/f9376c4fa7e6641ebed20bb071fac997c4467243)) - Belingud


---
## [0.0.16](https://github.com/belingud/yaicli/compare/v0.0.15..v0.0.16) - 2025-04-14

### ⛰️  Features

- **(cli)** add max history limit and stdin support - ([1b685df](https://github.com/belingud/yaicli/commit/1b685df079a0cb3010c73c543bdf8c4fbb72195d)) - Belingud

### 🚜 Refactor

- Remove unused io import - ([1e72f6c](https://github.com/belingud/yaicli/commit/1e72f6c3a1dfaff6326ad171aee360c57592be24)) - Belingud

### 📚 Documentation

- update README with new shortcuts and max history size - ([af70000](https://github.com/belingud/yaicli/commit/af700006e2a5f6b1b4ec1ec90396e00c45b4509f)) - Belingud

### ⚙️ Miscellaneous Tasks

- update yaicli version to 0.0.15 in uv.lock and CHANGELOG.md - ([15faced](https://github.com/belingud/yaicli/commit/15faced8e89e5eebc7ed6984be6b0e1a7743ff8c)) - Belingud


---
## [0.0.15](https://github.com/belingud/yaicli/compare/v0.0.14..v0.0.15) - 2025-04-11

### ⛰️  Features

- add CODE_THEME configuration for code block styling - ([ed0e8f6](https://github.com/belingud/yaicli/commit/ed0e8f62f73128ef2c57a472560ae438c8738103)) - Belingud

### 🐛 Bug Fixes

- handle None value in SHELL environment variable - ([a4e29f5](https://github.com/belingud/yaicli/commit/a4e29f5876f042c71d9a9d36f6577ce751a26eba)) - Belingud

### 📚 Documentation

- update CHANGELOG.md with env key prefix change - ([48b33da](https://github.com/belingud/yaicli/commit/48b33da0d290ac9707e0e441318e50760c7de251)) - Belingud
- update README.md with improved command execution format - ([03b2417](https://github.com/belingud/yaicli/commit/03b2417abc0e3127facb7638b31f07e1e35d8da1)) - Belingud
- update command execution UI in README.md - ([a4aadc8](https://github.com/belingud/yaicli/commit/a4aadc8c47b01117edfadb49db058e5e44847061)) - Belingud

### 🎨 Styling

- fix spacing around 'or' operator in shell detection - ([44cedc9](https://github.com/belingud/yaicli/commit/44cedc993fda3b64df16adfc5a1381c31c04b045)) - Belingud

### 🧪 Testing

- add smoke tests for CLI and fix shell detection tests - ([baa1beb](https://github.com/belingud/yaicli/commit/baa1beb0238eb0c228d0c56310839d53b09c8484)) - Belingud

### ⚙️ Miscellaneous Tasks

- update yaicli version to 0.0.14 in uv.lock and CHANGELOG.md - ([9d21edf](https://github.com/belingud/yaicli/commit/9d21edf9c046fe4c976750b27a0554d4605ccc5a)) - Belingud


---
## [0.0.14](https://github.com/belingud/yaicli/compare/v0.0.13..v0.0.14) - 2025-04-10

### ⛰️  Features

- **(cli)** enhance command execution and output display - ([d101841](https://github.com/belingud/yaicli/commit/d101841b17ee57e421574408fdc643a4f5b1eea7)) - Belingud

### 🚜 Refactor

- clean up unused imports in yaicli.py - ([71c64af](https://github.com/belingud/yaicli/commit/71c64af167b0b0d2b8f771302b86035da0c8f18f)) - Belingud

### 📚 Documentation

- **(Justfile)** update changelog command message - ([b060812](https://github.com/belingud/yaicli/commit/b060812488d8c64bb0bded6433fb93a66946c8aa)) - Belingud

### ⚙️ Miscellaneous Tasks

- update yaicli version to 0.0.13 in uv.lock and CHANGELOG.md - ([3806f70](https://github.com/belingud/yaicli/commit/3806f707e320ec7616264e62c28d3e345fb6a79d)) - Belingud


---
## [0.0.13](https://github.com/belingud/yaicli/compare/v0.0.12..v0.0.13) - 2025-04-09

[!IMPORTANT]
- Change env key prefix from AI_ to YAI_

### ⛰️  Features

- **(cli)** add command edit option and improve console output styling - ([48c14cc](https://github.com/belingud/yaicli/commit/48c14ccff33af8ebeaeb100e002cf15c01d3756e)) - Belingud
- refactor CLI and add new configuration options - ([ad09301](https://github.com/belingud/yaicli/commit/ad093015cd2d54fbd17e6a07dd56af9459b2070f)) - Belingud

### 📚 Documentation

- update README with new ASCII art and command examples - ([cdcb9af](https://github.com/belingud/yaicli/commit/cdcb9af6ece0cfa770390aa5900db5822c80d115)) - Belingud
- update CHANGELOG.md for v0.0.12 release - ([456c454](https://github.com/belingud/yaicli/commit/456c454f995fa2e6bf77fba9ca5d7b904e674f4e)) - Belingud

### ⚙️ Miscellaneous Tasks

- add ruff cache cleanup and uv lock to changelog - ([218b310](https://github.com/belingud/yaicli/commit/218b3103644b8aac6397acc2a765244c3bfae622)) - Belingud


---
## [0.0.12](https://github.com/belingud/yaicli/compare/v0.0.11..v0.0.12) - 2025-04-08

### ⛰️  Features

- add chat history and improve CLI UX with completions - ([7749883](https://github.com/belingud/yaicli/commit/7749883f886c23fc5226965795ae46128caacd13)) - Belingud

### 📚 Documentation

- restructure CLI options documentation in README - ([142ac78](https://github.com/belingud/yaicli/commit/142ac781f677b4285409414402f1493562bd6a90)) - Belingud
- update CHANGELOG.md for v0.0.11 release - ([6a6b3ae](https://github.com/belingud/yaicli/commit/6a6b3ae47d0ee2e3ae41160715f3416c3c1ce3bc)) - Belingud


---
## [0.0.11](https://github.com/belingud/yaicli/compare/v0.0.10..v0.0.11) - 2025-04-07

### 🚜 Refactor

- **(yaicli)** improve stream response parsing and add plaintext test - ([92383ae](https://github.com/belingud/yaicli/commit/92383aea242bebdf6e5149fde44d077d0757fc59)) - Belingud
- replace requests with httpx for HTTP client and update dependencies - ([cfc3823](https://github.com/belingud/yaicli/commit/cfc38232952b1eba8907067a14628fa24a81bfb6)) - Belingud

### 📚 Documentation

- update project title in README - ([cf8aaa7](https://github.com/belingud/yaicli/commit/cf8aaa7ea30c4ff845d27a5fd120b4157f28dc0c)) - Belingud

### ⚙️ Miscellaneous Tasks

- add publish command to Justfile - ([a2a76e5](https://github.com/belingud/yaicli/commit/a2a76e544332cc703a0956426c38dd5bd9301e12)) - Belingud
- update yaicli version to 0.0.10 and CHANGELOG - ([aab8fb2](https://github.com/belingud/yaicli/commit/aab8fb2340950028851577331f87fbbffb75e242)) - Belingud


---
## [0.0.10](https://github.com/belingud/yaicli/compare/v0.0.9..v0.0.10) - 2025-04-05

### 📚 Documentation

- update assistant name in default prompt - ([e92313e](https://github.com/belingud/yaicli/commit/e92313ecbd95191443b26320ae4cc26bf1983718)) - Belingud

### ⚙️ Miscellaneous Tasks

- update yaicli version to 0.0.9 and CHANGELOG - ([2a47a8b](https://github.com/belingud/yaicli/commit/2a47a8b318771139ae5f0515d7c04ccf7fef92eb)) - Belingud


---
## [0.0.9](https://github.com/belingud/yaicli/compare/v0.0.8..v0.0.9) - 2025-04-05

### ⛰️  Features

- add reasoning model support - ([8a3d21b](https://github.com/belingud/yaicli/commit/8a3d21bc1aea147652b345d0015c2468724ee37d)) - Belingud

### 📚 Documentation

- add configuration guide for non-OpenAI LLM providers - ([20f590d](https://github.com/belingud/yaicli/commit/20f590d374a3e6fa4b6c7a21529abec7dbb7d3b6)) - Belingud

### ⚙️ Miscellaneous Tasks

- update yaicli version to 0.0.8 and improve README - ([282d3b5](https://github.com/belingud/yaicli/commit/282d3b5c987a333294ed09bfaca74f2ed0e7db12)) - Belingud


---
## [0.0.8](https://github.com/belingud/yaicli/compare/v0.0.7..v0.0.8) - 2025-04-04

### ⛰️  Features

- add command filtering and improve history management - ([e743b13](https://github.com/belingud/yaicli/commit/e743b1381e07c55e8adb49a4618359c91b1b932d)) - Belingud

### 🧪 Testing

- restructure and add new test files for CLI functionality - ([09c81eb](https://github.com/belingud/yaicli/commit/09c81eb9002ed8735b2cbc41dfd739448960dfce)) - Belingud

### ⚙️ Miscellaneous Tasks

- update yaicli version to 0.0.7 and improve README - ([71a8eff](https://github.com/belingud/yaicli/commit/71a8eff5e77e5aed35a7dc2825be8dbb0a73cebe)) - Belingud


---
## [0.0.7](https://github.com/belingud/yaicli/compare/v0.0.6..v0.0.7) - 2025-04-04

### 🚜 Refactor

- simplify CLI structure and improve code maintainability - ([4eed7d8](https://github.com/belingud/yaicli/commit/4eed7d85abf3a75766e015533682beb2998f8c3e)) - Belingud

### ⚙️ Miscellaneous Tasks

- update yaicli version to 0.0.6 and CHANGELOG - ([563a468](https://github.com/belingud/yaicli/commit/563a4681c1a2e96a0609f2bd9822410567c4d0d0)) - Belingud


---
## [0.0.6](https://github.com/belingud/yaicli/compare/v0.0.5..v0.0.6) - 2025-04-03

### 🚜 Refactor

- update environment variable names and remove max_tokens - ([3abba5f](https://github.com/belingud/yaicli/commit/3abba5fe189b3de0d005907e159a46291a69636f)) - Belingud
- simplify config handling and remove DEFAULT_MODE - ([3439eda](https://github.com/belingud/yaicli/commit/3439eda71fdb24816de9c61c7ccee389e32c53b2)) - Belingud

### ⚙️ Miscellaneous Tasks

- update CHANGELOG and uv.lock for version 0.0.5 - ([d5abef4](https://github.com/belingud/yaicli/commit/d5abef4b602355fe472abaecd07f2701e8a38e4b)) - Belingud


---
## [0.0.5](https://github.com/belingud/yaicli/compare/v0.0.4..v0.0.5) - 2025-04-02

### 🚜 Refactor

- rename ShellAI to YAICLI and update related tests - ([2284297](https://github.com/belingud/yaicli/commit/2284297d018851abcb74f01064554b00df821301)) - Belingud

### 📚 Documentation

- update README with detailed project information and usage instructions - ([c71d50c](https://github.com/belingud/yaicli/commit/c71d50c9d232c47a3cdbe035d03c1f4a0dbbe7d2)) - Belingud

### ⚙️ Miscellaneous Tasks

- update yaicli version to 0.0.4 - ([03cdedb](https://github.com/belingud/yaicli/commit/03cdedb38465adcf4fc10d4379b2d939daf22d9d)) - Belingud


---
## [0.0.4](https://github.com/belingud/yaicli/compare/v0.0.3..v0.0.4) - 2025-04-02

### 🚜 Refactor

- simplify multi-line statements for better readability - ([4870bb7](https://github.com/belingud/yaicli/commit/4870bb7460682791ca79bbe2bcc0cef94bf51c26)) - Belingud
- rename ShellAI to yaicli and improve CLI help handling - ([dad0905](https://github.com/belingud/yaicli/commit/dad090540a7c1f8c8b30e3c688643a76e504b0c0)) - Belingud

### ⚙️ Miscellaneous Tasks

- update yaicli version to 0.0.3 - ([a689a02](https://github.com/belingud/yaicli/commit/a689a02b1c5e0cb278484267ef71f5f3acec8203)) - Belingud


---
## [0.0.3](https://github.com/belingud/yaicli/compare/v0.0.2..v0.0.3) - 2025-04-02

### 🚜 Refactor

- **(changelog)** switch from git log to git cliff for changelog generation - ([242a51d](https://github.com/belingud/yaicli/commit/242a51d93a25675041a7fe19c4a0db1c7c12a663)) - Belingud
- update CLI assistant description and error handling - ([1a8bcdc](https://github.com/belingud/yaicli/commit/1a8bcdc86c72a75259d266291bc9e5350fc81f61)) - Belingud
- fix spacing in clean target and simplify build target - ([2a1050e](https://github.com/belingud/yaicli/commit/2a1050e7a9eea8753c164553b13796e5510b7965)) - Belingud


---
## [0.0.2] - 2025-04-02

### ⛰️  Features

- enhance OS detection and LLM API request handling - ([8c00de0](https://github.com/belingud/yaicli/commit/8c00de099e1c75fedcdd33e9d7e0443818538059)) - Belingud
- add new dependencies and configurable API paths - ([3be3f67](https://github.com/belingud/yaicli/commit/3be3f67b3bd9645a9a8c9909be0e5542612c1c71)) - Belingud

### 🚜 Refactor

- **(config)** migrate config from JSON to INI format and enhance error handling - ([f556872](https://github.com/belingud/yaicli/commit/f556872fdb521adf8e20da6498fdaac26998a5b7)) - Belingud
- update config path to reflect project name change - ([e6bf761](https://github.com/belingud/yaicli/commit/e6bf761aa0fae20b643848c586c6dc55d6f324fb)) - Belingud
- rename project from llmcli to yaicli and update related files - ([cdb5a97](https://github.com/belingud/yaicli/commit/cdb5a97d06c9f042c1c8731c8f11a4a7284783f0)) - Belingud
- rename project from shellai to llmcli and update related files - ([db4ecb8](https://github.com/belingud/yaicli/commit/db4ecb85236b72fd7536c99b21d210037c09889e)) - Belingud
- reorganize imports and improve code readability - ([0f52c05](https://github.com/belingud/yaicli/commit/0f52c05918d177d4623ff2f07aff2fc2e3aa9e91)) - Belingud
- migrate llmcli to class-based ShellAI implementation - ([2509cba](https://github.com/belingud/yaicli/commit/2509cba5cad7c8626f794d88d971fff7eea9a404)) - Belingud

### Build

- add bump2version for version management - ([de287f1](https://github.com/belingud/yaicli/commit/de287f1262eae64ae5fd0cb634dea93762a17282)) - Belingud


