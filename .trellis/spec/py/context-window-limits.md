# 上下文窗口与预算规范（v0.23 K22，约束性）

> 适用：改动 `yaicli/model_limits.py`、`yaicli/tokens.py` 的窗口/预算逻辑、`llms/client.py` 的预算执行与超窗自愈、
> provider 的 `model_limits()` 钩子、`/context` 的预算展示、或新增相关配置键时，**必须**遵守本文件的 MUST 规则。
> 需求与验收样例见 `.trellis/tasks/11-11-k22-model-context-limits/prd.md`；设计见同目录 `design.md`。

## 1. 单一事实来源

- MUST：模型窗口的解析逻辑只存在于 `yaicli/model_limits.py`。其他模块不得维护新的窗口表、不得内联 `128000`/`200000`
  之类的窗口字面量（`DEFAULT_CONTEXT_WINDOW` 常量除外）。
- MUST：内置目录快照是 `yaicli/data/model_limits.json`，由 `scripts/gen_model_limits.py` 生成；不得在代码里散落大表。
- MUST：`tokens.py` 只负责"估算/预算/裁剪"，窗口与预算公式的解析委托 `model_limits`。

## 2. 解析优先级（不可重排）

```
user（MODEL_CONTEXT_WINDOWS） > learned（400 报错学习） > metadata（provider 元数据）
> catalog（内置快照） > heuristic（家族前缀） > default（128k + 警告）
```

- MUST：每一层结果都带 `source`，取值为 `user|learned|metadata|catalog|heuristic|default` 之一；可带 `detail` 说明来源。
- MUST：逐层短路。用户显式配置永远最高优先级；学习值只覆盖静态层，不覆盖用户配置。
- MUST：`source == "default"` 才算"未知窗口"；`heuristic`/`catalog` 不算。
- MUST：未知窗口（model 非空）在**每个 `LLMClient` 会话**向 stderr 警告一次，且消息包含可复制的覆盖示例；
  空模型名不警告。禁止静默使用默认值。
- MUST：模型名匹配使用 **provider 作用域 + 最长前缀**，禁止"首个 substring 命中"。归一化必须去 provider 前缀、
  日期/`@date` 后缀、OpenRouter `:free|:batch|:extended|:nitro|:online`、`[1m]` 变体标记（并映射到 1M）。
- MUST：Ollama provider 在无目录/元数据命中时回退 `OLLAMA_DEFAULT_CONTEXT_WINDOW`（8192），不得先匹配通用家族前缀
  （如 `qwen`→131072）；**不得**把 `NUM_CTX`/`num_ctx` 当作有效窗口（用户决策：代码暂不动，但新解析忽略它）。

## 3. 预算公式

```python
budget = max(1, min(window, max_input_if_any) - MAX_TOKENS - CONTEXT_SAFETY_TOKENS)
```

- MUST：`CONTEXT_BUDGET_TOKENS > 0` 时逐字覆盖上面结果（兼容旧行为、用户回退手段）。
- MUST：`budget >= 1`；`remaining = max(0, budget - total)`；百分比 = `total / budget * 100`。
- MUST：`CONTEXT_BUDGET_RATIO`（旧 70%）不再参与计算；不得重新引入固定比例。
- MUST：`MAX_TOKENS` 仍是输出上限，预算公式只把它作为预留项，不替用户改写 provider 参数。

## 4. provider 元数据钩子

- `Provider.model_limits(model) -> Optional[ModelLimits]`，基类返回 `None`。
- MUST：懒加载——只在预算解析需要且前面层未命中时调用；不得在启动/构造 provider 时调用。
- MUST：单次尝试、超时 ≤2s（`httpx` 显式 `timeout`）；任何异常/超时/格式不符都返回 `None` 静默回退。
- MUST：空结果必须做**进程内负缓存**（默认 `METADATA_MISS_TTL_SECONDS=300s`），否则离线/无元数据的 provider 会在每轮请求重复探测（最坏 +2s/轮）。
- MUST：`ENABLE_MODEL_METADATA=false` 时客户端完全跳过钩子。
- MUST：钩子内不打印、不缓存、不改 provider 状态；缓存统一在 `model_limits`。
- MUST：三个已实现源——OpenRouter `/models`（`context_length`、`top_provider.max_completion_tokens`）、
  Gemini `models.get`（`input_token_limit`/`output_token_limit`）、Ollama `/api/show`（`model_info.*.context_length`）。

