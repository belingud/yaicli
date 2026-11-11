# K22: 模型上下文窗口解析与预算修正

> 版本：v0.23.0（roadmap 2026-11-11 重排：K22 提前，lite transport 顺延 v0.24）
> 约束性 spec：[`.trellis/spec/py/context-window-limits.md`](../../spec/py/context-window-limits.md)

## Goal

让 YAICLI 在 30+ provider 下都能用**正确的模型上下文窗口**计算每次请求的输入预算，并把"这个数字从哪来"暴露给用户；请求被 provider 以超窗拒绝后，能从错误信息里**学习真实上限**并修正后续预算。替换当前"首个 substring 命中 + 固定窗口 × 70%"的近似。

## Background（现状问题）

| 问题 | 证据 |
|---|---|
| 窗口表按"第一个 substring"匹配，顺序脆弱 | `gpt-4-32k` → `gpt-4` = 8192（实际 32768）；`o1-mini` → `o1` = 200000（实际 128000）；Ollama `qwen2.5:7b` 先命中 `qwen` = 131072，走不到本地 8k 回退 |
| 未知模型静默按 128k 继续跑 | `tokens.get_context_window("totally-unknown-model") == DEFAULT_CONTEXT_WINDOW`，无提示、无覆盖指引 |
| 预算固定 70% 窗口，浪费输入空间 | `gpt-4o` = 89,600，而 `MAX_TOKENS` 默认仅 1,024；实际可用输入约 126k |
| provider 上报的真实 usage 不参与预算 | `UsageTracker`/`last_usage` 只用于成本展示（`/cost`、每轮 tokens 行） |
| 无每模型/每 provider 覆盖配置 | 用户只能通过 `CONTEXT_BUDGET_TOKENS`（全局）粗调 |
| provider 元数据未利用 | OpenRouter `/models` 有 `context_length`、Gemini `models.get` 有 `inputTokenLimit`、Ollama `/api/show` 有 `model_info.*.context_length` |
| 400 超窗只盲裁一次 | `client._heal_context_length` 不解析真实上限，不学习，不修正后续请求 |

## Scope

**In**

1. 新 `yaicli/model_limits.py`（stdlib-only 叶子模块）：分层解析 + 预算计算 + 学习/缓存 + 内置目录读取。
2. 配置键：`MODEL_CONTEXT_WINDOWS`、`ENABLE_MODEL_METADATA`、`CONTEXT_SAFETY_TOKENS`、`ENABLE_MODEL_LIMITS_CACHE`。
3. provider 钩子 `model_limits(model)`：OpenRouter / Gemini / Ollama 三个元数据源，其余默认 `None`。
4. `tokens.resolve_context_budget()` 改为新公式；`get_context_window()` 委托解析器。
5. `errors.parse_context_limit()` + `LLMClient` 超窗学习与按新预算重裁。
6. `/context` 输出 window/source/reserve 与系统/项目上下文/持久上下文的分类。
7. 内置目录 `yaicli/data/model_limits.json` + 生成脚本 `scripts/gen_model_limits.py`。
8. 文档：`docs/usage/context-limits.md`、`docs/usage/configuration.md`、`README.md`（与 `tests/test_docs_config.py` 同步）。
9. 约束写入 `.trellis/spec/py/context-window-limits.md`。

**Out（本任务不做）**

- 不用 `NUM_CTX` 作为有效窗口（用户决策：Ollama 代码/文档暂不动，新设计忽略它；`/api/show` 返回的模型上下文上限才是权威值）。
- 不做 LLM 摘要压缩（auto-compact）、microcompact、子代理隔离（属于 K02 后续/其他路线图项）。
- 不改变 provider 请求参数语义（`MAX_TOKENS` 仍是输出上限，不替用户改写）。
- 不做运行时下载目录（目录是随包快照；生成脚本在开发/发布时手动跑）。
- 不新增依赖（`httpx` 已有）。
- 不把窗口写进 headless JSON `usage` 对象（后续按需扩展）。

## Requirements

