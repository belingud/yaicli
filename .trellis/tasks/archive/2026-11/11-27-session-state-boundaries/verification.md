# 第三阶段验证记录

## 基线与授权

- 开始日期2026-11-28；基线66db0625e6b559f97509760c06e842f774eb8b9c，前两阶段已分别完整验收并提交。
- 第二阶段完整Python3.12：3173 passed，91.58秒；全范围静态、严格文档、wheel/sdist字节核对及原性能门禁均通过。详见前置verification.md，不重复基线。
- 用户已授权自主完成全部重构，主线程规划/规范/提交，由Trellis子代理实现和检查。共同分支chore/refactor-command-tools，最终统一PR到master，合并仍需用户明确授权。
- 共享接口和A/B/C文件所有权在design.md固定；实际配置/锁/回调接缝已由stage3-handoff.md及runtime-config-review.md核对。implement/check.jsonl各14项，validate通过。

## 初始分工与验收计划（历史）

A负责runtime/CLI/application/commands/planning与必要chat/project_context；B负责llms/tools及底层配置消费、环境桥接；C新增真实隔离与config-only-root跨进程回归。不得覆盖其他代理修改，不读取真实env/密钥，不使用真实provider/MCP，不增加配置或依赖。

最终完整测试、独立审查、三版本矩阵、严格文档、构建、指纹和原性能门禁均待本阶段源码冻结后执行；本记录不提前标记通过。

## 迁移前可观察污染基线

C线以git archive 66db062创建独立源码副本，在既有CLI表面重现两项失败，非缺少新API/import失败：构造B后A的模型提示变为runtime-b；A保存时会话JSON误写入B的目录。2 failed，0.62秒；/tmp/yr-kytudomg。SourceGuard确认导入/private/tmp/ys3-base-b8iocjar/yaicli/cli.py，排除了editable安装混入；汇总/tmp/yaicli-s3-archive-baseline.json。迁移后必须用同样实际返回/保存位置断言修复，不能只检查对象身份。

## 接线进度（非最终验收）

A已公布runtime.py固定接口，并接入CLI的一次深复制、所属默认聊天管理器、协调器唯一计划引用及service的显式session参数。请求/worker启动和普通/计划保存已加入无锁配置绑定。相关测试仍在运行；B模型工具、C独立隔离/跨进程回归尚未交付，不能据此宣称S3通过。

## 环境适配前置验证

B线新增tests/tools/test_runtime_environment.py，3项嵌套/异常恢复、真实guard写入和同root undo验证通过；组合运行65 passed/1旧selection夹具失败（/tmp/yr-9lgu92a7），后者需要改为所属config，不将混合结果算作最终全绿。实现采用env RLock仅包实际执行，确认yield在外，锁顺序env->workspace；checkpoint保存只绑定无锁配置，不反向取env锁。

扩大B回归暂为1337 passed/8 failed，失败集中旧factory参数、mock执行lambda、旧环境sync patch及截断配置夹具，仍在适配，最终完整验收待后续冻结。C首轮8 passed/1假provider缺config（/tmp/yr-d1b_nv0_），包含独立A/B/A三声明、禁止旧global getter、延迟会话callback、todo和sync/stream配置root跨进程实际字节；同样不作为最终完整通过证据。

## B/C正式交付

- B相关回归1410 passed，27.41秒（/tmp/yr-k2enesup），全部tools/llms及权限/计划shell/schema/预算/限制/脱敏；27个所属Python文件质量门禁通过且最终测试前后指纹一致。汇总/tmp/yaicli-s3-b-result.json，质量与原测试对比/tmp/yaicli-s3-b-quality.json，指纹/tmp/yaicli-s3-b-frozen-files.json。
- B原202个测试名称保留；除环境传播组外原assert AST保持。六条原永久export断言改为execute内观察相同值，并增加执行后恢复断言；新增4项实际环境/guard/undo回归。新模块tools/environment.py::tool_environment(config)承担完整环境桥接，未添加新配置。
- C两文件最终11 passed，9.89秒（/tmp/yr-kf2j9a88）；Ruff/format/isort/3.10AST/diff通过，/tmp/yaicli-s3-isolation-static.json。汇总/tmp/yaicli-s3-isolation-result.json，包含fresh解释器不执行conftest、旧getter禁止、实际三provider声明/会话状态、延迟callback、文件/undo/env/脱敏、动态MCP配置及sync/stream跨进程root的完整证据。
- C冻结test_runtime_isolation.py SHA256 1bfc750222bee5db00f40da2ba06fab293d4069c9878b3ad29694a533b22db34；test_runtime_checkpoint_root.py SHA256 a38dc8978f3bec39b86ea3f4a9e2b3bd1e5bf74fabbeef5b0c995e8fcfd11ba3。
- A最后相关回归仍待汇总，独立checker已开始审查冻结的B/C；本阶段完整矩阵和父任务验收尚待执行，组件通过数不能累加为完整套件数。

