# YAICLI: Your AI Assistant in Command Line

<p align="center">
  <img src="./assets/artwork/logo.png" width="150" alt="YAICLI Logo" />
</p>

YAICLI is a powerful yet lightweight command-line AI assistant that brings the capabilities of Large Language Models (LLMs) like GPT-5.2 directly to your terminal. Interact with AI through multiple modes: have natural conversations, generate and execute shell commands, or get quick answers without leaving your workflow.

**Supports both standard and deep reasoning models across all major LLM providers.**

## ⚡ Agent Quick Start (3 steps)

**1. Install and give it a key**

```bash
pip install yaicli

# either export a key for the default OpenAI provider ...
export YAI_API_KEY="sk-..."
# ... or run a real command once (e.g. `ai "hi"`) and edit the config file
ai --version
```

**2. Give the agent a real task**

```bash
ai "Use your tools to find the 3 largest files in this repository and write a summary to REPORT.md"
```

The 12 built-in tools are loaded directly from the package, so the model can call them on the
very first run — there is no `--install-functions` setup step.

**3. Approve tool calls** — allow once (`y`), for the session (`a`), permanently (`A`), or deny
(`n`). See [Permissions & Safety](usage/permissions.md) for the one safety rule explained
properly.

## ✨ Key Features

### 🤖 Agent Loop with Built-in Tools

- **Multi-step tasks**: the model plans, calls tools, reads results and continues
- **12 built-in tools**: filesystem read/write/edit/search/info, image reading, shell execution,
  web fetch, web search and weather
- **Project-aware**: `.yaicli.md` / `AGENTS.md` / `CLAUDE.md` are loaded into the system prompt
  automatically — see [Project Context](usage/project-context.md)
- **MCP (optional)**: connect external MCP servers as additional tools

### 🛡️ Safe by Default

- **Approval prompt** for every tool call, with risk classes (`read`/`write`/`network`/`exec`)
- **Danger classification** for shell commands and an **audit log** of every decision
- **Allow rules** by tool name, shell argv prefix or file path glob
- **Workspace-confined writes**: built-in file tools only touch files inside `WORKSPACE_ROOT`, back
  up changes to `.yaicli-backups/`, refuse protected paths, and `/undo` reverts the last change —
  see [Workspace Safety](usage/workspace-safety.md)
- **Guarded shell**: timeout, process-group kill, filtered environment, workspace-confined `cwd`

### 📜 Headless & Scriptable

- **`-p/--print`**, **`-q/--quiet`**, **`--output-format json|stream-json`**
- Clean stdout (result only) and stderr (logs/warnings), deterministic exit codes
- **`--yes`**, **`--allowed-tools`**, **`--fail-on-tool-denied`** for non-interactive runs

### 🧠 Context Economy

- **Tool-output truncation** with full output spilled to disk
- **Token budget** and turn-group-aligned trimming (no orphan tool messages)
- **Context-length self-heal** and **`/compact`**

### 💻 Terminal Experience & Compatibility

- Real-time streaming, syntax highlighting, file `@` references and image input
- **Per-project chat sessions** with metadata and `--resume` — see
  [Chat Sessions & Resume](usage/sessions.md)
- 30+ providers and any OpenAI-compatible endpoint — a compatibility layer, not the headline

## 🪶 Lightweight & scope

| Metric (baseline = v0.18, macOS sandbox) | Value |
| --- | --- |
| `ai --version` startup (P50) | ≈474–504 ms baseline → **≈40–45 ms** (v0.19 fast path) |
| `--help` startup (P50) | ≈519–568 ms baseline → **≈450–500 ms** after the v0.20 lazy-import work (the CLI stack is no longer imported for help) |
| one-shot local overhead (`ai "hi"`, no network) | ≈1.5–1.6 s baseline → **≈1.6 s** in the same sandbox; prompt_toolkit is no longer imported, provider-SDK init (≈0.9 s) still dominates |
| REPL ready (first prompt) | ≈1.55–1.75 s baseline → **≈0.55–0.65 s** (the LLM client/SDK is constructed on the first request) |
| base install closure | **95 dists** (v0.19.1: 103): fetch/search/MCP stay in base, the boto3/botocore/google-auth cloud closure (~25–29 MB) is now opt-in via `[bedrock]`/`[vertex]` |
| idle RSS | ≈30 MB for `--version`; ≈65 MB for a REPL with the OpenAI SDK loaded |
| background processes / daemons | **none** |

> **Measurement caveat:** these numbers were measured on macOS inside a sandboxed benchmark
> environment, where file access is intercepted and absolute timings are inflated (expect 2–3×
> slower than a bare machine). Treat the *relative* deltas and proportions as the credible claim;
> absolute milliseconds will be re-measured on CI before they are used in release notes.

## 🔌 Compatibility

YAICLI supports 30+ provider keys — OpenAI, Anthropic, Gemini, Ollama, DeepSeek, Groq, Mistral and
more — plus any OpenAI-compatible endpoint via a custom `BASE_URL`. Provider support is a
compatibility layer: the agent loop and tooling are the same for every provider. See the
[provider overview](providers/overview.md) for the full matrix and per-provider setup.

## Quick Links

- [Agent Quickstart](getting-started.md)
- [Headless & Scripting](usage/headless.md)
- [Permissions & Safety](usage/permissions.md)
- [Workspace Safety](usage/workspace-safety.md)
- [Context & Limits](usage/context-limits.md)
- [Project Context](usage/project-context.md)
- [Chat Sessions & Resume](usage/sessions.md)
- [Installation](install.md)
- [Command Reference](usage/commands.md)
- [Configuration](usage/configuration.md)
- [Upgrade Notes](advanced/upgrade.md)
- [Contributing](contributing.md)
- [GitHub Repository](https://github.com/belingud/yaicli)
