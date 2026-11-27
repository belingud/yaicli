# 第三阶段技术设计

## Preconditions and limits

前两阶段已合并；重新审查实际调用链和所有受影响配置读取点。本阶段在新模块边界上调整依赖来源，不再次大规模移动代码。总体兼容要求见父 design.md。

会话隔离覆盖实例状态以及交替/串行执行，进程级 cwd 和外部程序副作用保持原限制。不承诺同进程并行应用，也不以本阶段扩展产品能力。

## Minimal ownership

应用组装点创建轻量会话上下文，包含有效配置与唯一的惰性 PlanSession 引用，并创建使用它的具体服务；不使用字符串查找服务的容器。已有 CLI 依赖注入方式保留，首次使用计划功能时才导入并构造 PlanSession，普通启动不提前加载计划包。

配置来源仍为现有 get_config/Config 解析结果；不在各服务中重新加载文件或环境。为实例复制可变配置数据，包括嵌套 dict/list，运行时设置写入该实例。公开 Config/get_config 的行为和默认 cfg 保留。

CLI 创建内建客户端、权限服务及工具运行时的正常路径显式传入同一有效配置。对外部注入的 ready client 不擅自替换或重建实例，保留原注入契约；以工厂主路径和注入路径分别测试，不能为了真实路径统一而破坏测试/嵌入用途。

## Plan state and schema visibility

- PlanCoordinator、LLMClient、内部 submit_plan/todo_write 适配器引用同一个 PlanSession。
- 根据 session.mode 推导正常/计划/执行可见性，不再持有需同步的第二份 _plan_mode。旧 set/get 函数仅作用于默认兼容实例。
- schema 缓存按 provider 格式、实际模式、readonly shell 开关、工具选择及声明来源等影响结果的值区分；可共用不变的基础声明，不能修改缓存原对象。
- Gemini callback 在现有适配层绑定所属服务；不可把 session/config 字段加入模型 schema 或独立 Function.execute 签名。
- 不全局替换其他会话的 plan singleton 以临时冒充注入。确认 send/取消与计划修订的对象身份保持。

## Effective configuration

会话内参数修改必须触达后续消息构造、provider 参数、预算、工具选择、风险、执行限制和输出/脱敏通道。对本任务涉及的路径逐一追踪；不得只给 LLMClient 传新配置，而让 tools/limits/approval 等继续读旧 cfg。

从原默认配置创建实例后，普通 /model、/role、恢复会话及 auto OS/shell 解析仍依既有时机生效；内部更新同一会话数据，避免修改加载器默认值或其他实例。ProviderFactory 和用户配置优先级不变。

## Standalone tool environment adapter

保留独立工具通过环境读取 guardrail 的能力，兼容 builtin 和用户覆盖。内部工具执行前从所属有效配置生成受管理键的完整视图，而非从上一次调用残留环境猜测配置。

建议采用范围限定的环境适配：进入时保存受管理键，应用本次有效值/显式缺省，执行后在 finally 恢复；所有依赖同一环境的内部 guard、shell、undo 入口通过该适配边界。不要清空用户未受管理的环境键或更改工具环境白名单语义。

由于环境是进程级资源，适配使用专用可重入锁；统一顺序为环境适配锁 -> 既有 workspace mutation lock。检查点已持有的工作区锁路径不得反向取得环境锁。会话工作线程直接使用其绑定配置；取消导致线程尚未结束时仍保持既有 busy/barrier 处理，不能提前将同一执行上下文交给下一会话。

此设计在实现前先用 guard/undo、异常和流式工作线程做小范围验证。若现有调用边界无法安全维持上述锁顺序，回到规划调整适配，不删除独立工具兼容能力或降低隔离标准。

## Default compatibility and lazy loading

保留 get_plan_session、set_plan_tool_mode、工具 schema/execution 等必要默认入口；无显式会话时懒建默认适配，显式产品路径不回退。不要在模块 import 时加载用户文件、MCP、provider、计划/检查点存储或创建目录。

只移除已被本阶段替代的全局计划/模式同步逻辑。函数定义的共享只读缓存和 console 等无关单例不在本次全面重构范围内。更新相应规范，解释默认入口与实例入口各自用途。

## Validation / rollback

先加入可暴露跨实例污染的行为测试，再接入配置、计划、schema、执行和独立环境边界。验证实际返回、工具声明、文件字节及其他实例状态，不只断言对象 id。

保留现有隔离 HOME 与跨进程 root 回归。新增隔离测试应能在不调用全局计划 reset 的独立进程中运行，避免 conftest 自动清理掩盖问题。

数据格式不变，第三阶段为最后一个实现 PR；回退该 PR 不影响前两阶段模块组织。最终汇总父任务所有验收与架构说明。
