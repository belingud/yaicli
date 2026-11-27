# 第二阶段验证记录

## 基线与授权

- 日期：2026-11-27；阶段起点 b7d3ce41d6c9050e03b7a35e3764d4d2c2181470。
- 第一阶段完整测试 3152 passed，独立审查及原启动门禁通过；详见前置任务 verification.md，不重复运行已经完成的基线。
- 用户已授权自主完成整个重构，并要求主线程以规划协调为主、实现和测试尽量由子 Agent 完成。共同分支 chore/refactor-command-tools，各阶段串行验收和独立提交，最终统一 PR 到 master；合并仍需用户明确确认。
- 三个 Trellis implement 子代理分别负责 planning 核心包、CLI/application/命令及计划协调、独立集成测试。源码所有权已划分，文档、调度、验收汇总及提交由主线程负责。

## 迁移前的新增契约

test_application_contract.py 中四项独立契约已在 git archive b7d3ce4 的临时源码副本通过：4 passed in 0.41s，日志 /tmp/yr-qkb0or9c。

SourceGuard 在 pytest_sessionfinish 验证实际 yaicli.cli.__file__ 位于 /tmp/ys2-base-3wx5n7co/yaicli/cli.py，避免 editable 安装意外导入迁移中源码。契约覆盖真实 UsageTracker 的完整 JSON/NDJSON payload、惰性结果构造，以及真实旧会话的工具消息、元数据、实际存储目录恢复与保存；保留 usage 的 finish_reason 和 done 的既有字段。

## 验证隔离

沿用 /tmp/yaicli_refactor_run.py 的短路径私有 HOME/配置/缓存和 fake credentials，不读取真实用户配置或连接真实 provider/MCP。shell 经 rtk 执行，测试使用 uv --no-sync --offline。完整测试含本机假 HTTP 服务，需要允许临时 localhost 监听。

额外版本测试环境已按既有 uv.lock 安装，未修改 pyproject.toml、uv.lock 或主 venv：

- Python 3.10.21：/tmp/yaicli-refactor-py310，准备日志 /tmp/yr-9jwqdr3h。
- Python 3.13.18：/tmp/yaicli-refactor-py313，准备日志 /tmp/yr-_mgvxhk1。

这两项只是环境准备成功，不代表对应版本测试已通过。最终完整矩阵在源码冻结后执行。

## 分工交接证据

- planning 核心包已冻结：旧实现补测基线 124 passed（/tmp/yr-kxeuzzrn），迁移后核心 127 passed（/tmp/yr-t64o__q8），核心/修订/工具/schema/权限相邻回归 332 passed，6.73 秒（/tmp/yr-70m9ycki）。18 个所属文件 Ruff --no-fix、format、isort、Python 3.10 AST 通过（/tmp/yr-_k3p4428）。
- planning 代理比较旧 plan_mode/plan_store 的 83 个顶层函数与类，AST 原样保留；证据 /tmp/yaicli-s2-planning-ast.json。新增 test_planning_boundaries.py 验证真实持久化恢复、拒绝不变性、修订审批后才写盘、兼容身份与默认状态唯一，以及叶子模块新进程导入无 config/CLI/Rich/终端加载或配置写入。
- 独立集成代理已冻结 tests/test_application_contract.py，新增 12 项；与阶段一 NDJSON/取消集成共 16 passed，2.23 秒（/tmp/yr-0roqnuel）。单文件 Ruff、format、isort、Python 3.10 AST 通过，汇总 /tmp/yaicli-s2-integration-result.json。
- 新集成测试直接构造真实 SessionController、MachineOutput 和 PlanCoordinator，禁止构造 CLI，覆盖真实旧会话、计划 Markdown、元数据、聊天管理器目录、重试快照和 root 不同于 cwd 的检查点重新打开。其断言基于独立预期而非只验证 mock 转发。
- 独立 Trellis check 已开始审查冻结部分；CLI/application 实现线汇合后仍需最后一次全范围检查，下列待办不因此提前完成。
- 独立检查代理已重新核对 83 个旧定义无 AST 差异；对 session/output/coordinator 按显式 config、状态归属和四项 PlanTurns 端口归一化后，保存/恢复/检查点、结果/事件/退出及计划生命周期的主体语句结构与锁顺序保持。未发现绕过 CLI 初始化的备用生产状态；这是预审，不是最终全范围通过。
- CLI/application 代理首轮相关回归为 321 passed / 9 failed：包含一处当时尚未生成的 planning.service 导入和旧私有 slot/patch 适配，仍在逐项验证；不能作为完整通过证据。
- 较大计划测试组 /tmp/yr-khpjq6qu 因旧 CLI mock 未截获新协调器调用而未完成，未计入通过结果。tests/test_plan_execution.py 已由 application 明确移交集成代理独占适配，保留原有行为断言，使用临时有界子进程包装定位后重新验证；其余产品和既有测试仍由 application 代理负责。
- 计划执行测试适配已完成并冻结：单用例 -x 在 /tmp/yr-zboz8ddl 复现旧 recorder 未触发，原因是调用主体已转移到 PlanCoordinator.execute_plan；recorder、Prompt、次数上限和编辑器改为实际 coordinator/service 绑定，四项轮次注入改为 PlanTurns.process。旧 21 个测试函数名和 99 条 assert AST 逐项一致，未删除或放宽断言。
- 适配后审批分组 8 passed（/tmp/yr-czqlhnt1），其余分组 22 passed（/tmp/yr-l5ymzhme）；完整文件与 plan_store/mode/todo/headless_plan、新服务/真实取消集成共 211 passed，7.22 秒（/tmp/yr-3w7wh21d）。单文件 Ruff/format/isort/Python 3.10 语法及 diff-check 通过。临时测试包装 /tmp/yaicli_s2_execution_bounded.py 使用独立进程组与 timeout/TERM/KILL 定向清理，所有验证运行均未超时；不操作旧未知会话。
- application/CLI/命令线正式冻结：重点回归 514 passed，35.29 秒（/tmp/yr-ofz33m6h），15 个所属文件 Ruff --no-fix、format、isort、Python 3.10 AST 和 diff-check 通过（/tmp/yr-bzbyhkm8）。包括真实 CLI 模型切换和清空历史/重试快照两项新增回归。
- SessionCommands、PlanCommands、RuntimeCommands 的窄服务接入已完成；SessionController 保存唯一聊天/目录/重试/capture/worker 引用，线程控制仍在 CLI；MachineOutput 保存唯一 ResultState；PlanCoordinator 使用会话/输出服务及四项 PlanTurns 端口，并继续沿用阶段二默认 PlanSession 所有权。
- 所有实现/测试代理已停止修改，独立 checker 恢复最后一次全范围审查及完整门禁；后续若修复，须在最终结果中记录并以修复后源码重新冻结验收。

