# 技术设计：代码组织渐进式重构

## Scope and ownership

父任务负责 R1—R4 的一致性和最终集成审查，不作为业务代码实现目标。每个子任务分别规划、实现、验证及合并；依赖顺序由任务文档约束，父子关系本身不代表依赖调度。

| 顺序 | 子任务 | 预期分支 | PR 目标 |
| --- | --- | --- | --- |
| 1 | 11-27-command-tool-boundaries | chore/refactor-command-tools | master |
| 2 | 11-27-cli-planning-boundaries | chore/refactor-cli-planning | master |
| 3 | 11-27-session-state-boundaries | chore/refactor-session-state | master |

本次规划文档分支：chore/refactor-core-organization。子任务分支在各自实现前从更新后的 master 建立；本轮不创建这三个实现分支。

## Intended boundaries

~~~text
_faststart -> entry -> CLI（应用组装、REPL、模式选择）
                       ├─ commands（定义、解析和薄命令处理）
                       ├─ session 操作（保存、加载、恢复、检查点协调）
                       ├─ machine output（结果、事件、退出状态映射）
                       ├─ planning（模型、状态转换、存储、协调、提示词、编辑器）
                       └─ LLMClient（请求、重试、预算、工具轮次）
                              ├─ Provider（协议适配）
                              └─ 工具权限判断 -> 确认 -> executor
                                                       ├─ function / MCP
                                                       ├─ workspace / checkpoint capture
                                                       └─ 输出截断、记录及展示
~~~

这是责任划分，不要求每一行都新增一个文件。仅为已有职责创建模块；短小且内聚的逻辑保持原状。

## Stage 1 — definition and execution boundaries

- commands/registry.py 扩展现有命令元数据，使处理函数、参数接收策略、帮助和别名来源一致。保留逐命令语法和未知输入语义。
- tools/schemas.py 管理工具选择、provider 声明及缓存；tools/executor.py 管理解析后调用、文件保护、捕获和结果通道；tools/display.py 管理工具公告和结果展示。
- tools/policy.py 提取权限评估，返回允许/拒绝/需确认及原因、来源等内部结果。确认生成器和消息追加仍由客户端驱动，避免改变 yield/send 协议。
- tools/__init__.py 保留现有公开函数的兼容入口和必要的懒加载；不把现有单体逻辑藏到另一个同样大的文件中。
- 普通内置、用户覆盖、MCP 和 submit_plan/todo_write 保持现有分派顺序；schema 与执行必须应用相同选择条件。

## Stage 2 — application orchestration

- 引入有明确依赖的 SessionController 和 PlanCoordinator，分别接收聊天管理器、会话数据、配置和必要回调；不得仅把整个 CLI 注入新对象。
- 抽出 machine output 的结果构造、事件输出和退出状态映射。原有 CLI 公共状态契约先以委托方式维持。
- planning/ 归拢现有 plan_mode.py 与 plan_store.py 的职责：model、validation、service、store、prompt、editor、coordinator。按实际代码内聚程度合并小模块。
- 老模块作为薄兼容入口；产品内部迁移到新入口。PlanSession 不复制为第二份状态，阶段三前仍沿用已有所有权。
- 将检查点中与保存会话相关的协调纳入 SessionController，底层 CheckpointStore 保持现有边界及格式，工作线程存活状态仍由交互生命周期控制。

## Stage 3 — session ownership

- 一个轻量会话上下文持有有效配置及惰性 PlanSession 引用；由应用组装点创建，并显式提供给协调器、LLMClient 和工具运行时。首次使用计划功能时才导入并创建 PlanSession。
- 配置加载仍通过现有 Config/get_config 规则，不在子系统中重新解析 INI/环境；会话配置从解析完成的配置复制并持有，隔离嵌套可变值，/model、/role 等修改仍对同一会话的后续请求生效。
- 工具可见性从该会话状态派生，不再依赖需要 CLI 手动同步的全局 _plan_mode 副本；缓存键覆盖实际筛选条件，避免跨会话污染。
- submit_plan/todo_write 的内部适配器接收所属会话；不修改模型看到的 schema 或用户 Function.execute 签名。若 SDK 回调不提供上下文，只在现有适配边界绑定所属实例，不把新状态塞入模型参数。
- 兼容的默认入口可在调用时懒建默认运行时；正常产品调用必须携带所属上下文，不能悄悄转向另一个会话的状态。
- 独立工具的环境传递保留为集中边界，使用当前有效配置；隔离测试覆盖交替执行、取消、异常后的后续调用。环境变量是进程级资源，本任务不承诺同进程多个独立应用并行执行工具。

## Compatibility and invariants

1. _faststart、entry、CLI、ProviderFactory 的用户入口及原有注入点继续工作。工具公共函数名和签名先保持；内部测试 patch 目标可以随责任迁移更新，但不能削弱行为断言。
2. 不改 schema 的字段、required、工具名称和执行签名；包内 builtins 优先加载、同名用户文件覆盖的顺序不变。functions/buildin/ 名称保留。
3. 权限优先级、dangerous shell 的特殊确认、readonly 硬限制、工具结果配对及审计一并冻结；不把需求转成可配置策略框架。
4. 截断只发生一次；模型文本、工具结果预览、完整参数及 Ctrl+O 详情继续分别保持现有语义。
5. 检查点的会话锁、workspace mutation lock、capture 生命周期和保存回调顺序不变；配置文件提供的 workspace root 必须在第一次工具执行之前生效。
6. 本任务不升级数据版本，不修改已有会话/计划/检查点 JSON。迁移只涉及代码路径。
7. 不添加启动时 provider SDK、fastmcp、prompt_toolkit、计划或检查点的额外导入/IO。启动性能沿用 scripts/bench.py 的既有门禁。

## Verification design

- 首次实现前记录完整 pytest、行为基线和启动 P50；每阶段再次运行相关子集和完整套件，跨阶段比较同一组确定性输入的 stdout/stderr、结构化事件、退出码和文件状态。
- 特征测试固定 provider 回复、时间/随机 ID 等非确定项，仅按现有契约规范化动态字段；不得用过宽快照掩盖字段或事件顺序变化。
- 使用隔离 HOME、YAI_CONFIG_DIR、临时工作区，启动子进程前移除继承的 YAI_*、XDG_*、PYTHONPATH；不访问用户配置、密钥或真实 provider/MCP 服务。
- 会话隔离测试使用两个实际运行时实例，交替切换模式、生成声明、执行工具并观察对方状态；注入不同工作区和限制值验证实际文件副作用。
- 更新 docs/dev/architecture.md 与相应 .trellis/spec/py/，旧规范中的历史描述不可覆盖现有代码和行为测试。

## Rollout / rollback

每阶段独立 PR，以 merge commit 合并。CI 通过后仍需用户明确授权合并。未进入下一阶段时，可回退本阶段 PR；进入下一阶段后按 3 -> 2 -> 1 反向回退。由于没有数据迁移，回退不应要求修复用户数据。

发现现存行为缺陷时单独记录，除非属于本次重构引入的回归，否则不混入本任务修复。后续阶段若需扩大用户可见行为或兼容范围，先更新规划并重新评审。
