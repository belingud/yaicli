# 第二阶段技术设计

## Preconditions

第一阶段已验收并提交 b7d3ce4，完整测试 3152 passed。用户已授权自主推进所有阶段；本阶段在共同分支继续，以该提交为基线。已核对 commands/registry.py 及 tools/schemas.py、policy.py、executor.py、display.py；模块名可以作等价调整，但不能以重命名代替职责迁移。父任务兼容约束继续适用。

## Modules and direction

~~~text
entry -> CLI
          ├─ application/session.py -> Chat/FileChatManager、CheckpointStore
          ├─ application/output.py -> 结果/事件及退出状态映射
          ├─ planning/coordinator.py -> planning 服务、存储、UI 适配
          ├─ commands 的薄 handler -> 上述明确服务
          └─ 交互循环、生成线程、Printer
~~~

application/ 仅容纳已存在的协调职责，不设通用服务定位器。命令处理接收其实际使用的服务和展示依赖，不传入整个 CLI，也不以几十个回调重建 CLI 的隐式接口。

## SessionController

- 封装当前聊天对象、实际存储目录和聊天管理器，以及保存、加载、恢复、检查点准备/重置/回退操作。
- 将会话元数据应用、重试快照失效和历史变更后的上下文刷新暴露为明确操作；一次变更返回必要结果，由命令层按原文案展示。
- 状态只保留一份；CLI.chat、is_temp_session 等公共兼容属性转发到同一会话状态，不能复制后人工同步。
- checkpoint worker 的启动、关闭、存活查询仍属于 CLI 生成生命周期；协调器通过明确的生命周期输入决定能否提交/重置捕获，不接管终端线程。
- 保存回调、writer lock 和文件 mutation lock 顺序保持；不把 CheckpointStore 私有加载逻辑继续散落到命令处理层。

## Machine output

application/output.py 承担现有 _build_result、事件序列化、文本结尾、错误/用量 payload 与退出状态映射。使用显式状态参数和输出通道，不在序列化时构造 provider 或修改会话。

CLI 暂保留 entry 消费的公共标志，通过委托映射到同一结果状态。Printer 中必要的流式消费继续存在；不因抽出结果格式而重写 ThreadedStream 或确认 generator。

## Planning package

| 逻辑分组 | 来源及职责 |
| --- | --- |
| model | PlanSession、TodoItem、RevisionDiff、模式及进度等模型 |
| validation | submit_plan/todo_write 输入校验、步骤构造 |
| store | 现有 plan_store 的数据/Markdown/索引及原子文件操作 |
| service | 计划审批、修订、暂停、恢复、完成和审计等状态操作 |
| prompt | 系统上下文、todo 摘要及相关纯格式化 |
| editor | 编辑器草稿/调用，延迟依赖终端和进程 |
| coordinator | 原 CLI 计划业务，连接服务、保存会话和交互面板 |

实际仅拆出有清晰边界的模块；相关短逻辑可合并。模型、校验、存储不导入 CLI/Printer；协调器接收消息生成、面板交互和会话操作的窄依赖。

旧 plan_mode.py/plan_store.py 保留必须的兼容导出，使用同一类对象和状态入口；不能以 import-star 和重复全局变量复制实现。阶段三前继续接入原默认 PlanSession，不提前创建第二套运行时。

## Command boundary

将相关命令按会话、计划、运行设置分组，可新增 commands/session.py、commands/planning.py 等。CmdHandler 保留薄分派兼容入口。模型/角色切换和 retry 暴露命名操作，避免 command handler 直接写 _client/_last_turn_snapshot。

错误处理和文案在原有展示位置保持；抽出服务并不等于把 Rich 输出带入存储/模型。优先使用已有类型，只有跨边界结果确实需要时再增加小 dataclass。

## Validation / rollback

先提取机器输出，再迁移会话操作及计划包，最后调整命令依赖；各步保留行为测试。重点验证配置 root 与 cwd 不同、会话恢复/副本、fork 失败补偿、确认 send、Ctrl+O 和工作线程取消。

数据格式不变。回退本阶段提交可恢复到第一阶段组织；第三阶段提交后，必须先回退第三阶段。任务完成后更新架构图、相关规范及第三阶段上下文，最终统一 PR。