## 待汇合验收

- [x] 迁移后相关测试及最小真实服务依赖测试通过。
- [x] 独立 Trellis check 全范围审查 S2-A1—S2-A5，无阻塞问题。
- [x] 源码冻结后完整 pytest、Ruff --no-fix、全部重构改动文件的 format/isort/Python 3.10 语法、strict docs、构建和原启动门禁通过。
- [x] 核对旧聊天/计划/检查点格式、事件/退出码、文件回退、取消/锁顺序和懒加载未变。
- [ ] 记录实际结果、剩余限制及本阶段提交，再重核第三阶段接口与上下文。

## 首轮完整验收与接续

- 完整改动静态检查通过，57 个 Python 文件通过格式/isort/Python 3.10 AST；日志 /tmp/yr-w3gpec31。已核对 24 个 CMD 兼容导出，并将三项计划遗留助手改为对协调器的显式委托。
- 首轮完整 Python 3.12 pytest：3153 passed、20 failed，87.63 秒；日志 /tmp/yr-eryh3vse，外层有界运行 /tmp/ys2-bound-1avqqg9_，正常结束、未超时。失败集中在 context_budget/image/markup_safety 的绕过初始化夹具，以及 plan_interactions/plan_resume 的旧 patch 绑定；尚不能认为本阶段验收通过。
- strict docs、wheel/sdist 已通过，两包的 117 个产品 Python 模块与当时冻结源码逐字节相同。最终修改后重新冻结并核验，不将此轮构建冒充最终验收。
- 原 checker 达到会话轮数上限；主线程核对实际状态后交给新的 trellis-check 代理接续。保留已有用例和行为断言，修复实际夹具/补丁位置，不为测试增加备用生产状态。

- 接续修复仅涉及上述五个测试文件；151 项完整相关回归通过，5.11 秒（/tmp/yr-_5gwm8h4，外层 /tmp/ys2-bound-pbg85ufc）。151 个原测试名称与 443 条 assert AST 全部不变，对比证据 /tmp/yaicli-s2-recovery-assertions.json。117 个产品模块仍与旧冻结版本一致；重新冻结全部 229 个 Python 文件至 /tmp/yaicli-s2-recovery-frozen-sources.json，开始最终完整 Python 3.12 pytest（外层 /tmp/ys2-bound-i_jmdnyv，420 秒上限）。

## 最终门禁结果

- 最终完整 Python 3.12 测试：3173 passed，91.58 秒；/tmp/yr-8wap_mnj，有界运行 /tmp/ys2-bound-i_jmdnyv，未超时。
- 全仓 Ruff --no-fix、60 个改动 Python 文件的 format/isort/Python 3.10 AST、git diff --check 全通过；/tmp/yr-drplypbr。
- test_image.py 新纳入格式范围后只去除一处既有多余空行；完整 AST 等价，证明 /tmp/yaicli-s2-recovery-format-proof.json。最终 229 个 Python 文件指纹已更新；不因纯空白变更重复完整测试。
- 严格文档构建通过；/tmp/yr-amrtkrhz。
- 既有 wheel/sdist 的 117 个产品 Python 模块再次与当前产品源码逐字节核对一致；/tmp/yaicli-s2-recovery-package-integrity.json。接续修复没有修改产品源码。
- 原门限启动 benchmark 全部通过（5 次中位数，毫秒）：version 41.1/250、help 471.1/900、template 466.2/900、entry_import 368.6/900、repl_ready 593.5/1800、oneshot_local 1615.6/2200；/tmp/yr-xqkvjnt4。未调整门限，不据此宣称性能提升。

## 独立验收结论（2026-11-28）

S2-A1—S2-A5 全部通过，无未解决阻塞问题，允许提交并进入第三阶段。唯一状态分别属于 SessionController、MachineOutput/ResultState、PlanCoordinator；命令服务通过明确依赖工作，planning 不依赖 CLI，旧入口显式兼容。旧格式、事件、退出码、实际文件回退及取消/锁顺序均由保留的行为断言和新集成测试覆盖。源码/测试最终 229 文件指纹一致；完整汇总 /tmp/yaicli-s2-recovery-result.json。

恢复过程曾因遗漏 MagicMock 导入出现 150 passed/1 failed，随后修正为最终 151 passed；第一次静态检查的一处空行也已修正。中间失败全部保留，不冒充通过。Python 3.10/3.13 完整执行及父任务最终集成审查留待第三阶段，远端统一 PR/CI/合并尚未完成。