| ID | 要求（MUST） |
|---|---|
| R1 | 解析优先级固定：用户配置 → 报错学习 → provider 元数据 → 内置目录 → 家族启发 → 默认值；每个结果必须携带 `source`（`user\|learned\|metadata\|catalog\|heuristic\|default`）与可选 `detail` |
| R2 | 预算公式：`budget = max(1, min(window, max_input) - MAX_TOKENS - CONTEXT_SAFETY_TOKENS)`；`CONTEXT_BUDGET_TOKENS > 0` 时逐字覆盖（兼容旧行为） |
| R3 | 模型名归一化：小写、去 provider 前缀、去日期/`@date` 后缀、去 OpenRouter `:free\|:batch`、去 `[1m]`（标记 1M）；匹配必须是 provider 作用域 + **最长前缀**，禁止"首个 substring 命中" |
| R4 | 未知窗口（`source == "default"` 且 model 非空）时，每个 `LLMClient` 会话向 stderr 警告一次，并给出可复制的覆盖示例；不得静默 |
| R5 | 元数据探测必须懒加载、单次尝试、≤2s、异常静默回退；`ENABLE_MODEL_METADATA=false` 时完全不探测；探测不得阻塞启动 |
| R6 | 捕获 context-length 错误时解析真实上限并记录（内存 + 磁盘缓存，按 provider+base_url+模型）；随后按新预算重裁并保持"只重试一次" |
| R7 | 缓存文件 `<config-dir>/cache/model_limits.json`：元数据 TTL 7 天、学习值 30 天；写入 best-effort（OSError 不崩溃）；`ENABLE_MODEL_LIMITS_CACHE=false` 时不读写磁盘；损坏 JSON 忽略并重建 |
| R8 | 内置目录 `yaicli/data/model_limits.json` 随包发布（`version`/`generated_at`/`sources`/`exact`/`providers`），可被用户配置与学习值覆盖；生成脚本 `scripts/gen_model_limits.py` 可从 OpenRouter/LiteLLM/models.dev 快照生成 |
| R9 | `/context` 展示 `window (source ...)`、`role prompt`、`project ctx`、`/add context`、`history (tool output ...)`、`total / budget (percent)`、`remaining`、`reserve (MAX_TOKENS + safety)` |
| R10 | 4 个新配置键进入 `DEFAULT_CONFIG_MAP` + `DEFAULT_CONFIG_INI` + docs/README 参考表（drift guard 必须绿） |
| R11 | `model_limits.py` 保持 stdlib-only 叶子模块；不新增依赖；请求路径最多少一次 2s 网络探测（有缓存后为 0） |
| R12 | 测试不得联网、不得读写真实 `~/.config/yaicli`；provider 元数据钩子全部用 mock 覆盖 |

## Feature examples

> 本仓库的 PRD 必须让读者"看到"功能。以下为逐字终端/输出块，实现必须匹配。

### 1. `/context`（已知模型，元数据来源）

命令：REPL 输入 `/context`（或 `/ctx`、`/context budget`）。

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

### 2. `/context`（未知模型，默认来源）

```text
Context usage (estimated):
  window        : 128,000 tokens (source: default · assumed for unknown model; set MODEL_CONTEXT_WINDOWS to override)
  role prompt   : 12 tokens
  project ctx   : 0 tokens
  /add context  : 0 tokens
  history       : 2,175 tokens (tool output 1,148)
  overhead      : 3 tokens
  total         : 2,190 / 125,952 tokens (1.7%)
  remaining     : 123,762 tokens
  reserve       : 2,048 (MAX_TOKENS 1,024 + safety 1,024)
  Use /compact [keep_rounds] to drop older turn groups.
```

### 3. 未知模型首次请求警告（stderr）

触发：`source == "default"` 且 model 非空；每个 `LLMClient` 只在第一次请求前打印一次。stderr，dim yellow。

```text
Context window for model "my-gateway-model" is unknown; assuming 128,000 tokens (source: default).
Set MODEL_CONTEXT_WINDOWS={"my-gateway-model": 200000} or CONTEXT_BUDGET_TOKENS to override.
```

### 4. 超窗自愈：学习真实上限（stderr）

触发：provider 返回 context-length 400 且错误文本带数字上限（如 `maximum context length is 200000 tokens`）。仍只重试一次。

Before（现状）：

```text
Provider rejected the request as too long; dropped 1 older message(s) and retrying once (210,000 -> 180,000 est. tokens).
```

After（学习后）：

```text
Provider rejected the request as too long; learned the real context limit (200,000 tokens), dropped 1 older message(s) and retrying once (210,000 -> 197,952 est. tokens).
```

### 5. 配置覆盖（config.ini）

