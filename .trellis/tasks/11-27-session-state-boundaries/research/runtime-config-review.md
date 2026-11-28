# 第三阶段配置与状态接缝预审

2026-11-27，基于已验收的第一阶段 b7d3ce4 预审；第二阶段正在提取 application/planning，第三阶段开始前须重核实际接口。本文记录当前代码事实，不启动第三阶段产品实现。

## 已核对的隐式来源

| 位置 | 当前事实 | 第三阶段应验证的行为 |
| --- | --- | --- |
| config.Config / get_config / cfg | Config 是加载后保存值的 dict 子类；get_config 缓存默认实例 | 应用组装时复制已解析配置，隔离嵌套值；不能在子系统重读真实文件/环境 |
| LLMClient.__init__ | 保存传入 config；以同一 config 建 provider；plan_session 另行注入 | 一个实例的模型、预算、权限、provider 及计划工具使用所属依赖；保留 ready client 注入 |
| tools.schemas | ENABLED_TOOLS、计划模式与 schema 缓存仍取默认来源 | 三种声明按实际实例状态派生，A -> B -> A 交替调用不受全局 reset 掩盖 |
| tools.executor._sync_shell_guardrail_env | 永久写入四个 YAI_* 托管键，空值跳过，可能沿用上次调用值 | 完整覆盖本次有效值，在 finally 恢复；空/default、拒绝、异常及后续调用均有测试 |
| tools.limits._config_int/_config_str | 截断、预览、spill 等仍读本模块默认 cfg | 同会话的输出限制实际影响模型文本和详情记录，不能只隔离 client.config |
| redaction.is_redaction_enabled | 懒读默认 cfg | 保存聊天和 spill 使用所属配置，默认安全行为保持 |
| tools.approval._workspace_root | 懒读默认 cfg，再回退 cwd | 规则中的相对路径匹配所属 root，而非另一个会话或历史调用的 root |
| tools.workspace.plans_root | 保护计划文件时懒读默认 cfg 的 PLAN_DIR | 保护所属计划目录，保持本模块的轻量导入特征 |
| checkpoints.checkpoint_audit | 懒读 cfg 的 TOOL_AUDIT，并走现有 redaction | 检查点协调的审计和保存同样使用所属配置；不改事件/文件格式 |
| tools.session_tools.execute_session_tool | 分派到既有类 execute，再输出 todo 进度 | 显式产品路径绑定所属 PlanSession；schema 和独立 Function.execute 签名不变 |

## 锁及生命周期约束

- workspace.mutation_lock 可显式接收 root；缺省时 resolve_workspace_root 使用 YAI_WORKSPACE_ROOT/cwd。独立工具仍需要环境桥接，不能仅在 provider 请求循环中改配置。
- CheckpointStore 在准备、记录、rewind、补偿等路径显式持有自身 root 的 mutation lock。环境适配锁在其外层取得，禁止在持有 workspace lock 的路径反向取得环境锁。
- undo_last 在 mutation_lock 内实际回退；应在进入该路径之前应用所属环境，并覆盖异常恢复。检查点跨进程 writer lock 顺序和流式工作线程尚未结束时的 busy/barrier 语义保持。
- 实例隔离只承诺串行/交替应用；不增加同进程并行应用及并发 cwd 能力，不为本次重构构建通用依赖注入框架。

## 开始第三阶段时的必要证据

1. 先加入能暴露旧全局污染的 A -> B -> A 回归，断言实际声明、会话工具结果、文件字节及对方状态；独立进程不调用全局 reset。
2. 对两实例注入不同 root、权限、选择和输出限制；覆盖异常后下一次调用、空/default 值、undo 和 checkpoint。
3. 配置文件单独指定 root，cwd 为子目录，移除继承 YAI_WORKSPACE_ROOT；sync/stream 均实际回退相同文件字节。
4. 正常产品路径在禁止旧全局计划/工具模式读取时仍可运行；默认兼容入口另测，避免以替换全局对象模拟显式依赖。
5. 使用隔离启动器，保留原有测试与断言；完整三版本运行环境准备与最终执行结果由主线程记录。
