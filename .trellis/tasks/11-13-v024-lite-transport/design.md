# Design — v0.24.0 lite transport

## 1. 问题定位

`LLMClient` → `ProviderFactory` → `OpenAIProvider.__init__` → `openai.OpenAI(...)`。构造 SDK client 触发 `import openai`（812ms）。`OpenAIProvider.completion()` 只用到 SDK 两件事：

1. `self.client.chat.completions.create(**params)`（非流式返回 `ChatCompletion`，流式返回 `Stream[ChatCompletionChunk]`）；
2. 对返回值做鸭子式属性读取（`choices`、`message.content`、`delta.tool_calls`、`usage` 等）。

因此可以引入一个同接口的 httpx 后端（`LiteChatClient`），把 SDK 留给：其它 provider 家族、Azure、自定义 `CLIENT_CLS` 子类，以及 `LITE_TRANSPORT=false` 回退。

## 2. 模块结构

```
yaicli/llms/
├── openai_wire.py          # NEW: 共享 wire 逻辑（无 SDK import）
├── lite_transport.py       # NEW: httpx 直连 + SSE 解析 + LiteAPIError + 鸭子对象
├── providers/
│   ├── openai_provider.py  # 变薄：OpenAIProvider(OpenAIWireProvider) + 懒 import openai + create_client()
│   └── openai_compatible_provider.py  # SDK 类型 import 移到 TYPE_CHECKING
```

依赖方向（无环）：

```
providers/openai_provider.py ──> openai_wire.py ──> provider.py (ABC), schemas, errors, usage, tools
providers/openai_provider.py ──> lite_transport.py ──> httpx
providers/openai_compatible_provider.py ──> openai_provider.py
```

`openai_wire.py` / `lite_transport.py` 导入期只允许 stdlib + httpx + yaicli 叶子模块，**禁止** `import openai`（PRD R10，用子进程断言测试）。

## 3. `openai_wire.py`

把现 `OpenAIProvider` 的类体（除 `__init__` 里的 client 构造）平移到 `OpenAIWireProvider(Provider)`，逐行保留：

- `DEFAULT_BASE_URL` / `COMPLETION_PARAMS_KEYS`
- `__init__`：`self.client = self.create_client()`（抽象钩子）
- `get_client_params()` / `get_completion_params()` / `get_tools()`
- `completion()`：参数组装、verbose dump、`_create_completion`、异常包装
- `_is_stream_options_rejection()` / `_create_completion()`（不变，鸭子读 `status_code` 与 message）
- `_handle_normal_response()` / `_handle_stream_response()` / `_first_chunk_error()`
- `_accumulate_tool_call_chunks()` / `_finalize_tool_calls()` / `_process_tool_call_chunk()`（legacy）
- `_get_reasoning_content()` / `detect_tool_role()`

两处必要改动（不改变行为）：

1. **异常处理合并为鸭子式**：现在 `except (openai.APIStatusError, openai.APIResponseValidationError)` 打印 `Error Response: {body}` 并以 `detail=body` 分类；其它异常无 body。抽成：

   ```python
   except Exception as e:
       body = self._response_error_body(e)   # status_code 存在时尝试 e.response.json()/text
       if body is not None:
           print_untrusted(self.console, f"Error Response: {body}")
           raise wrap_provider_exception(e, label, detail=str(body)) from e
       raise wrap_provider_exception(e, label) from e
   ```

   `_response_error_body` 对 SDK 异常（`status_code` + `response`）与 `LiteAPIError` 返回相同结果；对 `httpx.ConnectError` 等无 status 的异常返回 `None` → 与原 `except Exception` 分支一致。

2. **类型注解**：去掉对 `Stream[ChatCompletionChunk]` / `ChatCompletion` 的运行时依赖，handler 参数用 `Any`/`Iterable[Any]`；`if not chunk.choices` 等主体代码不变。

## 4. `lite_transport.py`

### 4.1 公开接口

```python
class LiteChatClient:
    def __init__(self, client_params: dict, *, http_client: httpx.Client | None = None) -> None
    chat: LiteChatNamespace          # .completions.create(**params)

def create_lite_client(client_params: dict, **kwargs) -> LiteChatClient

class LiteAPIError(ProviderError):
    status_code: int
    response: httpx.Response         # .text/.json()/.headers 供 errors.py 鸭子读取
    body: object                     # 解析后的 error payload（无则原文）
```

`create(**params)` 与 SDK 的 `chat.completions.create(**params)` 同签名语义：

- `stream=False` → `LiteCompletion`（`.choices` / `.usage` / `.to_dict()` / `.base_resp=None`）
- `stream=True` → `Iterator[LiteChunk]`（惰性读取 SSE，迭代结束关闭响应）
- `params` 中 `timeout` 作为请求超时（不进入 body）；`extra_body` 深合并进 body；`stream_options` 原样发送（由 provider 的 `_create_completion` 控制）
- 其余键原样 JSON 序列化。

### 4.2 HTTP 细节