## A正式交付与统一冻结

- A的29个应用/计划/检查点/启动/线程相关文件928 passed，46.08秒，无超时（/tmp/yr-igvtkfsk，外层/tmp/ys2-bound-ig97fm9l）。22所属Python文件Ruff --no-fix/format/isort/Python3.10 AST/diff通过：/tmp/yaicli-s3-a-quality.json。
- 最终12个既有改动测试文件420个旧测试函数名全部保留，assert1244→1245；差异限所属配置/计划模式、显式session及新增默认cfg不变断言。精确对比/tmp/yaicli-s3-a-assertions.json；指纹/tmp/yaicli-s3-a-frozen.json，汇总/tmp/yaicli-s3-a-result.json。先前9文件311函数/1056→1057为中间范围，不冒充最终范围。
- 三条实现线均已停止修改并移交独立trellis-check；所有生产/测试后续必要修复由checker独占。主线程冻结七份站点/规范文件，仅继续任务记录。完整Python3.12及最终全范围门禁开始；3.10/3.13矩阵待checker确认稳定指纹后并行执行，性能待全部CPU重任务结束。

## 独立审查中的必要修复

checker发现CLI._make_printer未传所属config，Printer的默认配置工厂因此使显式应用配置的SHOW_REASONING/SHOW_THINKING_STATUS/CODE_THEME仍取默认值。这属于本阶段漏接的局部依赖修复；先补行为复现，再传self.config，不改变Printer公共契约。首轮完整测试冻结235个Python文件（外层/tmp/ys2-bound-esy337vr，内/tmp/yr-dqabwuby），结束前不改源码；修复后重新冻结并执行最终完整门禁，首轮结果不冒充修复后验收。

## 独立审查修复与首轮完整结果

- 首轮完整Python3.12：3174 passed/20 failed，102.41秒，/tmp/yr-dqabwuby。17项工作区测试夹具仍patch已删除的_sync_shell_guardrail_env；patch.start中途失败又泄漏get_function，导致后续3项失败。改为传入实际WORKSPACE_ROOT并移除失效patch，69个旧测试名和204条assert AST全部保持；/tmp/yaicli-s3-check-workspace-assertions.json。
- 打印器新增两项参数化实际render回归先2 failed（/tmp/yr-xfajjxgw），修复_make_printer的machine/text两条路径传self.config，覆盖coder重建和configure_headless。主题/推理/状态已有实际消费同一Printer.config，无需改无关render/console单例。
- 修复后270项相邻回归通过，11.22秒（/tmp/yr-idtbncdv）。checker重新冻结并执行最终完整Python3.12、静态、docs和build；上述首轮失败与局部通过不替代最终完整结果。

## 最终冻结后的完整门禁（矩阵/性能前）

| 检查 | 结果 | 记录 |
| --- | --- | --- |
| Python3.12完整pytest | 3196 passed，98.75秒，无超时 | /tmp/yr-s5fgdgkv；外层/tmp/ys2-bound-0xg71a_g |
| 全仓Ruff --no-fix | 通过 | /tmp/yr-fi62d607 |
| 85个改动Python文件format/isort/3.10AST及diff-check | 全部通过 | /tmp/yr-fi62d607 |
| strict docs | 通过 | /tmp/yr-swc3lnkl |
| wheel/sdist构建 | 两种包均通过 | /tmp/yr-b8vbfz7v |
| 安装包字节核对 | 两包119个产品Python模块与冻结源码逐字节相同，wheel不含tests | /tmp/yaicli-s3-check-package-integrity.json |
| 原测试完整性 | 旧改动测试名称全部保留，workspace69测试/204assert完全一致；其余差异仅所属状态/有效配置绑定 | /tmp/yaicli-s3-check-test-integrity.json |

