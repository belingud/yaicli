# 第一阶段验证记录

## 基线与隔离

- 日期：2026-11-27；Python 3.12.11。
- 分支：chore/refactor-command-tools；PR 目标 master。
- 已获取远端 master，基线提交 d0cbb8f29b69c9429262b83be4daba2cf6e2bf2f。
- 用户已批准最终补测优先、命令/工具并行方案；本子任务 in_progress，后续两个阶段未启动。
- 每次验证由 `/tmp/yaicli_refactor_run.py` 创建独立短路径临时 HOME、YAI_CONFIG_DIR、UV_CACHE_DIR，清除继承 YAI_*/XDG_*/PYTHONPATH 及凭据，离线 uv，不读取个人配置。测试凭据由 fixtures 提供；HTTP 边界使用本机假 provider。
- shell 命令经 rtk 执行；下列记录只列实际底层命令，日志包含启动参数、退出码和耗时。短路径避免既有 200 字符项目上下文测试的路径长度假设，详见父任务 research/test-safety-review.md。

## 迁移前的完整及组件基线

| 检查 | 结果 | 原始记录 |
| --- | --- | --- |
| 隔离完整 pytest，含语句/分支覆盖 | 3070 passed，143.46 秒；退出码 0 | /tmp/yr-z674br4f/result.json、stdout.txt、coverage.json |
| 启动 benchmark：python scripts/bench.py --gate -n 3 --json | 退出码 0，六项均通过 | /tmp/yr-f_7gjgsd/result.json、stdout.txt |
| 命令特征测试先在旧实现运行 | 171 passed，2.83 秒 | /tmp/yr-fu6njd_f/result.json、stdout.txt |
| 工具专属补测先在旧工具实现运行 | 163 passed，2.76 秒 | /tmp/yr-dd75h3rz/result.json、stdout.txt |
| NDJSON 与取消/检查点组合先在旧工具实现运行 | 4 passed，2.07 秒 | /tmp/yr-95qc_o1i/result.json、stdout.txt |

启动基线 P50（毫秒）：

| 指标 | 基线 | 原门禁 |
| --- | ---: | ---: |
| version | 44.4 | 250 |
| help | 530.5 | 900 |
| template | 469.2 | 900 |
| entry_import | 408.7 | 900 |
| repl_ready | 625.0 | 1800 |
| oneshot_local | 1711.3 | 2200 |

完整基线覆盖 14035/15338 条语句、4419/5248 个分支，综合约 89.64%。覆盖率只是定位工具，不作为完成阈值；未执行分支及 mock 接缝已列入必需补测。

## 迁移及独立审查

- [x] 工具补测在旧实现先通过。
- [x] 真实 NDJSON、取消/检查点组合回归在旧实现先通过。
- [x] 命令注册表提取后四个相关测试文件通过：198 passed，3.81 秒（/tmp/yr-eao7jaqm）。注册表轻量导入及兼容导出同一性也有断言。
- [x] 工具模块与权限提取后相关回归通过：754 passed（/tmp/yr-ecgx48x_）；相邻 provider、上下文及安全链路 772 passed（/tmp/yr-hvplh_2h）。重叠测试不累加为总数。
- [x] 真实 NDJSON、取消/检查点组合在新实现上通过：4 passed（/tmp/yr-u4zaqncw）；相邻集成链路 92 passed（/tmp/yr-y9zqxtv6）。
- [x] 独立 Trellis check 全范围审查通过，无阻塞问题。相关测试 380 passed（/tmp/yr-n85l2a05），修复重复 MCP 前缀常量后 262 passed（/tmp/yr-6iizli4v）。审查比较迁移前后的函数结构及 16 个既有测试文件，未删除测试或放宽断言；修正恒真断言、实际缓存所有者及失效集合引用。
- [x] 既有 WorkerConsoleRouting 的公共 console 注入保留，由 tools 公共入口显式传递当前 cfg/console。权限评估保持纯决策；确认生成器、授权、审计和配对消息仍由客户端衔接。

## 最终完整门禁

独立审查完成后冻结源码，再执行以下检查。日志目录中的 result.json 记录实际命令、退出码和耗时，stdout.txt/stderr.txt 保留输出。

| 检查 | 实际命令或检查范围 | 结果 | 原始记录 |
| --- | --- | --- | --- |
| 完整测试 | uv run --no-sync --offline pytest -q | 3152 passed，pytest 88.24 秒，退出码 0 | /tmp/yr-b0c7rb9p |
| Lint | .venv/bin/python -m ruff check --no-fix yaicli tests | 通过 | /tmp/yr-ognvmwiz |
| 格式、导入及语法 | 27 个改动 Python 文件：ruff format --check、isort --check-only、ast.parse(feature_version=(3, 10)) | 全部通过；git diff --check 通过 | /tmp/yr-ognvmwiz |
| 严格文档构建 | uv run --no-sync --offline mkdocs build --strict --site-dir /tmp/yaicli-refactor-docs | 退出码 0 | /tmp/yr-7ix2dli_ |
| Wheel 与 sdist | uv build --python /tmp/yaicli-refactor-build-env/bin/python --no-build-isolation --offline --out-dir /tmp/yaicli-refactor-dist | 两种包均构建成功，退出码 0 | /tmp/yr-839l03ob |
| 安装包内容 | 检查 wheel/归档内九个新增或迁移的核心模块 | 两种包的对应模块均与冻结源码逐字节一致；wheel 不包含 tests/ | /tmp/yaicli-refactor-dist |
| 启动门禁 | uv run --no-sync --offline python scripts/bench.py --gate -n 3 --json | 六项全部通过，退出码 0 | /tmp/yr-bxqa651s |

