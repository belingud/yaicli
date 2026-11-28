# 重构测试保护评估

## 结论与方法

2026-11-27，基于提交 d0cbb8f 的未修改产品代码，三个只读子代理分别检查命令契约、工具调用链和跨层集成，主线程复核关键发现并运行隔离测试。现有测试适合支持分阶段重构，但不能仅凭全量通过或覆盖率承诺等价；迁移前必须补齐本文件列出的关键接缝。

本文件补充具体测试证据及执行顺序，不增加产品功能、配置或行为。三个阶段仍然顺序执行，代码实施按各自任务门禁处理。

## 已有的有效保护

| 边界 | 测试证据 | 能保护的内容 |
| --- | --- | --- |
| 命令与补全 | tests/test_command_handler.py:747—756；tests/test_completer.py:134—182 | 元数据、注册和斜杠补全集合一致；实际补全前缀、大小写与参数区处理 |
| 真实命令副作用 | tests/test_command_handler.py:93、131；tests/test_checkpoint_commands.py:58—129 | 清空历史、标题保留、实际文件回退、取消无副作用、真实 fork 保存 |
| 权限与确认 | tests/test_tool_policy.py:302—452、517—565；tests/llms/test_tool_confirmation.py:49—68、83—240 | readonly/trusted/standard 和危险 shell 优先级，generator.send 决策，审批、审计及 tool_call_id 配对 |
| 工具声明与覆盖 | tests/test_tool_schema_filter.py:114—179；tests/test_plan_shell_gate.py:251—322；tests/tools/test_function_loading.py:206—237 | OpenAI/Anthropic 筛选缓存，计划模式声明与 MCP 懒加载，真实加载并执行用户同名工具 |
| 输出及执行结果 | tests/test_context_budget.py:588—633、691—722；tests/tools/test_tool_display.py:197—283 | 真实分发器、大输出分页、下一次模型请求、预览及完整参数/历史 |
| 文件与撤销 | tests/test_workspace_safety.py:511—526、593—624、696—712 | 创建、追加、编辑和覆盖移动之后的实际文件字节恢复 |
| 检查点跨层集成 | tests/test_checkpoint_integration.py:245—455；tests/test_checkpoints.py:141—163、308—408 | 真实 CLI/client/worker/guard/存储、配置 root 首轮生效、跨进程恢复、二进制字节/权限、失败补偿 |
| 机器输出 | tests/test_headless_contract.py:76—105、150—177、573—585、639—683；tests/test_headless_plan.py:76—155 | JSON 字段、文本换行、stdout/stderr 分离、中断退出码、计划字段及事件 |
| 线程桥接 | tests/test_stream_bridge.py:130—204；tests/test_worker_console.py:209—243；tests/test_cli.py:1703—1771 | 双向确认、取消解除等待、迟到输出隔离、成功才采用历史副本 |

权限单元测试会 mock 执行入口；它们保护决策协议，不能替代真实分发器贯通测试。检查点集成保留真实执行链，是迁移期间必须保留的重要防线。

## 第一阶段迁移前的最小补测

1. **独立冻结旧命令契约。** 测试显式记录当前 24 条主命令、3 条斜杠别名和 `?`，包含处理器与尾部输入策略，不能从待重构的注册表生成 expected。覆盖精确 token、混合大小写、未知/近似名称、无参命令后的文本、原始参数及全部别名。特别保留 `/checkpoints extra` 进入处理器输出 Usage，而 `/help extra` 作为原提示词返回的差异。依据：cmd_handler.py:95、171、1322—1358。
2. **授权写失败的完整回退。** PERSIST 遇到 OSError 后当前调用执行、提示准确、同一 manager 下一次不确认、重建 manager 后没有永久授权。依据：llms/client.py:762—782；首轮覆盖率确认 774、776—779 未执行。
3. **权限到真实执行器的贯通。** 假 provider 加真实 client/dispatcher、临时目录，至少覆盖确认允许和拒绝，核对真实文件字节、审计、配对消息、下一次 provider 请求及公告次数。
4. **大输出元数据完整性。** 一次调用核对原始长度、完整 spill 内容、仅一条历史、模型结果与历史结果对应，避免兼容入口和新 executor 各处理一次；不以内部函数调用次数代替行为验收。
5. **真实工具的 NDJSON 事件。** 假 provider 发出至少两次工具调用，经真实 client/dispatcher，核对 tool_call/tool_result/text/usage/done 顺序、数量及载荷；拒绝分支也覆盖。现有 headless 文本流测试和人工注入 history 不能替代此链路。依据：cli.py:756—817；test_headless_contract.py:118—134、181—197。
6. **取消与检查点的组合边界。** 用 threading.Event 控制工具阻塞并经真实 CLI 取消，检查未结束 worker 的 pending/锁、回退拒绝、未完成轮次不提交成功检查点；释放 worker 后验证文件、历史、barrier 及后续轮次可用。避免依赖 sleep。第一阶段建立基线，第二阶段提取前必须复跑。依据：cli.py:2160—2162、2330—2338、2433—2463。

