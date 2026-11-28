# Bug Analysis: VS16宽度与Live旧帧残留

## 1. Root Cause Category

- **E 隐式假设 / B 跨层契约**：Rich14.0.0认为☀️占一列，支持VS16的终端显示两列。Live补满行后多出一列，自动换行数超出清屏/光标回退的预期，首句不断进入滚动历史。
- **D 测试覆盖缺口**：原测试确认了内容、调用和流控，却没有独立核对实际显示列数。3196项全绿不能证明真实终端没有此类缺陷。

## 2. Why Earlier Conclusions Failed

最初把带空格的重复文本视为可能的原始刷新帧，且简化屏幕重建器同样忽略VS16，得到一次首句的假阴性。没有据此修改产品或对正文去重。随后使用独立grapheme/wcwidth重建纠正：26组实际Rich输出，在四种视口、☀️和❤️条件下均从一次输入/返回内容产生108次可见残留，对照字符均一次。

现有真实debug日志只记录generation/watcher生命周期，既不能证明成功，也不能排除模型重复；没有Ctrl+O/查看器事件只用于缩小本轮路径。provider/client十组假流与45相关回归表明正常增量不会在该层自行复制，不能扩大为已捕获用户真实上游数据。

## 3. Prevention Mechanisms

| 优先级 | 机制 | 实际动作 | 状态 |
| --- | --- | --- | --- |
| P0 | 上游修复 | 现有Rich下限与锁定版本定向升级至14.3.3 | 已完成，本地独立验收通过 |
| P0 | 独立测试量尺 | 真实Printer/Live帧用wcwidth测列，旧版先失败，再验证新版 | 已完成，旧版4失败/4通过；新版10项通过 |
| P1 | 验收边界 | 分开最终正文、原始ANSI帧、屏幕/滚动历史；不再共用被测宽度算法作排除依据 | 已写py规范与cross-layer指南 |
| P1 | 日志解释 | generation.end为finally；现有debug日志不记录chunk或正文，不扩大收集 | 已写debug-cli文档 |

## 4. Systematic Expansion

太阳/心形VS16是本次确定复现；中文、普通emoji与无VS16对照用于防止误归因。ZWJ、多码点、工具面板及终端尺寸继续由定向回归和上游支持覆盖，不引入手写Unicode表、通用内容去重或并发框架。问题在重构前的Rich锁定版本同样存在；使用独立fix提交，保持前三阶段回退边界。

## 5. Knowledge Capture

- [x] 更新py/cli-and-rendering.md的依赖下限、具体失败机制和独立断言点。
- [x] 更新repo/build-and-release.md的定向锁及质量门禁要求。
- [x] 更新cross-layer-thinking-guide.md的独立终端测量检查项。
- [x] 更新docs/dev/debug-cli.md的日志限制、环境版本检查和排查方法。
- [x] 建立独立缺陷任务与执行记录；本仓库不存在src/templates/markdown/spec，不创建无关模板目录。
- [x] 实际修复与独立本地验收通过；原始8项工具打印证据不足，补2项真实执行集成回归，共3206个不同测试已验证，详见verification.md。
- [ ] 单独fix提交、最新PR CI另行记录；用户明确批准后才合并和归档。
