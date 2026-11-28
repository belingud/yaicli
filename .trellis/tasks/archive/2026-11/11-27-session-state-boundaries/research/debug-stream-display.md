# Research: 调试日志与流式终端重复显示

- Query: 用户在一次 get_weather 调用后看到首句“今天杭州天气不错，是个晴天 ☀️”重复数百次，并补充使用 yai_debug_log=1 启动；调查 debug logging / Rich Live / terminal renderer 路径，不检查 provider 增量归一化。
- Scope: internal；产品和测试只读；仅在本文件及 /tmp 写入调查结果。
- Date: 2026-11-28
- Baseline: 主线程提供分支 chore/refactor-command-tools、HEAD 7408c51、PR #60；未执行 git、改产品/测试、提交、推送或合并。

## 2026-11-28 追加复核：已验证的 emoji 宽度缺陷

**本节取代下文早期“普通屏幕重建只出现1次，因此更像捕获保留刷新帧”的排除依据。** 早期自包含模拟器使用单字符 East Asian Width 并忽略 U+FE0F，与 Rich 14 的按码点宽度假设具有同源缺陷。该模拟器可以处理 CSI，却无法发现 VS16 emoji 导致的额外换行。此处明确撤回用早期 screen_prefix_count=1 排除真实屏幕残留的判断。原始字节、返回正文、debug开关逐字节一致性和既有日志事实不变。

### 严格结论

**已验证一个足以造成用户所述重复残留的代码根因，而不再只是原始帧被复制的假设：Rich 14.0.0 将 ☀️ 的显示宽度低估1列；Markdown 左对齐将其填充至整个终端宽度，实际按 emoji 2 列显示的终端便在每帧额外换行；Live 按旧宽度推导出的行数回退光标，少回退一行，导致首句进入滚动历史。** 固定输入、Printer返回值都只有一份正文，独立字素宽度屏幕模型却留下数百份首句。触发条件是终端把该 VS16 字素显示为2列；本调查没有在用户实际终端测量该列宽，因此这是已复现的条件性根因、并与具体症状高度吻合，而非宣称已观察用户终端内部状态。

### 宽度与填充的代码因果链

- 本地 Rich 14.0.0 的 `rich/cells.py:34-48,51-64` 对每个码点的 get_character_cell_size 求和，没有按字素处理 VS16/ZWJ。
- 本地直接测量：`rich.cells.cell_len("☀️") == 1`；独立 `wcwidth.wcswidth("☀️") == 2`。`❤️` 同为1对2；`☀` 为1对1；CJK `天` 和 `🙂` 都为2对2；`👩‍💻` 为4对2。
- `yaicli/printer.py:527-528,1036` 将全文交给 Markdown 并逐增量刷新 Live。
- 本地 `rich/markdown.py:119-129` 将段落设为 left；`rich/text.py:1241-1244` 进入 Lines.justify；`rich/containers.py:129-131` 对左对齐执行 truncate(width, pad=True)，从而补齐行尾空格。
- 在60列视口，含 ☀️ 的完整首句帧 Rich测量60列，但独立字素宽度61列；200列视口则为200对201。末尾多出的空格触发自动换行，虽输入没有换行，实际占用行数仍增加。
- `rich/live_render.py:47-65` 的 CR/EL2/CUU 回退只依据 Rich自身记录的shape高度，无法抹去额外自动换行前的首句。重复刷新使该行不断进入scrollback。
- 不增加provider轮次、不重复工具调用、不改变返回全文，也无需debug写入、Ctrl+O、线程并发或特殊长panel即可触发。

### 独立字素宽度复现

脚本 `/tmp/yaicli_emoji_width_probe.py` 使用已安装的 `regex` 进行 `\X` 字素分簇，以已安装的 `wcwidth 0.2.13` 的 `wcswidth` 测量整个字素；正确模型不调用 Rich 的宽度函数。另保留 Rich宽度模型作为对照。未安装新依赖。

- 26组真实Rich输出矩阵已完成，总8.37秒；证据 `/tmp/yr-vz13u19p/emoji-probe/results.json`、`*.raw.txt`、`*.grapheme-screen.txt`。
- 四种视口：60×12、200×12、60×6、200×6；每次仅一次 RefreshLive、一次工具调用行、一个20行长工具panel，首句只yield一次，再用3字符增量完成唯一正文。
- 每组 `input_prefix_count=1`、`returned_prefix_count=1`、`returned_equal=true`、`tool_call_count=1`，无未知控制序列。

