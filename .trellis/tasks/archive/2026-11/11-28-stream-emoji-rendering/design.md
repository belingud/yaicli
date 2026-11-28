# 技术设计

## Root cause and boundary

Printer.display_stream把累计Markdown交给Rich Live；Live依据自己的cell长度计算行尾padding和清除高度。旧Rich将U+2600 U+FE0F计为一列，支持VS16的终端显示两列，满宽帧额外换行，旧帧遗留到scrollback。现有简单终端重建器也按单字符测量，曾得到屏幕仅一次的假阴性；已用regex分grapheme与独立wcwidth重建纠正。真实日志主要用于排除本轮Ctrl+O/查看器操作，不足以证明模型没有重复。

## Minimal fix

pyproject.toml将rich下限提高至>=14.3.3，uv.lock仅定向选择rich14.3.3（上游14.3.0修VS16，14.3.3含后续grapheme修复，支持本项目Python3.10）。不复制上游宽度算法或改正文，不引入新的运行时依赖。运行时产品Python文件原则上无需修改。

## Tests and ownership

实现代理拥有pyproject.toml、uv.lock、新增tests/test_stream_unicode_width.py，以及必要的现有渲染测试预期适配（必须先报告Rich既有Markdown样式变化，不放宽断言）。先在旧Rich上固定真实Printer/Live帧与最终文本，独立wcwidth测量宽度，记录红灯再升级。可使用已有prompt-toolkit依赖携带的wcwidth作为测试独立量尺；不要新增regex依赖，复杂grapheme模拟仅留/tmp诊断脚本。

主线程拥有任务文档、py/cli-and-rendering与repo/build-and-release规范、docs/dev/debug-cli.md的必要说明和PR/提交。checker独立检查源码/lock范围及真实行为。所有进程使用隔离HOME/假配置/假provider，无真实API、MCP、env文件或密钥读取。仅主线程经用户明确授权读过真实debug.log；不得扩大到其他真实配置/历史。

## Compatibility and rollback

Rich14.3更改了部分Markdown默认样式；需要实际相关测试、完整套件、headless契约、文档构建和启动门禁验证，不以升级即修复。Python3.10/3.12/3.13保持支持。独立fix提交在现有三阶段refactor之后，可单独revert；本次不改版本、数据协议或配置项。
