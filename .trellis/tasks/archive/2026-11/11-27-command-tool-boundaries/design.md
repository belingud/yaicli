# 第一阶段技术设计

## Source contracts

需求见 prd.md；总体约束与回退规则见 ../11-27-core-organization-refactor/design.md。实现前读取上下文清单中的工具、provider、CLI 和检查点规范，并以现有源码/行为测试核对历史差异。

## Command definition

在 commands/registry.py 扩展现有 CommandInfo；定义保留 command、description、usage、aliases，并关联 handler 名称及是否接收尾部输入。由同一集合生成帮助、补全和绑定当前 handler 的分发表。使用普通 dataclass/函数，不设计自动发现插件。

处理步骤：精确 token 查找 -> 按该定义的参数策略判断 -> handler 接收原始输入。只规范化命令 token，不对标题/路径/提示词整体小写。无参数命令后附文本、空白和未知命令按基线处理，不以统一解析器改变旧语义。

CmdHandler 暂留各命令业务逻辑，COMMAND_INFO/command_completions 保留兼容导出；第二阶段再迁移命令业务依赖。registry 不能导入 CLI、实例化服务或触发 provider SDK 导入。

## Tool modules

| 模块 | 职责 |
| --- | --- |
| tools/schemas.py | 工具选择模式、声明聚合、计划模式适配、缓存及失效；复用现有 function/mcp 转换 |
| tools/policy.py | 权限和风险的评估结果，区分允许、拒绝、需要交互确认，携带来源、原因和风险信息 |
| tools/executor.py | 参数修复、工具查找/分派、环境桥接、workspace guard、执行、mutation capture、统一结果通道 |
| tools/display.py | 公告、参数预览、结果面板及查看最后输出的展示适配；复用 limits/output_history |
| tools/__init__.py | 现有公共入口及按需委托，避免业务逻辑和可变缓存重复 |

仅提取现有职责；展示与截断边界保持：模型可见截断/输出历史归执行结果通道，Rich 展示不决定模型文本。缓存和模式状态只有一份权威存储，阶段一仍用当前默认模式，由兼容函数代理访问。

## Call flow and side effects

1. LLMClient 解析完整 tool call，执行既有 ToolPolicy/ENABLED_TOOLS 筛选。
2. policy 评估现有 readonly/trusted/standard、风险、模式、授权规则及可否确认，返回内部决策，不执行工具。
3. 客户端按原 generator 协议 yield ConfirmToolCall 并接收 send(decision)，处理 SESSION/PERSIST，记录相同审计。
4. executor 修复参数、查找对应 builtin/user/MCP/会话工具；保持现有计划工具优先分派及错误返回。
5. 文件变更在原 workspace lock 内执行 prepare -> capture.prepare -> execute -> capture.record/undo；失败和未知副作用仍设置 barrier。
6. 一次输出截断后记录详情并交给 display 展示，向客户端返回原有 tuple[str, bool]；客户端追加配对消息并请求下一轮。

需要保留的调用时序以当前测试为准；本阶段不把 audit、confirm、workspace capture 改造成通用中间件链。权限结果对象仅承载现有决策所需字段。

## Compatibility

- execute_tool_call(tool_call, announce=True) 的入口、参数修复、前缀处理、返回错误及 ok 含义不变。
- builtins 的 Function(OpenAISchema)/execute、同名覆盖、manifest 警告、损坏文件跳过不变。
- 函数加载器与 schema cache 不得因重新导出形成两份状态；Gemini 的签名和计划模式缓存与其他 provider 同步。
- Gemini 当前 callable builder 不应用 ENABLED_TOOLS、provider 直接聚合 MCP 的差异按原行为冻结；“等价”指各自迁移前后等价，不指本阶段让各 provider 行为一致。证据和最小补测见父任务 research/test-safety-review.md。
- 公共 API 和受支持的注入点保留。内部 patch 随模块迁移时应修改实际绑定目标，不为测试构造另一套生产逻辑。
- 无计划/检查点活动的启动路径继续懒加载；禁止子模块反向导入 CLI/entry。

## Validation and rollback

先建立命令/工具行为基线，再依次提取命令定义、schemas、policy、executor/display；每一步运行对应行为测试及相邻链路测试。第一阶段独立 PR；若后续阶段尚未合并，回退该 PR 即回到旧组织，无数据迁移。具体命令见 implement.md。