| 假流末尾字素 | Rich / 独立宽度 | 四种视口屏幕+scrollback首句次数 | 额外自动换行 | 同一raw移除行尾填充后次数 |
| --- | --- | --- | --- | --- |
| ☀️ | 1 / 2 | 每种均108 | 每种均108 | 每种均1 |
| ❤️ | 1 / 2 | 每种均108 | 每种均108 | 每种均1 |
| ☀ | 1 / 1 | 每种均1 | 0 | 每种均1 |
| 天 | 2 / 2 | 每种均1 | 0 | 每种均1 |
| 🙂 | 2 / 2 | 每种均1 | 0 | 每种均1 |
| 👩‍💻 | 4 / 2 | 每种均1 | 0 | 每种均1 |

另外60×12、200×12两组只用短工具结果、去掉panel仍为108次残留。长panel是用户场景的一部分，却不是根因必要条件。ZWJ样例被Rich高估，造成欠填充但本矩阵不会触发相同的行尾溢出；不能把所有emoji笼统视为同一种问题。

为避免只在StringIO构造中复现，已用同一独立模型重新播放上轮保存的真实PTY字节：

- `/tmp/yr-_5mraw_k/probe/short-debug-{0,1}.pty.raw.txt`：独立模型各留下9次首句，Rich宽度模型各为1次。
- `/tmp/yr-_5mraw_k/probe/long-debug-{0,1}.pty.raw.txt`：独立模型各留下463次首句，Rich宽度模型各为1次。
- 重放命令及实际输出保存在隔离runner的 `/tmp/yr-5iq2h1s1/stdout.txt`；因此上轮“真实PTY+旧模拟器仍正常”的排除结论也一并撤回。

只移除同一raw的行尾空格便消失，是因果对照，不是提出修改用户正文或去重方案；未对产品输出应用这一处理。

### 修复范围建议

- 优先由主线程核对并验证现有 Rich 依赖的最低版本与定向锁文件升级。主线程已查官方 Rich #3897/#3930 及 14.3.x 多码点字素支持/修复资料；本代理没有再次浏览其页面，不把尚未在本矩阵运行的版本宣称为已修复。
- 避免应用层修改首句、删除VS16/emoji、正文去重、Unicode表或全局monkeypatch；这些不能修复 Rich 宽度和Live行数的一致性。
- 升级候选需重跑本矩阵及现有 Printer/render/worker/headless定向测试。验收应是 VS16 在独立宽度模型下首句只留1次、返回正文完全相同、工具行仍1次、非TTY最终输出契约不变。
- 原有debug文件sink独立于根因，仍没有证据支持“debug导致内容重复”。实际既有日志缺少chunk/render指标的限制仍成立。

## 早期调查记录（宽度模型结论已由上节更正）

### 结论与确定性