| 项 | 实现 |
| --- | --- |
| URL | `base_url.rstrip("/") + "/chat/completions"`（`base_url` 缺失时用 provider `DEFAULT_BASE_URL`，由 `get_client_params` 保证） |
| Headers | `default_headers`（X-Title/HTTP_Referer/EXTRA_HEADERS）+ `Authorization: Bearer` + `Content-Type: application/json` + `Accept: application/json` / `text/event-stream` + `User-Agent: yaicli/<version> (lite)` |
| Query | client_params 的 `default_query`（当前 OpenAI/Azure 之外不用；实现并测试透传） |
| Proxy / TLS | `httpx.Client(trust_env=True)`：继承 `HTTP(S)_PROXY`/`NO_PROXY`，与 SDK 内部 httpx 传输一致；socks 由已有 `socksio` 依赖支持 |
| Timeout | client 默认 `httpx.Timeout(TIMEOUT or 60)`；请求级 `timeout` 覆盖（与 SDK 的 per-request timeout 对齐） |
| 错误响应 | `response.read()` 后构造 `LiteAPIError(response)`，`status_code`/`text`/`json()` 与 SDK `APIStatusError` 暴露面一致 |
| 流式 | `client.send(request, stream=True)` → `iter_lines()`；SSE 逐事件解析，`[DONE]` 结束，`finally` 关闭响应 |

### 4.3 响应鸭子对象

用 3 个小类 + `model_extra` dict 复刻 handler 读取的字段（不追求完整 SDK 模型）：

- `LiteCompletion`: `choices: List[LiteChoice]`、`usage: Optional[dict]`、`to_dict()`、`base_resp = None`
- `LiteChoice`: `message: LiteMessage`、`finish_reason: Optional[str]`
- `LiteMessage`: `content: str`、`reasoning_content: str`、`tool_calls: List[LiteToolCall]`、`model_extra: dict`
- 流式：`LiteChunk`: `choices: List[LiteStreamChoice]`、`usage: Optional[dict]`、`model_extra: dict`（未知顶层键，含 `error`，供 `_first_chunk_error` 识别）；`LiteStreamChoice`: `delta: LiteDelta`、`finish_reason`；`LiteDelta`: `content`、`tool_calls`、`model_extra`（未知 delta 键，含 `reasoning_content`/`reasoning`，供 `_get_reasoning_content` 识别）
- `LiteToolCall` / `LiteFunction`: `id`、`index`、`function.name`、`function.arguments`
- `usage` 保持原始 dict：`yaicli.usage._get` 支持 `Mapping`，`usage_from_openai` 直接可用。

## 5. 传输选择（`openai_provider.py`）

```python
LITE_TRANSPORT_PROVIDER_CLASSES = frozenset({"OpenAIProvider", "OpenAICompatibleProvider"})

class OpenAIProvider(OpenAIWireProvider):
    CLIENT_CLS = None  # marker; resolved lazily to openai.OpenAI unless a subclass sets one

    def create_client(self):
        if type(self).__name__ in LITE_TRANSPORT_PROVIDER_CLASSES and bool(self.config.get("LITE_TRANSPORT", True)):
            self._log_transport("lite (httpx)")
            from ..lite_transport import create_lite_client
            return create_lite_client(self.client_params)
        self._log_transport("openai SDK")
        import openai
        client_cls = self.CLIENT_CLS or openai.OpenAI
        return client_cls(**self.client_params)

class OpenAIAzure(OpenAIProvider):
    CLIENT_CLS = None
    def create_client(self):   # always SDK
        import openai
        return (self.CLIENT_CLS or openai.AzureOpenAI)(**self.client_params)
```

- 精确类名匹配：`DeepSeekProvider`/`OpenRouterProvider`/...（含用户自定义子类）自动留在 SDK；`CerebrasProvider` 等自定义 `CLIENT_CLS` 也留在 SDK。
- `openai_compatible_provider.py` 继续只覆盖 `_handle_stream_response`（complete-JSON 检测），并把 `Stream`/`ChatCompletionChunk` 类型 import 移入 `TYPE_CHECKING` + `from __future__ import annotations`，从而 lite 路径不 import openai。
- 配置读取用 `bool(self.config.get("LITE_TRANSPORT", True))`：config 层已用 `str2bool` 归一化（env/ini），缺失键（测试 mock config）默认 True。

## 6. 配置键

- `yaicli/const.py`：`DEFAULT_LITE_TRANSPORT: BOOL_STR = "true"` + `DEFAULT_CONFIG_MAP["LITE_TRANSPORT"] = {"value": ..., "env_key": "YAI_LITE_TRANSPORT", "type": bool}` + `DEFAULT_CONFIG_INI` 增加 `LITE_TRANSPORT={...}`（放在 API/请求参数区）。
- `docs/usage/configuration.md`：参考表 + INI 片段 + 一节短文 "Transport (lite / SDK)" 说明默认、回退、适用范围与排障。
- `README.md`：参考表。
- `docs/advanced/upgrade.md`：v0.24 行为变化 + 回退方法。
- provider 文档（`docs/providers/openai.md`、`openai-compatible.md` 若存在）加一句传输层说明。

## 7. 测试设计

