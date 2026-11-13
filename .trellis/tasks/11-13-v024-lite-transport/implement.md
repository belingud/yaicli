# v0.24.0 Lite transport — Implement 计划

> 按 [prd.md](./prd.md) 与 [design.md](./design.md) 落地。分支 `feat/lite-transport`，PR 目标 `master`。
> 约束：**不 bump 版本、不发版**（用户决定）；不联网测试；sandbox 内用 `.venv/bin/python -m pytest` 等。

## Phase 0 — 规划与任务产物（Lead）

- [x] Trellis 任务目录 `11-13-v024-lite-transport`（prd/design/implement）
- [x] `task.py set-branch` / `set-base-branch`
- [x] 分支 `feat/lite-transport`
- [x] `task.py start`（in_progress）

**gate**：PRD 有 `## Feature examples`；`task.json.status == in_progress`。

## Phase 1 — 核心模块（Lead；契约冻结点）

写入域：`yaicli/llms/openai_wire.py`(新)、`yaicli/llms/lite_transport.py`(新)、
`yaicli/llms/providers/openai_provider.py`、`yaicli/llms/providers/openai_compatible_provider.py`。

1. `openai_wire.py`：平移 `OpenAIProvider` 逻辑（无 SDK import），异常处理鸭子化。
2. `lite_transport.py`：`LiteChatClient` + 鸭子对象 + SSE + `LiteAPIError`。
3. `openai_provider.py`：懒 `import openai`，`create_client()` 按 `LITE_TRANSPORT` + 精确类名选择；Azure 永远 SDK。
4. `openai_compatible_provider.py`：SDK 类型 import → `TYPE_CHECKING`；`from __future__ import annotations`。
5. 冒烟：`python -m pytest tests/llms/test_openai_provider.py tests/llms/test_openai_compatible_provider.py -q`（此时既有测试因 patch 路径/默认 lite 需要修复，Phase 3 统一处理；先确认模块可 import）。

**gate**（契约冻结）：`python -c "import yaicli.llms.lite_transport, sys; assert 'openai' not in sys.modules"` 通过；
`LITE_TRANSPORT` 选择在构造期生效（手工或临时脚本验证 lite/sdk 两条 client 类型）。

## Phase 2 — 并行（两个写入域，互不重叠）

### 2A 配置键与模板（Lead）

写入域：`yaicli/const.py`、`tests/test_docs_config.py` 不改（自动覆盖）。

- `DEFAULT_LITE_TRANSPORT: BOOL_STR = "true"`、`DEFAULT_CONFIG_MAP["LITE_TRANSPORT"]`、`DEFAULT_CONFIG_INI` 行。
- verbose 行实现检查（Lead 在 Phase 1 已写入 provider，此处验证 machine 模式落到 stderr）。

**验证**：`python -m pytest tests/test_docs_config.py -q`（docs 由 Phase 2B 同步前会红，属预期；2B 完成后必须绿）。

### 2B 文档（teammate: docs-writer）— 已完成（配置参考表/INI 片段/Transport Selection/v0.24 upgrade/README/docs index/provider 页；`tests/test_docs_config.py` 6 passed，`mkdocs build --strict` 通过）

写入域：`docs/`、`README.md`（**不改** `yaicli/`、`tests/`、`scripts/`）。

- `docs/usage/configuration.md`：参考表 + INI 片段 + "Transport (lite / SDK)" 小节。
- `README.md`：参考表 + 必要的轻量声明。
- `docs/advanced/upgrade.md`：v0.24 节（默认变化、回退 `LITE_TRANSPORT=false`、适用范围、排障）。
- `docs/providers/openai.md` / `openai-compatible.md`（存在则加传输层说明）。

**验证**：`python -m pytest tests/test_docs_config.py -q` + `python -m mkdocs build --strict`。

### 2C 测试（teammate: parity-tester，Phase 1 冻结后启动）— 已完成（新增 `test_lite_transport.py` 74 例 + `test_lite_parity.py` 10 例；修复 66 个既有失败用例；全量 2626 passed）

写入域：`tests/llms/test_lite_transport.py`(新)、`tests/llms/test_lite_parity.py`(新)、
`tests/llms/test_openai_provider.py`、`tests/llms/test_simple_providers.py`、`tests/llms/test_openai_compatible_provider.py`、其它受懒 import 影响的测试。

- 按 design §7 写传输层单测（`httpx.MockTransport`）与 SDK/lite parity 测试。
- 修复既有 `patch("...openai_provider.openai.OpenAI")` 路径；SDK 路径测试显式 `LITE_TRANSPORT=False`。
- 新增配置键/verbose 行的测试。

**验证**：`python -m pytest tests/llms/test_lite_transport.py tests/llms/test_lite_parity.py tests/llms/test_openai_provider.py tests/llms/test_openai_compatible_provider.py -q`。

## Phase 3 — 集成、bench 与门禁（Lead + 独立复核）

1. 合并各域，跑全量：
   - `python -m pytest`
   - `python -m ruff check --no-fix yaicli tests`
   - `python -m mkdocs build --strict`
2. `python scripts/bench.py -n 5 --gate`：记录 `oneshot_local` 实测；按 design §8 收紧 `GATE_LIMITS`。
3. 手工验收（PRD Feature examples 2/3/4）：默认/回退的 `Transport:` 行、401 错误输出、`--json` stdout 干净。
4. 独立复核（teammate 或 Lead 二次检查）：`git diff` 与 design 一致、无 openai import 泄漏、无联网测试。
5. `task.py validate` / `task.py finish`，更新 spec（provider-guidelines 的 lite transport 章节）、roadmap（`var/lightweight-audit/09-roadmap.md` 记 v0.24.0 实现状态）。
6. 提交分支、push、`gh pr create --base master`；**等用户确认后再合并**（不自动 merge）。

**gate**：PRD Acceptance 1–7 全部满足；PR CI 绿。

## 回滚点

| 阶段 | 回滚集合 |
| --- | --- |
| Phase 1 | 删除 2 个新模块 + revert 2 个 provider 文件 |
| Phase 2 | revert docs/README/const |
| Phase 3 | revert bench gate + 测试文件 |

## 完成状态（2026-11-13，Lead 最终门禁）

- [x] `pytest` 全量 **2626 passed**（含 84 个新增 lite/parity 用例）
- [x] `ruff check --no-fix yaicli tests` 干净
- [x] `mkdocs build --strict` 通过
- [x] `python scripts/bench.py -n 3 --gate` 全项 ok（`oneshot_local` 643.4ms < 1000ms）
- [x] 导入边界子进程断言：`lite_transport` / `openai_wire` / 两个 provider 模块均不 import `openai`
- [x] 手工验收：默认 `Transport: lite (httpx)`、`YAI_LITE_TRANSPORT=false` → `Transport: openai SDK`、`--json` stdout 干净、401 stderr 与 SDK 逐字节一致、流式/非流式输出一致
- [x] 实测 `oneshot_local`：SDK 回退 1623.2ms → lite **584.3ms**（-64%）；gate 2200 → 1000ms
- [ ] PR 创建 / 合并（需要用户确认后合并）/ 归档（合并后做）