1. **已确认：调试辅助函数只有文件 sink，不会把模型正文打印到终端，也不修改 Console/Live。** `yaicli/debug_log.py:27` 精确读取 `os.environ.get("YAI_DEBUG_LOG", "").strip()`。`31` 对值作 lower() 以识别 1/true/yes/on，并非对环境键名作大小写转换。`32-36` 决定默认 CONFIG_DIR/debug.log 或显式路径；`37-41` 只 mkdir/open("a")/write 事件、传入字段和线程名。当前 POSIX 进程中单独设置小写 yai_debug_log 不会触发该函数。不能据此断言用户的实际启动命令一定用了小写；用户后续提供的既有日志说明相应运行至少存在有效诊断来源。
2. **已确认：标准 TTY 的原始输出天然包含重复整块刷新帧。** 固定且不重复的假流，经真实 Printer 与 Rich 14.0.0 渲染，返回全文首句为 1 次，TTY 原始字节中可有 463/693 次首句，工具调用行仅 1 次；行尾被填充至终端宽度。在本次 60 列 PTY 中首句每帧尾随 32 个空格。这与用户文本中“同首句大量重复、带整行宽尾空格、工具行只出现一次”的形态吻合。
3. **早期假设，现不得作为排除依据：用户实际故障可能是重绘帧被复制或捕获后摊平。** 标准 ANSI 语义要求光标上移、清行后覆盖旧帧；将 CSI 控制码直接去掉而保留所有正文，会把正常刷新变成重复行。早期假流可复现这一原始字节/纯文本形态；后续独立字素模型已确认另一条能造成真实屏幕残留的Rich宽度缺陷，见报告开头。用户具体终端和复制路径仍未直接测量。
4. **已确认：普通非 TTY/TERM=dumb 边界不会逐增量输出所有刷新帧。** 同一固定假流只在停止 Live 时输出最终正文一次，首句 1 次，工具行 1 次。不能把“非 TTY 正常”推广为“TTY 不会有问题”。
5. **已确认：在确定性假流中，开启大写 debug、仅设置小写变量、关闭 debug，以及启用 ThreadedStream 的普通路径，其 TTY 输出逐字节相同。** 开启大写值时只有额外假 debug 文件；小写独立设置不生成文件。真实 PTY 的短/长正文分别再次比较开启/关闭大写 debug，原始 stdout 逐字节相同。
6. **尚无证据支持本次重构引入 Live 主体缺陷。** 主线程导出的 master/HEAD 七个显示文件中，console.py/debug_log.py/generation_keys.py/render.py/stream_bridge.py/worker_console.py 完全一致；printer.py 仅 import 排版和 plan_store 导入路径变化。当前显示主体逻辑未变。CLI 的依赖组装/上下文变化仍可能改变调用环境，不能仅以显示文件不变排除所有间接回归。

### 最新实际日志所能证明的边界

主线程在用户授权后读取既有日志并转交摘要；本代理没有读取真实用户日志文件。最新一轮为：

- 2026-11-28 13:19:28 prompt.begin。
- 13:19:30 generation.begin interactive=True；watcher.start fd=0 cbreak=True discard_disabled=True flow_control_disabled=True；watcher.ready started=True。
- 13:19:44 generation.end；watcher.stop pending=0；prompt.begin。

该轮没有 watcher.ctrl-o、printer.pause.request 或 viewer 事件。因此不能将这次故障归因于用户打开/关闭查看器；`generation.end` 在 `yaicli/cli.py:1349-1350` 的 finally 内，正常返回、异常处理及取消清理都可能产生，不能据此断言成功完成。该日志只确认本轮进入了交互式生成与清理生命周期，没有 chunk 数、chunk 长度、完整正文或历史内容，**不足以区分模型真的输出重复与终端重绘残留**。它也不能单独证明未发生 ANSI 执行/复制兼容问题。

### 代码路径与文件

| 文件 | 作用及关键行 |
| --- | --- |
| yaicli/debug_log.py | 25-43 文件诊断 helper；27 大小写精确读取；31-41 路径与 sink。 |
| yaicli/console.py | 20-77 YaiConsole 仅设置默认 justify 后调用 Rich；80-97 stdout/stderr 单例。 |
| yaicli/printer.py | 572-582 创建 Live(auto_refresh=False)；584-587 安全 stop；599-608 查看器暂停/恢复；999-1016 工具轮次 RefreshLive 停止/重建并清空累积；1018-1036 追加 delta 后用累积全文更新 Live；1048-1056 finally 收尾并返回全文。 |
| yaicli/printer.py | 474-500 只按输入 delta 追加 content/reasoning；502-540 将累积全文交给 Markdown/Group。没有首句去重逻辑，也没有凭空复制正文的循环。 |
| yaicli/cli.py | 1270-1276 绑定配置、diagnostic begin、Assistant 标签；1281-1314 watcher/ThreadedStream/routing 组装；1316-1323 把唯一 iterator 交给 Printer；1350-1379 结束与 worker/watcher 清理。 |
| yaicli/cli.py | 1381-1399 watcher 仅交互式非机器模式启动；1402-1410 worker console 事件在主线程 replay；1412-1439 临时替换并恢复 client/provider console。 |
| yaicli/stream_bridge.py | 128-133 copy_context 后启动单 worker；135-162 逐项进入同一 FIFO；178-215 每项完成或 replay 一次，无内容缓存重复发送；217-223 仅确认后 send。 |
| yaicli/worker_console.py | 42-61 主线程直接 real.print；worker 按所属 bridge 入队；dead bridge 丢弃；90-118 路由工具及 stderr 单例。 |
| yaicli/generation_keys.py | 112-135 cbreak + watcher；167-172 只有 viewer_requested 事件置位才返回暂停请求；208-223 按读取字节识别 Ctrl+O 并记录。debug 文件写入本身不置位 viewer 请求。 |
| tests/test_printer.py | 385-408 RecordingLive 只记录 renderable，不执行真实控制码；无法单独排除终端重绘残留。 |
| tests/test_worker_console.py / tests/test_stream_bridge.py | 已有 worker FIFO/路由测试；本调查未重复完整门禁。 |
| docs/dev/debug-cli.md | 75-105 官方项目说明：debug 文件和事件名，没有 stream 内容诊断承诺。 |

