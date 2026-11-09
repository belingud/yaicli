# Feature Spec Writing Convention

> **Rule**: a feature spec must let a reader *see* the feature, not only read about it. Every PRD,
> OpenSpec proposal/spec delta, or plan that introduces user-visible behavior MUST contain a
> **Feature examples** section covering three things:
>
> 1. **Concrete UI** — the feature as it actually renders (verbatim terminal blocks, layouts, output
>    samples), including the exact entry point.
> 2. **Presentation form** — which channel carries what (stdout/stderr), formatting, TTY vs
>    non-TTY, machine modes.
> 3. **Logic** — triggers, precedence, state, edge cases and error paths, with the exact user-facing
>    message and exit code.
>
> A spec that says *what to do* without an example of *what it looks like* and *when it happens* is
> incomplete. It must not pass the planning gate, and the implementation must not start from it.

## Why

- **The spec is the only shared artifact between the user and the agents building the feature.** In
  this repo several sessions/agents may work at once; each one reads the same prose differently
  unless an example pins it down. "Supports JSON output" or "improve the prompt experience" can be
  implemented a dozen different ways.
- **Examples surface ambiguity before code is written.** Layout, channel, precedence and error text
  are exactly where implementers guess wrong, and where the user notices the mistake only after the
  feature ships.
- **The example is the acceptance demo.** The reviewer compares the implementation against the spec's
  rendered blocks; "looks about right" becomes "matches or does not".
- **Writing it is cheap; discovering it missing is not.** One terminal block prevents a rework cycle.

## Where this applies

| Artifact | Path | Requirement |
| --- | --- | --- |
| Trellis PRD | `.trellis/tasks/<task>/prd.md` | `## Feature examples` section with UI + presentation + logic |
| Trellis design / implement doc | `.trellis/tasks/<task>/design.md`, `implement.md` | same, for the part of the design that is user-visible |
| OpenSpec proposal | `openspec/changes/<change>/proposal.md` | same, under "What Changes" |
| OpenSpec capability spec | `openspec/specs/<capability>/spec.md` | every requirement carries at least one concrete rendered example in addition to its scenarios |
| Standalone plan | `plans/*.md` | same, when the plan introduces user-visible behavior |
| User docs (`docs/`, `README.md`) | not a spec — but the docs page is what the example must match | |

Exempt: internal refactors, performance work and bug fixes with no observable change. As soon as the
user can see a different screen, output, prompt, message or exit code, examples are required. When
unsure, treat it as user-visible.

## Required content

### 1. What the feature is

One short paragraph + the exact entry point: command line, flag, slash command, keybinding, config
key or environment variable. If the feature changes existing behavior, add a **Before → After**
comparison.

### 2. Concrete UI / output examples (at least one)

- Show the exact input verbatim: the command line, the keys pressed, the stdin content.
- Show the rendered result as a fenced `text`/`console` block: borders, icons, indentation, prompt
  characters, blank lines — everything the user sees. Name colors/styles when they carry meaning
  (e.g. `dim`, `red`, `bold`), because they survive as text.
- REPL/prompt features: include the full prompt/status lines as rendered and state where the cursor
  ends up if layout is part of the request.
- Machine output: paste the actual JSON / NDJSON / text, not a prose description of the schema.
- When TTY and non-TTY differ, show both blocks.
- For changed UX, pair **Before** and **After** blocks.
- Plain text blocks only — no screenshots as the sole evidence; text is diffable and searchable.

### 3. Presentation form

- **Channel**: which stream carries the result, and which carries labels, warnings, tool previews and
  errors (in this project: result on stdout, diagnostics on stderr in machine modes).
- **Formatting**: plain text vs Rich panel/Markdown vs machine mode; colors/styles; wrapping,
  truncation and width handling; paging or alt-screen.
- **Mode behavior**: `--quiet`, `-p/--print`, `--output-format`, redirected stdin/stdout,
  interactive vs non-interactive approval.

### 4. Logic

- **Triggers**: what activates it — runtime mode, flag, config key, TTY state, model/tool event.
- **Precedence**: explicit order between CLI flags, environment variables, config file and defaults;
  first-match order; how it composes with existing features.
- **State**: per call / per turn / per session / persisted to disk; what is recorded where; whether a
  restart is required for a change to take effect.
- **Edge cases and errors**: empty input, denial, interruption, provider error, invalid value — the
  exact user-facing message and the exit code. "Handles errors gracefully" is not an example.
- **Side effects**: files written, network calls, permissions recorded.

### 5. Acceptance

List the commands a reviewer will run and the observable result of each, plus the tests that will
assert it. Every example above should map to at least one acceptance criterion.

## Template

Copy this skeleton into the PRD; delete sections that do not apply only when the spec is genuinely
non-user-visible (then also record why).

````markdown
## What the feature does

