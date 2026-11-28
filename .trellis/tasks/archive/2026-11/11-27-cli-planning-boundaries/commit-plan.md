# 第二阶段提交计划

## 授权与分支

用户已授权自主完成全部重构。沿用 chore/refactor-command-tools，基线 b7d3ce4；本阶段完整本地验收后独立提交，最终与第三阶段统一创建目标 master 的 PR。合并仍需用户明确确认。

## 提交内容

- 提取 application 的会话协调、机器输出及运行状态；CLI 保留组装、交互和线程生成控制。
- 提取明确依赖的计划协调器与 session/planning/runtime 命令服务。
- 归拢 planning 的模型、校验、存储、服务、提示和编辑器；旧模块保留显式兼容导出。
- 保持旧数据格式、事件、退出码及副作用顺序，适配测试真实绑定并增加独立服务契约。
- 更新本次直接涉及的架构/规范、阶段交接和验收证据。

建议提交信息：refactor(app): separate session output and planning coordination

## 提交前核验

- 独立 checker 已确认全部本地门禁通过；完整测试 3173 passed，原性能门禁全部通过，详见 verification.md。
- 显式暂存本任务的 yaicli、tests、docs/dev/architecture.md、相关规范及四个任务目录。
- 排除预先存在的 .trellis/.template-hashes.json、.agents/skills/trellis-start、trellis-continue、trellis-finish-work 和 .codex；不使用 git add .。
- 复核已暂存 diff、git diff --cached --check，提交后确认哈希和剩余无关改动。
- 本提交后以前置验收证据重核第三阶段接口，再启动第三阶段；不提前发起合并或发布。