这些测试先在旧实现上运行；新增测试若发现既有产品缺陷，应明确记录并单独评审，不能直接改变 expected 或借重构修复用户语义。

## 测试本身需要修正的断言

- tests/test_command_handler.py:642 的 `assert cli._client is cli._client` 恒真；应先保存原实例再比较。
- tests/test_tool_schema_filter.py:22、45、211 在 fixture 替换集合后仍断言顶部导入的旧集合；应核对实际模块的当前集合，并保留未输出警告的行为断言。
- tests/llms/test_gemini_provider.py:102、147 的 patch 目标不是 provider 已绑定的引用；应对实际绑定处 patch，避免 mock 无效后测试仍然通过。
- tests/tools/test_fetch_webpage.py:653 的升级重定向测试遗漏现有 public_dns fixture，会依赖外部 DNS；应补测试隔离，不修改抓取工具的产品逻辑。
- tests/test_project_context.py:213—221、265—273 假设绝对路径标题能装入固定 200 字符；临时路径较长时会失败。当前基线复核使用较短临时根目录，记录此限制，不将长路径失败误判成重构缺陷；后续测试稳定性修正不能放宽产品字符上限。

## 后续阶段的专属保护

- 第二阶段：SessionController / PlanCoordinator 使用窄依赖独立测试，继续校验实际保存路径、计划文件、恢复指针及历史，而不是只迁移 mock 目标。复跑 NDJSON 和取消/检查点组合用例。
- 第三阶段：一个测试中建立两个真实运行时，A→B→A 交替使用不同配置和 PlanSession；中途不能全局 reset。检查声明、状态、输出限制、workspace root、配置变更和异常后的下一次调用。双方切到正常写入模式后验证各自文件字节。当前 test_session_isolation.py:157—175 只保护存储目录，conftest.py:131—144 的自动 reset 不能证明运行时隔离。

## 必须保留的现状及门禁限制

Gemini 当前与另两种 provider 并不完全一致：tools/function.py:280—312 的 callable builder 按 mode 缓存，不筛 ENABLED_TOOLS；gemini_provider.py:196—212 直接聚合 MCP。第一阶段按各 provider 当前实际输出分别冻结，不借 schemas 提取统一这些行为；相关功能修正应单独提出。

`ok=True` 表示抵达工具执行路径，包含保护层或工具自身的业务错误，不应改成业务成功；test_workspace_safety.py:492—509 和 test_plan_shell_gate.py:144—150 已有保护。

CI 已有 Python 3.10/3.12/3.13、Ruff、strict docs 及启动性能任务。旧 quality spec 的“没有测试 CI”描述过时。scripts/bench.py:112—143 的部分计时未检查子进程返回码，故门禁必须与 startup/runtime_bootstrap 功能测试配合，不能单凭计时通过判定启动正确；不在本次顺手重写 benchmark。

## 本轮运行记录

基线提交 d0cbb8f，Python 3.12.11；产品源码与测试均未修改。启动器位于 `/tmp/yaicli_refactor_baseline.py`，进程启动前隔离 HOME/YAI_CONFIG_DIR/UV_CACHE_DIR，清除继承 YAI_*/XDG_*/PYTHONPATH 及凭据，设置离线 uv；测试凭据由仓库 fixtures 提供。覆盖率输出及 pytest 缓存均放在临时目录。

命令：`uv run --no-sync --offline pytest -q --basetemp <临时根>/pytest -o cache_dir=<临时根>/pytest-cache --cov=yaicli --cov-branch --cov-report=json:<临时根>/coverage.json --cov-report=term`。

首轮在沙箱内、较长的系统临时根目录运行：**3064 passed、3 failed、3 errors，144.46 秒**。失败分别为上述两项绝对路径长度假设和一项遗漏 DNS mock；三项 error 是 provider_response_errors 的本机假 HTTP 服务不能绑定 127.0.0.1。总语句覆盖率为 14035/15338，分支覆盖率为 4418/5248，合计约 89.64%；失败运行的覆盖率仅用于定位未执行分支，不能称为绿色基线。

较短临时根 `/tmp/yr-z674br4f`、允许本机模拟服务的完整复核：**3070 passed，143.46 秒**，退出码 0，启动器总耗时 147.88 秒。覆盖 14035/15338 条语句、4419/5248 个分支，综合约 89.64%（pytest 显示 90%）。本次没有修复或屏蔽任何测试；DNS 测试在允许网络解析的环境下通过，但遗漏 mock 的确定性问题仍然存在，必须按上文修正。

原始 stdout、stderr、result.json 和 coverage.json 位于该临时目录，仅用于本轮证据；重跑应按上述隔离方法生成新目录，不能依赖临时产物长期存在。尚未运行多 Python 本地矩阵、性能、文档或构建门禁，不将计划中的命令写成已通过证据。