### 7.1 `tests/llms/test_lite_transport.py`（传输层）

用 `httpx.MockTransport(handler)` 注入 `LiteChatClient(..., http_client=httpx.Client(transport=...))`，无网络、无 sleep：

1. 请求：URL/方法/headers（auth、默认头、content-type、accept、UA）/body（params、messages、tools、`extra_body` 合并、无 `timeout`）/query 透传。
2. 非流式：content/reasoning/`tool_calls`/usage（含 cached/reasoning tokens）解析；`to_dict()`。
3. 流式：文本 delta、`reasoning_content`、`reasoning`、多事件、注释/空行/`event:` 行、`[DONE]`、并行碎片 tool_calls、无 `index` 回退、usage-only chunk、末 chunk usage。
4. 错误：400（带 JSON body）/401/429/500 → `LiteAPIError` 的 `status_code`/`text`/`json()`，`classify_exception` 的 kind/retryable；`stream_options` 400 重试（server 第一次断言有参数、第二次断言无参数）；`httpx.ConnectError`/`ReadTimeout` 分类。
5. 生命周期：流式生成器被提前关闭/耗尽后响应关闭。

### 7.2 `tests/llms/test_lite_parity.py`（parity）

把同一份 wire JSON/SSE 分别：

- SDK 解析：`ChatCompletion.model_validate(payload)` / `ChatCompletionChunk.model_validate(chunk)`（openai 是 dev 环境既有依赖，仅在测试中使用）；
- lite 解析：`MockTransport` 返回同一份 payload → `LiteChatClient`。

再分别喂给同一个 `OpenAIProvider`（`_handle_normal_response` / `_handle_stream_response`）或经完整 `completion()`，断言 `[(content, reasoning, finish_reason, tool_calls, usage)]` 序列相等。至少覆盖：

1. 纯文本非流式/流式；
2. 并行碎片 tool_calls + finish_reason=tool_calls；
3. reasoning_content + usage；
4. 无 finish_reason 的 complete-JSON proxy 流（`OpenAICompatibleProvider`）；
5. HTTP 200 in-band error payload（两边都抛 `AgentError`，kind 相同）。

### 7.3 既有测试更新

- `tests/llms/test_simple_providers.py` 等 `patch("yaicli.llms.providers.openai_provider.openai.OpenAI")` → `patch("openai.OpenAI")`（模块不再在导入期绑定 `openai`）。SDK 路径测试同时显式设置 `LITE_TRANSPORT=False`（或使用非 lite 子类），避免默认值变化影响 mock 断言。
- `tests/llms/test_openai_provider.py`：`OpenAIProvider` 默认现在走 lite → 需要 `mock_config["LITE_TRANSPORT"] = False` 或 patch `create_client`；补充 lite 走通的用例。
- `tests/test_errors.py` 的 39-provider 矩阵：`hasattr(CLIENT_CLS)` 仍成立（`CLIENT_CLS=None`），patch 后 SDK 路径；无影响，跑一遍确认。

## 8. 性能与 gate

- 基线：同树 SDK 回退路径 `oneshot_local` P50 1623.2ms（`-n 5`；v0.23 master 首次测量 1759.7ms）。实现后 `-n 5` 实测 **584.3ms**（-64%），写进 PRD 的「实测结果」。
- `GATE_LIMITS["oneshot_local"]` 旧值 2200 → **1000ms**（roadmap 的「沙箱 ≤1.0s」验收；本机 584ms、CI 预期 250–350ms，余量 ≥1.6x）；`scripts/bench.py` 注释解释新 gate 依据。
- `version`/`help`/`template`/`entry_import`/`repl_ready` gate 不动，用 `--gate` 验证。

## 9. 备选方案（未采用）

| 方案 | 不采用原因 |
| --- | --- |
| 新 `openai_lite_provider.py` 复制一份 provider | 552 行逻辑重复，后续维护必漂移；抽 `openai_wire.py` 零逻辑改动 |
| 只给 `openai-compatible` 加 lite，`openai` 保持 SDK | 默认 provider（README 首推）无法受益，验收 ③ 无意义 |
| lite 扩展到全部 OpenAI-family | 一次改动面过大，provider 特例（chatglm 等自定义 handler）风险高；本版先灰度两类，后续按需扩展 |
| 用 stdlib `urllib`/`http.client` 省掉 httpx | 需要自写 SSE/代理/TLS/超时；httpx 已是基础依赖且边际成本 ~45ms，不值得 |
| 保留 SDK 内部 retry（关闭 lite 自带的） | SDK retry 是 import 后行为；`LLMClient` 的请求级 retry 已覆盖用户可见语义，lite 不复制 SDK 内部重试 |

## 10. 验证顺序

1. `pytest tests/llms/test_lite_transport.py tests/llms/test_lite_parity.py tests/llms/test_openai_provider.py -q`
2. 全量 `pytest`
3. `ruff check --no-fix yaicli tests`
4. `mkdocs build --strict`
5. `python scripts/bench.py -n 5 --gate`
6. 手工：默认/回退/401 错误输出，与 PRD Feature examples 对照