格式检查使用项目 venv 中的 Ruff 与已有 /Users/vic/.local/bin/isort，不安装项目依赖。构建后端装在独立临时构建环境中，未修改 pyproject.toml、uv.lock 或运行时依赖。各子进程均通过隔离启动器执行。

启动门禁 P50（毫秒，n=3）：

| 指标 | 迁移前 | 迁移后 | 原门禁 |
| --- | ---: | ---: | ---: |
| version | 44.4 | 40.8 | 250 |
| help | 530.5 | 346.4 | 900 |
| template | 469.2 | 342.8 | 900 |
| entry_import | 408.7 | 286.8 | 900 |
| repl_ready | 625.0 | 446.7 | 1800 |
| oneshot_local | 1711.3 | 1171.6 | 2200 |

基线与迁移后结果均满足原门禁，未调整 benchmark 或阈值。单机小样本会受缓存、负载影响，不据此宣称性能提升。既有 benchmark 部分子进程指标不检查退出码，因此同时依赖完整测试中的启动行为回归，不以耗时单独证明功能正确。

冻结源码清单 /tmp/yaicli-s1-source-hashes.json 包含 yaicli/、tests/ 下 212 个 Python 文件；最终测试和构建结束后重新比较，文件集合及 SHA-256 全部一致。此后只补充任务记录。

## 验收条件映射

| 条件 | 已验证的行为 | 证据与状态 |
| --- | --- | --- |
| S1-A1 | 24 条主命令、三个斜杠别名及 ? 的独立固定契约；帮助/补全顺序、大小写、原始参数、近似名称、无参命令尾部和检查点非法参数 | 命令特征测试、198 项相关回归及最终完整测试通过 |
| S1-A2 | 三种 provider 的既有 schema/筛选差异、模式与缓存、MCP 懒加载、用户同名覆盖 | tests/test_tool_schema_filter.py、tests/tools/、tests/llms/ 及完整测试通过 |
| S1-A3 | 权限优先级、确认生成器、非交互及规则路径；真实允许/拒绝到工具执行、审计、消息配对和后续 provider 请求；持久授权失败回退 | tests/test_permissions.py、tests/test_plan_shell_gate.py、tests/tools/test_execution_contract.py 及完整测试通过 |
| S1-A4 | 真实文件写入/拒绝、既有撤销与回退、单次截断和完整输出记录；多工具 NDJSON 顺序；实际工作线程取消、锁、检查点及下一轮安全基线 | tests/tools/test_execution_contract.py、tests/test_refactor_integration.py、既有安全/检查点/展示测试及完整测试通过 |
| S1-A5 | 单一命令和缓存定义、纯 policy、executor/display 分工、薄兼容入口、cfg/console 注入、懒加载及安装包模块完整 | 独立审查与本地全部门禁通过；提交/PR/CI/合并仍待后续完成 |

S1-A4 的取消回归用 Event 控制真实写入前后时点，走实际 Printer/ThreadedStream/guard/capture/store，不以 sleep 或只 mock 入口代替文件和状态断言。保留现有两个 turn_start 事件及 ok 标志语义，不借测试改写产品行为。

## 兼容边界与剩余限制

只实现第一阶段职责迁移，保持现有命令、配置、provider 差异、schema、工具返回值、确认/审计/消息顺序和文件数据格式。保留 Gemini 已有筛选/MCP 差异、MCP 名称原地处理及 ok 标志的既有含义，不趁重构修正产品语义。

本地完整测试使用 Python 3.12；已检查改动文件的 Python 3.10 语法，3.10/3.13 实际运行仍由现有 CI 矩阵复核。多应用运行时状态隔离属于第三阶段，本阶段通过不表示已实现该目标。

第一阶段已于用户授权后提交 b7d3ce41d6c9050e03b7a35e3764d4d2c2181470，任务保持 in_progress，等待最终统一 PR/CI/合并。用户于 2026-11-27 授权自主完成全部重构，后续阶段在同一分支串行验收和提交；此交付调整取代原先每阶段先合并的门禁。合并仍需用户明确授权，无数据迁移，按阶段 3 -> 2 -> 1 逆序回退。

## 统一PR交付进度（2026-11-28）

三个阶段已分别提交b7d3ce4、66db062、0bb6415并推送，统一PR [#60](https://github.com/belingud/yaicli/pull/60)目标master。第三阶段完整hash为0bb64158dfe1c1744cda4fed1b73d971ab0cef48。后续任务元数据/日志独立提交，不改已冻结产品与测试；最新head CI通过后仍需用户明确批准合并，未提前归档或发布。