冻结清单/tmp/yaicli-s3-check-final-frozen.json共235个Python源/测试文件，随后无写入。实际Python3.10和3.13完整矩阵已分别交A/B只读执行，先验证版本/导入路径，结束后比较同一235文件指纹；禁止在矩阵期间修改源码。最终启动benchmark待二者结束后由checker单独执行，沿用原阈值。

## 最终实际版本矩阵

| 解释器 | 完整结果 | pytest耗时 | 日志与汇总 |
| --- | --- | ---: | --- |
| Python3.10.21，私有/tmp/yaicli-refactor-py310 | 3195 passed，1 skipped，退出0、未超时 | 109.21秒 | /tmp/yr-ludv9f2j；/tmp/yaicli-s3-py310-result.json |
| Python3.12.11，项目venv | 3196 passed，退出0、未超时 | 98.75秒 | /tmp/yr-s5fgdgkv |
| Python3.13.18，私有/tmp/yaicli-refactor-py313 | 3196 passed，退出0、未超时 | 107.16秒 | /tmp/yr-umo_2m84；/tmp/yaicli-s3-py313-result.json |

3.10唯一skip是既有test_runtime_bootstrap.py:358的pytest.importorskip('tomllib')；已实证该解释器无tomllib（/tmp/yr-tmz4tlmm），不改测试或加依赖。3.13首次预检只因/tmp与/private/tmp目录别名字符串比较失败，改临时预检脚本为resolve后通过（失败预检/tmp/yr-nhatmz_p），没有跑测试或改产品。

两私有矩阵均先确认实际解释器与仓库yaicli导入路径，运行前后235文件集合与SHA全部一致。矩阵结束后无源码/测试写入。原checker会话达到轮数上限后，剩余只读验收映射/指纹/性能交给新trellis-check继续，不重复已完成门禁；最终benchmark现已解除CPU等待。

## 最终启动性能与独立结论（2026-11-28）

原scripts/bench.py与第二阶段66db062逐字节相同，两个完整版本矩阵结束后串行执行，沿用原阈值：

~~~bash
uv run --no-sync --offline python scripts/bench.py --gate -n 5 --json
~~~

| 指标 | P50（毫秒） | 原阈值（毫秒） |
| --- | ---: | ---: |
| version | 40.4 | 250 |
| help | 447.2 | 900 |
| template | 447.1 | 900 |
| entry_import | 391.9 | 900 |
| repl_ready | 555.8 | 1800 |
| oneshot_local | 1440.1 | 2200 |

六项均通过，退出0、无超时，外层19.12秒；隔离启动器与假provider，没有真实外部请求。内日志/tmp/yr-2oh88vbd，外/tmp/ys3-bench-ig3zy48a，汇总/tmp/yaicli-s3-bench-result.json。该小样本仅证明原门禁通过，不宣称性能提升。既有脚本部分子进程不检查返回码，须与已经通过的startup/runtime-bootstrap功能测试合看，本次未顺手改脚本。

最终独立checker只读复核既有日志、门禁结果和验收映射，没有再次改动源码或重复完整门禁。235文件（119产品、116测试）集合与SHA最终一致；无新增产品阻塞。完整汇总/tmp/yaicli-s3-final-acceptance.json已读回确认。

## 最终验收映射

| 条件 | 实际证据 | 结论 |
| --- | --- | --- |
| S3-A1 唯一计划状态 | test_runtime_isolation的fresh进程禁旧getter、三provider A/B/A声明、延迟submit/todo及实际持久化；test_runtime_context唯一引用 | 通过 |
| S3-A2 所属配置 | 一次深复制、嵌套隔离、权限/工具/输出限制、模型重建、实际save/spill脱敏、两种Printer实际render及重建 | 通过 |
| S3-A3 独立工具环境 | 实际root交替写入/拒绝、异常和空默认恢复、下一调用、真实undo、锁顺序与取消集成；builtin源码/签名保持 | 通过 |
| S3-A4 检查点root | test_runtime_checkpoint_root的仅配置文件root、cwd子目录、其他应用干扰，sync/stream跨进程保存/重开/rewind真实字节 | 通过 |
| S3-A5 兼容及惰性 | 显式路径禁旧getter、默认入口另测、runtime仅标准库和惰性planning、startup/bootstrap及原性能门禁 | 通过 |
| S3-A6 质量和交付 | 完整三版本、静态、strict docs、build/包字节、235指纹全部通过；父任务最终架构和技术审查通过 | 本地技术通过；提交/PR/CI/合并确认单列待办 |