### Rich 14.0.0 的本地实现证据

版本由隔离解释器 importlib.metadata.version("rich") 取得。读取安装包源代码，没有访问 .env 或真实配置：

- `.venv/lib/python3.12/site-packages/rich/live.py:109-132`：注册 render hook；auto_refresh=False 时不启动 Rich 刷新线程。
- `live.py:213-218`：update(refresh=True) 立即 refresh。
- `live.py:240-247`：正常 TTY 进行实时刷新；文件/dumb 终端在停止且非 transient 时只保留最终结果。
- `live.py:145-156`：stop 把 vertical_overflow 变为 visible 并进行最终 refresh，最后换行/恢复光标。所以“之前是带填充的短帧，最后出现完整长正文”本身是正常 Live 停止行为。
- `.venv/lib/python3.12/site-packages/rich/live_render.py:47-65`：每次定位发出 CR、EL2、逐行 CUU1/EL2。
- `live_render.py:90-106`：渲染超过视口时使用 crop/ellipsis 限制刷新区域；此行为和最终 visible 刷新不同。

没有将外部文档或未验证的 Rich issue 当作归因依据；本地实际安装版本及其实现是本调查的第三方参考。

### 最小复现与证据

所有运行通过已有 `/tmp/yaicli_refactor_run.py`，提供私有 HOME/YAI_CONFIG_DIR，移除 ambient YAI_*/XDG_*/凭据变量；脚本只注入显式假 API key 以满足模块导入，不构造 provider、不请求 API、不读 .env、不启动 MCP、不读取用户真实 debug.log。实际用户历史未在该假流实验中构造，因此下面“正文”仅指 Printer 返回值，不能冒称已验证真实持久化历史。

1. `/tmp/yaicli_debug_stream_probe.py`：真实 Live + StringIO(force_terminal=True/False)，一次 RefreshLive、一次工具行与结果、首句仅 yield 一次，再逐字添加余下正文；可选 ThreadedStream 与 WorkerConsole。12 组矩阵，运行约 9.87 秒。
   - 证据目录 `/tmp/yr-if60ycua/probe/`；`results.json`、`*.raw.txt`、`*.transcript.txt`、`*.screen.txt`。
   - 基准长正文：returned_equal=true，返回首句1次，raw首句693次，工具行1次，570490 bytes。
   - debug upper/lower/off、bridge、原生 Rich Console 对比基准 byte_equal=true。
   - bridge 中额外假 console 事件仅增加合法重绘帧（raw首句700次），未改变返回正文。
   - 非TTY与dumb：raw首句1次。
2. `/tmp/yaicli_debug_pty_probe.py`：os.openpty 设置 60×12 实际 TTY，子进程真实 stdout.isatty() 和 console.is_terminal 均为 true；短/长固定正文×大写debug开/关，单个子进程8秒超时，总运行约3.34秒。
   - 证据目录 `/tmp/yr-_5mraw_k/probe/`；`pty-results.json`、`*.pty.raw.txt`、`*.pty.transcript.txt`、`*.pty.screen.txt`、`*.stderr.txt`。
   - 长正文返回首句1次，raw首句463次，工具行1次，354178 bytes，首句帧尾空格32个；debug开/关raw逐字节相同。
   - 短正文返回首句1次，raw首句9次，工具行1次，debug开/关raw逐字节相同。
   - 早期简化 ANSI 屏幕重建器得到首句1次，但忽略VS16，结果已被开头的独立字素复核推翻，不能用于排除屏幕残留。
   - 限制：PTY 提供真实终端检测与字节传输，屏幕重建器是本调查自包含的有限实现，并非用户的真实终端模拟器；它支持本次所有控制序列，但不能替代用户环境重现。
