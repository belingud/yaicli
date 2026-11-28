# 执行清单

- [x] 读取真实debug日志和源码，区分生命周期证据与正文/重绘证据。
- [x] 并行只读研究provider/client与终端路径；固定假流与独立grapheme复现。
- [x] 查上游官方问题、发布及Python兼容信息，明确最小依赖修复边界。
- [x] 实现代理增加真实Printer/Live回归，在旧Rich14.0.0上记录4失败/4通过的红灯。
- [x] 定向升级现有Rich最低版本与锁定版本至14.3.3；其他包版本/source不变；192相关通过、26组独立重放首句均一次。
- [x] 本地3206个不同测试已验证（3203通过+3沙箱准备错误后同hash补跑通过），静态、文档、构建、3.10 AST与原启动门禁通过；远端Python矩阵待最新提交CI。
- [x] 独立checker验收E1—E5本地技术部分，补足真实工具执行/debug集成证据；主线程更新规范与长期验收记录。
- [x] 单独fix提交1b63b42；更新会话与PR说明，随后推送当前分支。
- [x] 检查最新head CI（Python 3.10/3.12/3.13等）。
- [x] 用户明确批准后才合并和归档；用户已于2026-11-28明确批准合并，PR60已合并。

## Evidence

原调查：../11-27-session-state-boundaries/research/debug-stream-display.md与debug-stream-protocol.md。独立26组终端重放/tmp/yr-vz13u19p/emoji-probe/results.json；实现和检查结果后续追加verification.md。临时日志不能替代长期摘要。