父A1命令/工具、A2服务边界、A3实例隔离、A4行为/旧数据/实际回退、A5质量均已最终集成通过；父A6技术审查完成，详见父verification.md。原19个改动测试文件691个旧测试函数名保留，旧测试assert2116→2125；变更只限所属配置/模式/环境观察时机及新增恢复断言，不删行为预期。项目没有mypy/pyright配置，不虚构类型检查结果。

## 交付与限制

- 实例隔离承诺为串行/交替，不扩大为同进程并行应用或并发cwd。
- 进程级undo/output-history、console及无关加载缓存维持原范围；没有新增配置、命令、依赖、存储协议或迁移步骤。
- pyproject.toml、uv.lock、const/config/schemas、planning模型/存储/校验/提示/编辑器、命令registry、stream_bridge、checkpoint_lock及独立builtin与S2保持一致。
- 主线程接手第三阶段提交和统一PR；CI通过后按AGENTS.md要求等待用户明确合并确认。未合并前不提前归档或发布。
- 临时JSON/日志便于本机核查，本记录和父任务记录保留长期验收摘要，不依赖临时目录作为交付物。

## 统一PR交付进度（2026-11-28）

三个阶段已分别提交b7d3ce4、66db062、0bb6415并推送，统一PR [#60](https://github.com/belingud/yaicli/pull/60)目标master。第三阶段完整hash为0bb64158dfe1c1744cda4fed1b73d971ab0cef48。后续任务元数据/日志独立提交，不改已冻结产品与测试；最新head CI通过后仍需用户明确批准合并，未提前归档或发布。

## 用户后续报告的独立渲染缺陷（2026-11-28）

原三阶段验收/PR7408c51的CI通过后，用户报告含☀️的流式回答残留重复。结合已授权读取的debug生命周期日志与真实Rich输出，定位到旧锁Rich14.0.0的VS16计宽缺陷；重构前同样存在。已建立独立任务[stream-emoji-rendering](../11-28-stream-emoji-rendering/prd.md)，以独立fix提交附加到同一PR60，不重写原阶段提交或把升级前门禁冒称升级后验证。其192项聚焦与26组独立重放已绿，完整验收/最新PR CI由该任务继续；合并仍需用户明确确认。

### 缺陷跟进本地验收完成

独立stream-emoji-rendering任务已完成定向Rich14.3.3修复和本地独立检查：旧版4项VS16红灯，修复后10项回归与26组重放通过（108次残留→1次）；真实天气fake工具在工作线程只执行一次，debug前后TTY字节相同。冻结245文件未变，3203项通过后因沙箱回环端口限制产生的3项准备错误同hash补跑通过，共3206个不同测试已验证。静态、strict docs、离线lock/构建、原启动门禁均通过；新版wheel/sdist120产品文件与源码一致。本段不替代上文三阶段历史基线；完整结果见../11-28-stream-emoji-rendering/verification.md及acceptance.json。待单独fix提交和最新head CI，再等待用户明确合并确认。

## 最终合并与归档（2026-11-28）

最新交付head 5d2424bb8e0288625c851ad72a83734a4052b604 的六项CI全部通过：Python3.10/3.12/3.13完整测试、Lint & docs、Cold-start gate、GitGuardian。用户明确回复“好，合并吧”后，PR60于2026-11-28 06:02:54 UTC（北京时间14:02:54）以merge commit ae8620af6cfa0c084e68c37d88405a30a4ba5bc5合并到master。本地master已快进同步，原有无关未提交改动保留。长期合并/CI证据见../11-27-core-organization-refactor/delivery.json。

本PR对应父任务、三个重构阶段及独立emoji修复均已完成；按仓库规则归档到archive/2026-11，不开展新功能，不发布、不升版本。此前章节中的“待CI/合并”等为当时历史状态，以本节为最终交付结果。后续仅允许任务归档与会话记录的bookkeeping提交。