3. 附加发现，**不应当作本次根因**：主动模拟一次查看器 pause 后，`_safe_stop_live()` 会把旧部分正文留在屏幕，恢复时新 Live 重绘累积全文，屏幕首句可变为2次。该路径需要实际 pause 请求；最新用户日志没有相应事件，不能解释当前无按键证据的百次重复。

可重新运行的命令（不含真实配置或 API）：

```bash
python3 /tmp/yaicli_refactor_run.py .venv/bin/python /tmp/yaicli_debug_stream_probe.py
python3 /tmp/yaicli_refactor_run.py .venv/bin/python /tmp/yaicli_debug_pty_probe.py
```

### 对本次变更的历史对照

本角色禁止 git 操作，历史数据由主线程导出后只读：

- `/tmp/yaicli-debug-history/master/yaicli/` 与 `/tmp/yaicli-debug-history/HEAD/yaicli/`。
- `/tmp/yaicli-debug-history/display-master-head.diff`（已实际读取）。
- printer.py 的差异仅多行 import 排版及 `_shorten_plan_path()` 的 `from . import plan_store` 改为 `from .planning import store as plan_store`；非计划天气回答不会走该 helper。其余六个文件与 master 一致的结论来自主线程导出说明。

### 建议的最小后续验证

- 优先执行开头的Rich依赖候选修复与独立字素回归；用户实际终端列宽/复制边界可作为旁证，无需将再次索取用户证据作为继续排查的前提。无需读取用户提示词、配置或密钥。
- 与另一代理的 provider/消息历史调查合并；只有实际累积 content/历史重复，才定位到增量内容路径；当前假流实验证据不能替代实际 provider 结论。
- 若要增加诊断，优先只记录每轮 content 增量数量、增量总长度、最终累积长度、Live 刷新数、终端宽高、console.is_terminal/dumb；保持现有秘密与正文不入日志的约束。另记录“当前chunk是否空内容”可检查无效刷新放大，但不应先修改正常delta语义。
- 添加与实际故障对应的回归时，至少保留真实 Live 的 TTY/非TTY输出契约、单次 Refresh工具行、唯一正文返回；不能仅用 Mock Live 或 raw 文本中首句计数作为失败依据。屏幕模拟应处理 ANSI 覆写语义。
- 目前不建议按“debug 导致正文重复”直接修改 logger、强行去重首句、关闭所有流式输出或改变 provider 语义。

## Related specs

- `.trellis/spec/py/cli-and-rendering.md:196-208`：worker、viewer、主线程渲染所有权；230-246 确认与 RefreshLive 协议；290-308 Live 和 reasoning 约束；310-334 console/stdout/stderr。
- `.trellis/spec/py/quality-guidelines.md:50-81,127-146`：模块导入前假凭据、隔离 HOME/配置、不调用真实 API、不触及用户状态。
- `.trellis/spec/guides/cross-layer-thinking-guide.md`：沿 provider→generator→bridge→Printer→terminal 跟踪不同层的数据形态，避免把投影当成源数据。
- 当前任务 prd/design/implement：配置和计划状态边界重构；console 等无关单例不在全面改造范围。
- `/Users/vic/.codex/DEVELOP.md` 与仓库 AGENTS.md：先证明假设、最小修改、可验证完成标准。

## Caveats / Not Found

- 研究角色隔离禁止读取 implement.jsonl/check.jsonl；任务目录只有这两个 jsonl，因此依 dispatch 指示以 PRD/design/implement 和相关规范为上下文，没有加载二者。
- 未检查 provider 增量归一化，按分工交由另一代理；没有将模型或 SDK 重复排除。
- 用户实际终端、复制/日志捕获路径、宽度变化、远端连接及 ANSI 支持尚未取得，不能宣称用户故障已复现或已修复。
- 实际 debug 日志没有正文、token/chunk数量、Live刷新计数，不能从 generation.begin/end 推断内容唯一性。
- 未执行全套测试、修改产品/测试或评估 PR 合并；本轮产出仅用于主线程决定下一步定位范围。