```ini
[core]
# JSON：键支持 "model" / "provider:model" / "provider/model"；值可为整数或对象
MODEL_CONTEXT_WINDOWS={"my-gateway-model": 200000, "openrouter/anthropic/claude-sonnet-5.5": 1000000, "ollama/qwen2.5:7b": {"window": 32768, "max_output": 4096}}
ENABLE_MODEL_METADATA=true
CONTEXT_SAFETY_TOKENS=1024
ENABLE_MODEL_LIMITS_CACHE=true
```

覆盖优先级示例：同一模型同时存在用户配置与目录条目 → `/context` 显示 `source: user`；删除配置后变为 `source: catalog`。

### Presentation form

| 输出 | 通道 | 格式 | TTY | 非 TTY / 机器模式 |
|---|---|---|---|---|
| `/context` 明细 | stdout | Rich 纯文本、2 空格缩进、数字千分位 | REPL 可用 | `/context` 仅 REPL，headless 无此命令 |
| 未知窗口警告 | stderr | 纯文本 2 行、`dim yellow` | 打印一次 | 同样打印一次（stderr） |
| 超窗学习提示 | stderr | 纯文本 1 行、`yellow` | 打印 | 打印 |
| 预算裁剪提示 | stderr | 保持现有 `Context over budget: ...` | 打印 | 打印 |

`--output-format json` / `stream-json` 的 payload 本任务**不变**；警告只走 stderr，不影响 stdout 可解析性。

### Logic（触发器 / 优先级 / 状态 / 边界）

1. 解析在每次预算计算时触发（客户端每轮 `_enforce_context_budget` 前；`/context` 时独立计算）。进程内 memo 保证只探测一次。
2. 优先级逐层短路：`user > learned > metadata > catalog > heuristic > default`。某层命中即返回，不再往下。
3. `source=="default"` 才警告；`heuristic`/`catalog` 不算未知。`/context` 的 `total` 行前置一行 `overhead`（`REQUEST_OVERHEAD_TOKENS=3`，仅当存在 history/project/extra 时计入），保证各 bucket 相加等于 total；裸 `/context` 不再打印 subcommand 提示（提示仅出现在未知子命令的错误路径）。
4. 元数据探测仅在 `ENABLE_MODEL_METADATA` 为真、且前面层未命中、且该 `(provider, base_url, model)` 未缓存时发生；任何异常/超时都静默跳到下一层。
5. 学习值写入后立即生效：本会话后续预算、`/context`、`/compact` 都用新窗口；磁盘缓存供下次会话使用。
6. 预算保护：`remaining = max(0, budget - total)`；`budget` 最小 1，避免除零/负预算。
7. 空模型名（如测试/未配置）：不警告，按默认窗口计算。
8. 单轮即超窗（无可裁轮组）：仍记录学习值；本次报可操作错误（现有行为），不做无限重试。

## Acceptance criteria

- [x] `gpt-4o` 默认预算 ≥ 120,000（旧值 89,600）；`CONTEXT_BUDGET_TOKENS=5000` 仍逐字生效。
- [x] `get_context_window("gpt-4-32k") == 32768`、`("o1-mini") == 128000`、`("qwen2.5:7b", provider="ollama") == 8192`（无目录/元数据时）。
- [x] `MODEL_CONTEXT_WINDOWS` 三种键写法都生效；用户配置覆盖目录；`source` 正确。
- [x] 未知模型：首轮 stderr 警告一次（第二次请求不再打印），消息含覆盖示例。
- [x] OpenRouter/Gemini/Ollama 元数据钩子：mock 成功时 `source=="metadata"`；mock 抛错/超时静默回退。
- [x] 400 超窗带数字上限：学习 + 重裁 + 只重试一次；stderr 提示含学习到的上限；后续请求预算使用新值。
- [x] 缓存：TTL 生效、`ENABLE_MODEL_LIMITS_CACHE=false` 不落盘、损坏 JSON 不崩溃。
- [x] `/context` 输出匹配 Feature examples（含已知/未知两种 window 行）。
- [x] `tests/test_model_limits.py` 新增；`tests/test_context_budget.py`、`tests/test_errors.py`、`tests/llms/test_client.py`、provider 测试、`tests/test_command_handler.py`、`tests/test_docs_config.py` 全绿。
- [x] `uv run pytest` 全绿；`uv run ruff check --no-fix yaicli tests` 干净。
- [x] 文档三处更新（context-limits / configuration / README），`mkdocs build --strict`（如环境允许）通过。

## Non-goals

见 Scope/Out。特别是：本轮**不**用 `NUM_CTX`、**不**做摘要压缩、**不**改 `MAX_TOKENS` 语义、**不**引入 `tiktoken`。
