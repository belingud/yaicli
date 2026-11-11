# K22 Implement — 执行计划

> 目标：按 [prd.md](./prd.md) 与 [design.md](./design.md) 落地；每个阶段结束必须跑对应验证命令。
> 分支：直接在 master 工作区完成（不提交，由用户决定）。回滚点 = 每个阶段一个可独立回退的文件集合。

## Phase 0 — 约束与规划产物（Lead）

- [x] roadmap：K22 列为 v0.23.0，lite transport 顺延 v0.24（`var/lightweight-audit/09-roadmap.md`）
- [x] Trellis 任务目录 + `prd.md` / `design.md` / `implement.md`
- [x] `.trellis/spec/py/context-window-limits.md`（MUST 规则）+ `.trellis/spec/py/index.md` 索引
- [x] `task.py start 11-11-k22-model-context-limits`

**gate**：spec 文件存在；PRD 有 `## Feature examples`；`task.json.status == in_progress`。

## Phase 1 — 核心模块（Lead，契约冻结）

文件：

- `yaicli/model_limits.py`（新增，stdlib-only）
- `yaicli/data/model_limits.json`（新增，目录快照）
- `scripts/gen_model_limits.py`（新增，快照生成）
- `tests/test_model_limits.py`（新增）

内容：`ModelLimits`、`normalize_model_name`、`parse_user_windows`、`get_context_limits`（六层 + memo + cache + 注入 fetcher）、`context_input_budget`、`record_learned_limit`、`clear_limit_cache`、`HEURISTIC_CONTEXT_WINDOWS`、目录加载。

**验证**：

```bash
uv run pytest tests/test_model_limits.py -q
uv run ruff check --no-fix yaicli/model_limits.py tests/test_model_limits.py
```

**gate**：新增测试全绿；接口与 design §2 一致（下游按此并行开发）。

## Phase 2 — 并行集成（3 个写入域，互不重叠）

### 2A 预算与配置（teammate: integration-budget）

文件：`yaicli/tokens.py`、`yaicli/const.py`、`tests/test_context_budget.py`（预算/窗口部分）

- `resolve_context_budget(config, model, provider)` 新公式；`get_context_window` 委托；删除 `CONTEXT_BUDGET_RATIO` 使用
- `estimate_context_usage` 新参数/`ContextUsage` 新字段（window_tokens/max_output_tokens/source/detail/extra_tokens/reserve_tokens）
- 4 个配置键进 `DEFAULT_CONFIG_MAP` + `DEFAULT_CONFIG_INI`（模板文案见 design §9）
- 更新 `tests/test_context_budget.py` 中窗口/预算/estimate 断言

**验证**：`uv run pytest tests/test_context_budget.py -q`

### 2B provider 元数据 + 超窗学习（teammate: provider-learning）

文件：`yaicli/llms/provider.py`、`yaicli/llms/providers/{openrouter,gemini,ollama}_provider.py`、`yaicli/errors.py`、`yaicli/llms/client.py`、`tests/test_errors.py`（追加 parse 用例）、`tests/llms/test_{openrouter,gemini,ollama}_provider.py`、`tests/llms/test_client.py`（追加）

- Provider：`base_url` property + `model_limits()` 默认 None；三 provider 实现（懒加载、≤2s、异常静默）
- `errors.parse_context_limit(exc)`：OpenAI/Anthropic/Gemini/Ollama 超窗文本 → 数字
- Client：`provider_key`/`_limits_warned`/`last_context_limits`；`_resolve_limits_and_budget()`；未知警告（stderr 一次）；`_heal_context_length` 学习 → 重算 budget → 重裁 → 重试一次；stderr 消息按 PRD 样例

**验证**：

```bash
uv run pytest tests/test_errors.py tests/llms -q
```

### 2C `/context` UI 与文档（teammate: ui-docs）

文件：`yaicli/cmd_handler.py`、`docs/usage/context-limits.md`、`docs/usage/configuration.md`、`README.md`、`tests/test_command_handler.py`（追加 `/context` 输出用例）

- `_context_usage()` 传 role prompt + project context + /add context + provider
- `_print_context_usage()` 按 PRD Feature examples 输出（window/source/detail、role/project/context/history/total/remaining/reserve）
- 文档：context-limits 预算章节重写、configuration 新增 4 键 + snippet、README 参考表同步（drift guard）

**验证**：

```bash
uv run pytest tests/test_command_handler.py tests/test_docs_config.py -q
```

**gate（Phase 2 结束）**：2A/2B/2C 全部报告完成；Lead 合并检查 `git diff`。

## Phase 3 — 集成验证（Lead）

```bash
uv run pytest tests/test_model_limits.py tests/test_context_budget.py tests/test_errors.py \
  tests/test_command_handler.py tests/test_docs_config.py tests/llms -q
uv run pytest -q                # 全量
uv run ruff check --no-fix yaicli tests
just format                     # 或 ruff format + isort（改完再复跑 lint）
```

修复跨模块问题；确认：

- [x] `get_context_window` 三个 bug 用例正确
- [x] 未知模型警告只出现一次
- [x] 400 学习后预算/`/context` 使用新窗口
- [x] `/context` 输出匹配 PRD 样例
- [x] docs drift guard 绿

## Phase 4 — 收尾（Lead）

- [x] `trellis-check` 质量检查（spec 合规 / 跨层 / 复用 / 一致性）
- [x] 更新 `.trellis/spec/py/index.md` 索引与相关 spec 交叉引用
- [ ] 记录 journal / `task.py finish`（是否 archive 由用户决定）— 待用户 review/commit 后
- [x] 最终报告：变更文件、测试结果、遗留项

## 回滚点

| 阶段 | 回滚方式 |
|---|---|
| Phase 1 | 删 `model_limits.py`/data/script/test_model_limits.py |
| Phase 2A | 恢复 `tokens.py` + `const.py` 旧内容（git checkout -- 上述文件） |
| Phase 2B | 恢复 provider/client/errors（git checkout --） |
| Phase 2C | 恢复 cmd_handler/docs/README |
| Phase 3 | 无（只读验证） |

## 不做（防止范围蔓延）

- 不实现 auto-compact / microcompact / 子代理 / usage→预算联动
- 不改 `NUM_CTX`
- 不新增依赖、不联网下载目录、不改 headless JSON


## Final results（2026-11-11）

- 新增：`yaicli/model_limits.py`、`yaicli/data/model_limits.json`（37 curated + 377 OpenRouter，36KB）、
  `scripts/gen_model_limits.py`、`tests/test_model_limits.py`（49 tests）、`tests/llms/test_openrouter_provider.py`（13 tests）。
- 修改：`tokens.py`（预算/estimate 委托）、`const.py`（4 键 + 缓存路径）、`errors.py`（`parse_context_limit`）、
  `llms/provider.py` + 3 个 provider（元数据钩子）、`llms/client.py`（未知警告 + 学习 + 重算预算）、
  `cmd_handler.py`（`/context` 新输出）、tests（+95 tests）、README/docs（configuration、context-limits、upgrade）。
- 质量门：`pytest -q` **2542 passed**；`ruff check --no-fix yaicli tests` clean；`mkdocs build --strict` OK；
  `yaicli/data/model_limits.json` 快照 `generated_at=2026-11-11`。
- 收尾：negative-cache（metadata 探测失败 TTL 300s）补丁与 2 个回归测试由 Lead 在集成阶段完成。