<one paragraph: what it does, for whom, from where it is invoked: `ai --flag ...`, `/command`, `Ctrl-X`>

## Feature examples

### Example 1 — primary success path

Input:

```bash
$ ai ...
```

Rendered UI / output:

```text
<verbatim terminal rendering, JSON, prompt lines...>
```

### Example 2 — TTY difference / non-interactive path / error path

Input:

```bash
$ ...
```

Rendered UI / output (stderr marked):

```text
<...>
```

## Presentation form

- Result channel: stdout / stderr — ...
- Formatting: ...
- Non-TTY / machine mode: ...
- Interactive vs non-interactive: ...

## Logic

- Trigger: ...
- Precedence: `<flag>` > `<env>` > `<config>` > default; danger/readonly rules first.
- State: ...
- Errors and exit codes: <message> → exit `<n>`; ...
- Side effects: ...

## Acceptance

- [ ] `...` renders as in Example 1
- [ ] `...` falls back to `...` (Example 2)
- [ ] test(s) asserting ...
````

## Worked examples

These are abridged; the full contract lives in the linked docs page. Note the shape: what it looks
like, where it is printed, what decides it.

### A. Terminal UI — tool-call confirmation (`docs/usage/permissions.md`)

```text
╭─ Confirm tool call ────────────────────────╮
│ execute_shell_command                      │
│ risk: exec                                 │
│ command: du -sh .                          │
│ dangerous: no                              │
╰────────────────────────────────────────────╯
Execute tool? [y]once, [a]session, [A]always, [n]o:
```

- **UI**: a titled Rich panel shows the *normalized* arguments (a diff excerpt for edits, target path
  and create/overwrite for writes), followed by a one-line prompt. The preview must match what will
  actually execute; a mismatch is a bug.
- **Presentation**: interactive TTY only; the prompt is inline, not a panel. Non-interactive runs
  never prompt — unapproved calls are denied and the model receives a structured refusal.
- **Logic**: `y` = this call, `a` = this tool for the session, `A` = persist to
  `tool_permissions.json`, `n` = deny; Ctrl+C/EOF counts as deny. Gate order: persistent/session rules
  → `--allowed-tools` → `--yes` → prompt/deny. Danger classification is evaluated first, before the
  mode, in every mode; `TOOL_POLICY` (`readonly`/`standard`/`trusted`) then caps or floors the outcome.

### B. Machine output — `--output-format json` (`docs/usage/headless.md`)

Input:

```bash
$ ai -p "List the files changed in the last commit" --json | jq -r .content
```

Output (stdout, abridged — one object, then newline):

```json
{"content": "The last commit changed ...", "tool_calls": [], "usage": {"prompt_tokens": 1234, "completion_tokens": 456, "total_tokens": 1690, "cost_usd": 0.0077}, "finish_reason": "stop", "model": "gpt-4o-mini", "provider": "openai", "error": null, "exit_code": 0}
```

- **Presentation**: exactly one JSON object on stdout; warnings, trim notices, tool previews and errors
  go to stderr; no Live region, Markdown or ANSI in machine mode.
- **Logic**: `--json` implies `--output-format json` and a one-shot run (`--chat` is ignored with a
  stderr warning); usage error → exit `2`; auth/provider failure → stderr + exit `1`; interruption →
  exit `130` and `error.kind = "interrupted"`. Failures that happen *before* a result exists emit no
  JSON object at all.

## Anti-patterns

| Don't write | Write instead |
| --- | --- |
| "Supports JSON output." | The invocation, a real JSON object, the stdout/stderr split, and the exit codes (worked example B). |
| "Improve the prompt; put the model info on top." | Before/After terminal blocks showing both prompt lines, which parts are dim, and where the cursor lands. |
| "Shows an error to the user." | The exact stderr line, the exit code, and what the non-interactive path prints instead. |
| "Precedence is handled normally." | The literal chain, e.g. `--flag` > `YAI_*` > `config.ini` > default, plus which rule wins first. |
| An invented example ("output looks roughly like this"). | A verified example: run the command, or lift it from a test; mark it `proposed` while unimplemented. |
| A link to a doc page as the only detail. | The essential rendered block inline, with the link for the full contract. |
| A requirement list with no rendered example. | Each requirement gets at least one concrete scenario with expected output. |

## Ready gate

Before a spec is ready for review or implementation:

- [ ] The feature has an exact entry point, and a novice reader can picture the UI from the spec alone.
- [ ] At least one primary success example is rendered verbatim (terminal block / JSON / prompt lines).
- [ ] TTY vs non-TTY, interactive vs non-interactive, and machine modes are covered where they differ.
- [ ] The error/denial/edge path shows the exact message and exit code.
- [ ] Precedence, state/persistence, and side effects are explicit — no "and so on".
- [ ] Each example is verified against code/tests or clearly marked `proposed`.
- [ ] Every example maps to an acceptance item, and the docs page planned for the change will match it.