## 5. 超窗学习

- MUST：`errors.parse_context_limit(exc)` 从错误文本提取真实上限；支持 OpenAI/Anthropic/Gemini/Ollama 常见措辞，
  提取不到数字返回 `None`。
- MUST：客户端仅在 `ErrorKind.CONTEXT_LENGTH` 且解析到数字时学习；学习发生在裁剪前，即使无轮组可裁也保留学习值。
- MUST：学习值按 `(provider, base_url, normalized model)` 记录，内存即时生效 + 磁盘缓存（TTL 30 天）。
- MUST：仍保持"一次请求只自愈重试一次"；学习后按新预算重裁，再重试。
- MUST：stderr 提示包含学习到的上限（见 PRD Feature example 4）。

## 6. 缓存

- 文件：`<config-dir>/cache/model_limits.json`（`const.get_config_dir()`，不硬编码 `~`）。
- MUST：元数据 TTL 7 天，学习值 30 天；过期即失效。
- MUST：`ENABLE_MODEL_LIMITS_CACHE=false` 时不读不写磁盘（内存 memo 仍可）。
- MUST：读写 best-effort：`OSError`/`JSONDecodeError` 静默；损坏文件可被重建；写入 0600（best-effort）。
- MUST：测试不写真实 config 目录（`tmp_path`/patch），且不联网。

## 7. 展示约定

- `/context`（stdout）必须展示：`window (source [· detail])`、`role prompt`、`project ctx`、`/add context`、
  `history (tool output ...)`、`overhead`、`total / budget (percent)`、`remaining`、`reserve (MAX_TOKENS + safety)`。
- MUST：`overhead` 行展示 `ContextUsage.overhead_tokens`（= 实际计入 total 的 `REQUEST_OVERHEAD_TOKENS`，
  无 history/project/extra 时为 `0`）；各 bucket 相加必须等于 total。
- MUST：裸 `/context` 只输出 usage 块 + 旧 `/add` 列表，不得重复打印 subcommand 提示；子命令提示仅在未知子命令
  的错误路径输出（`Available: list, clear, add <path>, remove <path>, budget`）。
- 未知窗口的 window 行必须写明 `source: default` 与覆盖方法。
- 警告/诊断一律 stderr（`get_error_console()`），不得污染 stdout/JSON 输出；`/context` 仅 REPL，机器模式不新增输出。
- 数字用千分位；缩进 2 空格；不要新增 Rich 表格（保持纯文本可断言）。

## 8. 配置与文档

- 新增键 MUST 同时进入：`const.DEFAULT_CONFIG_MAP`（value/env_key/type）、`const.DEFAULT_CONFIG_INI`、
  `docs/usage/configuration.md`（参考表 + 文件结构 snippet）、`README.md` 参考表 —— `tests/test_docs_config.py`
  是 drift guard，必须绿。
- MUST：新键沿用 `YAI_*`；`MODEL_CONTEXT_WINDOWS` 为 JSON dict（键支持 `model`、`provider:model`、`provider/model`；
  值支持 int 或 `{window,max_input,max_output}`）。

## 9. 质量与测试

- `model_limits.py` MUST 保持 stdlib-only 叶子模块（可懒 import `const.get_config_dir`），不得 import rich/typer/SDK/cfg。
- MUST 不新增依赖（httpx 已在 base）。
- 测试 MUST：`tests/test_model_limits.py` 覆盖归一化/最长前缀/六层优先级/缓存 TTL+开关/损坏缓存/预算公式/
  注入 fetcher；provider 钩子、超窗学习、`/context` 各有测试；全量 `uv run pytest` + `ruff check --no-fix yaicli tests` 绿。
- 禁止反模式：在 provider 内缓存窗口；在 `completion()` 里打印窗口警告；用固定 70% 回填；把学习值写成用户配置；
  请求路径上同步下载目录。

## 10. 与既有规范的关系

- 配置键流程：`.trellis/spec/py/config-and-context.md` → "Adding or Changing a Config Key"（本规范补充 keys 清单）。
- Provider 契约：`.trellis/spec/py/provider-guidelines.md`（`model_limits` 是新增的可选钩子，抽象方法不增加）。
- 用户可见行为：`.trellis/spec/repo/feature-spec-writing.md`（PRD 的 `## Feature examples` 为准）。
