# K22 Design — 模型上下文窗口解析与预算修正

> 约束性规则见 [`.trellis/spec/py/context-window-limits.md`](../../spec/py/context-window-limits.md)。本文件描述实现边界、接口与数据流。

## 1. 模块边界

新增 **`yaicli/model_limits.py`**（stdlib-only 叶子模块，禁止 import rich/typer/SDK/cfg 单例）：

```
const.py ── config.py(cfg) ─┐
                            ├──> tokens.py (估算/裁剪/预算) ──> cli.py / cmd_handler.py
model_limits.py <───────────┘                     │
   ▲   ▲                                          ▼
   │   └── llms/provider.py (ABC + base_url + model_limits hook)
   │            ▲
   │            ├── providers/openrouter_provider.py  (httpx /models)
   │            ├── providers/gemini_provider.py      (google-genai models.get)
   │            └── providers/ollama_provider.py      (ollama show)
   │
   └── llms/client.py (预算执行 + 超窗学习)
   └── errors.py (parse_context_limit)
```

- `tokens.py` 继续作为请求路径的估值/裁剪入口，但**窗口与预算**委托 `model_limits`。
- `model_limits` 不 import `tokens`、`errors`、`config`、`console`、`llms`，避免循环；需要配置目录时函数内懒 import `const.get_config_dir()`。
- provider 钩子 import `...model_limits.ModelLimits`（追加导入，不改变现有 provider 行为）。

## 2. 数据契约

```python
@dataclass(frozen=True)
class ModelLimits:
    window: Optional[int] = None       # 总窗口（含输出）
    max_input: Optional[int] = None    # 输入硬上限（与 window 不同时，如 Gemini）
    max_output: Optional[int] = None   # 单次输出上限（仅展示/预留参考）
    source: str = "default"            # user|learned|metadata|catalog|heuristic|default
    detail: str = ""                   # 如 "openrouter /models" / "catalog 2026-11-11"
```

```python
DEFAULT_CONTEXT_WINDOW = 128_000
OLLAMA_DEFAULT_CONTEXT_WINDOW = 8_192
DEFAULT_SAFETY_TOKENS = 1_024
METADATA_TTL_SECONDS = 7 * 24 * 3600
LEARNED_TTL_SECONDS = 30 * 24 * 3600
METADATA_TIMEOUT_SECONDS = 2.0
METADATA_MISS_TTL_SECONDS = 300      # 探测失败的进程内负缓存（避免每轮重探）
```

公开函数：

```python
def normalize_model_name(model: str) -> str
def parse_user_windows(value: Any) -> dict[str, dict[str, int]]
def get_context_limits(provider: str, model: str, config: Optional[Mapping[str, Any]] = None,
                       *, base_url: str = "",
                       fetcher: Optional[Callable[[str], Optional[ModelLimits]]] = None) -> ModelLimits
def context_input_budget(limits: ModelLimits, *, max_tokens: Optional[int] = None,
                         safety_tokens: int = DEFAULT_SAFETY_TOKENS,
                         override: Optional[int] = None) -> int
def record_learned_limit(provider: str, model: str, base_url: str, window: int,
                         max_output: Optional[int] = None) -> None
def parse_context_limit(exc: BaseException) -> Optional[int]      # 实现在 errors.py，client 调用
def _default_cache_path() -> Path                                 # <config-dir>/cache/model_limits.json
def clear_limit_cache() -> None                                    # 测试用：清内存 + 磁盘
```

> `parse_context_limit` 放在 `errors.py`（错误分类已在那里），`client.py` 把结果交给 `record_learned_limit`。

## 3. 解析算法（逐层短路）

```
normalized = normalize(provider, model)
key        = f"{provider}|{base_url}|{normalized}"

1. user      : parse_user_windows(cfg["MODEL_CONTEXT_WINDOWS"])
               查找顺序: f"{provider}:{normalized}" / f"{provider}/{normalized}" / normalized
2. learned   : 内存 dict -> 磁盘 cache（TTL 30d）
3. metadata  : 内存/磁盘 cache（TTL 7d）未命中且 ENABLE_MODEL_METADATA 且 fetcher 存在
               -> fetcher(normalized)（provider.model_limits），失败/超时 -> None
4. catalog   : yaicli/data/model_limits.json
               providers[provider][normalized] -> exact["*"][normalized]（exact 大小写用归一化后的键）
5. heuristic : HEURISTIC_CONTEXT_WINDOWS（provider 作用域 + 最长前缀）
               provider == "ollama" 且没有 provider 专属条目 -> OLLAMA_DEFAULT_CONTEXT_WINDOW
6. default   : ModelLimits(window=DEFAULT_CONTEXT_WINDOW, source="default",
                           detail="assumed for unknown model")
```

- `fetcher` 只在 `get_context_limits` 内部调用；客户端传入 `lambda m: self.provider.model_limits(m)` 并包 `try/except`。
- 进程内 memo：`_MEM_LIMITS: dict[key, (ModelLimits, expires_at)]`；探测失败/返回空另入 `_METADATA_MISSES: dict[key, expires_at]`（TTL 300s，不落盘）；`clear_limit_cache()` 清空二者。
- 磁盘 cache JSON：

```json
{"version": 1,
 "entries": {"openrouter|https://openrouter.ai/api/v1|claude-sonnet-5.5":
             {"window": 1000000, "max_input": null, "max_output": 128000,
              "source": "metadata", "detail": "openrouter /models",
              "saved_at": 1762900000, "ttl": 604800}}}
```

- 磁盘读写 best-effort：`OSError`/`JSONDecodeError` 静默；写前 `mkdir(parents=True, exist_ok=True)`，`chmod 0600`（best-effort）。
- `ENABLE_MODEL_LIMITS_CACHE=false`：不读不写磁盘（内存 memo 仍可用）。

## 4. 归一化与启发式

`normalize_model_name`：

1. `strip().lower()`
2. 去 yaicli/OpenRouter 供应商前缀：`openrouter/`、`anthropic/`、`openai/`、`google/`、`mistralai/`、`meta-llama/`、`qwen/`、`deepseek/`、`moonshotai/`、`x-ai/`、`cohere/`、`nvidia/`（逐层，最多 2 次）
3. 去日期后缀：`[-@]\d{8}$`（如 `-20250929`、`@20250929`）
4. 去 OpenRouter 变体后缀：`:(free|batch|extended|nitro|online)$`
5. `[1m]` 标记：先记录 `_is_1m_variant`，从名字中去掉 `[1m]`；命中 1M 变体时启发式直接给 `1_000_000`（source=`heuristic`, detail=`1m variant`）

`HEURISTIC_CONTEXT_WINDOWS`（provider 作用域，`""` = 任意 provider；按 pattern 长度倒序匹配，最长前缀优先）：

| pattern | window | 说明 |
|---|---|---|
| `gpt-4.1` | 1,047,576 | |
| `gpt-4-32k` | 32,768 | 必须优先于 `gpt-4` |
| `gpt-4o` | 128,000 | |
| `gpt-4-turbo` | 128,000 | |
| `gpt-4` | 8,192 | |
| `gpt-5` | 400,000 | |
| `gpt-3.5` | 16,385 | |
| `o1-mini` | 128,000 | 必须优先于 `o1` |
| `o1` / `o3` / `o4` | 200,000 | |
| `claude` | 200,000 | |
| `gemini` | 1,048,576 | |
| `deepseek` | 128,000 | |
| `moonshot` / `kimi` | 131,072 | |
| `qwen` | 131,072 | |
| `glm` / `chatglm` | 128,000 | |
| `grok` | 131,072 | |
| `mistral` | 128,000 | |
| `mixtral` | 32,768 | |
| `command` | 128,000 | |
| `cohere` | 128,000 | |
| `minimax` | 245,760 | |
| `("ollama", "llama")` | 8,192 | provider 专属示例；其余未命中走 Ollama 默认 |

## 5. 预算公式

`tokens.resolve_context_budget(config=None, model=None, provider=None)`：

```python
provider = provider or config.get("PROVIDER", "")
limits = get_context_limits(provider, model, config)
budget = context_input_budget(
    limits,
    max_tokens=config.get("MAX_TOKENS"),
    safety_tokens=int(config.get("CONTEXT_SAFETY_TOKENS") or 0),
    override=int(config.get("CONTEXT_BUDGET_TOKENS") or 0),
)
```

`context_input_budget`：

```python
if override and override > 0: return int(override)
caps = [x for x in (limits.window, limits.max_input) if x]
cap = min(caps) if caps else DEFAULT_CONTEXT_WINDOW
reserve = max(0, int(max_tokens or 0)) + max(0, int(safety_tokens or 0))
return max(1, cap - reserve)
```

兼容：`get_context_window(model=None, provider=None)` 保留，返回 `get_context_limits(provider or "", model or "", None).window or DEFAULT_CONTEXT_WINDOW`；`DEFAULT_CONTEXT_WINDOW`/`OLLAMA_DEFAULT_CONTEXT_WINDOW` 从 `model_limits` 再导出让旧导入不破。

## 6. provider 元数据钩子

`Provider`（`llms/provider.py`）：

```python
@property
def base_url(self) -> str:
    return str(self.config.get("BASE_URL") or getattr(self, "DEFAULT_BASE_URL", "") or "")

def model_limits(self, model: str) -> Optional[ModelLimits]:
    """Return provider-advertised limits, or None. Base: no metadata source."""
    return None
```

三个实现（都 `try/except Exception: return None`）：

| provider | 调用 | 字段 | detail |
|---|---|---|---|
| OpenRouter | `httpx.get(f"{base_url}/models", headers=Authorization, timeout=2.0)` | `data[].context_length`、`data[].top_provider.max_completion_tokens`；按归一化 id 匹配 | `openrouter /models` |
| Gemini | `self.client.models.get(model=f"models/{model}")`（失败再试 `model=model`） | `input_token_limit`、`output_token_limit` | `gemini models.get` |
| Ollama | `self.client.show(model)` | `model_info` 中 `*.context_length`（取最大正值） | `ollama /api/show` |

约束：不允许在钩子里读 `NUM_CTX`/`num_ctx`；不允许缓存到 provider 自身（缓存统一在 `model_limits`）；不允许打印输出。

## 7. 客户端集成（`llms/client.py`）

- `__slots__` 增加 `provider_key`、`_limits_warned`、`last_context_limits`；`__init__` 记录归一化后的 provider 名。
- `_resolve_limits_and_budget()`：
  - `fetcher = lambda m: self.provider.model_limits(m)`
  - `limits = get_context_limits(self.provider_key, model, self.config, base_url=self.provider.base_url, fetcher=fetcher)`
  - `budget = context_input_budget(limits, max_tokens=..., safety_tokens=..., override=...)`
  - 未知时 `_warn_unknown_model_limits(limits)`（`get_error_console()`，每 client 一次，空模型不警告）
- `_enforce_context_budget` 使用上面的 limits/budget；保存 `last_context_limits`。
- `_heal_context_length`：`limit = parse_context_limit(exc)`；若 `limit and limit > 0`：
  `record_learned_limit(...)` → 重算 budget →（必要时再裁）→ 重试一次；stderr 消息按 PRD 样例。
  学习发生在裁剪前，所以即使没有可裁组也保留学习值。

## 8. `/context` 集成（`cmd_handler.py`）

```python
def _context_usage(self):
    cli = self.cli
    history = self._history()
    role_prompt = self._role_prompt()
    project = cli._get_project_context() if hasattr(cli, "_get_project_context") else ""
    extra = cli.context_manager.get_context_messages() if getattr(cli, "context_manager", None) else []
    config = cfg if hasattr(cfg, "get") else None
    return estimate_context_usage(
        history, config=config, system_text=role_prompt, model=...,
        provider=..., extra_system_text=project, extra_messages=extra,
    )
```

`estimate_context_usage` 新增参数与 `ContextUsage` 字段：

```python
extra_system_text: Optional[str] = None
extra_messages: Optional[Sequence[Any]] = None
# ContextUsage += window_tokens, max_output_tokens, source, detail,
#                 project_tokens（extra_system_text）, extra_tokens（extra_messages）,
#                 reserve_tokens, overhead_tokens（实际计入 total 的 REQUEST_OVERHEAD_TOKENS 值）
```

`total = system_tokens + project_tokens + extra_tokens + history_tokens + overhead_tokens`（有 history/project/extra 时
`overhead_tokens = 3`，否则 `0`；`/context` 单独渲染 `overhead` 行，避免 bucket 之和与 total 对不上）。
`used_percent = total / budget * 100`，`remaining = max(0, budget - total)`。
`reserve_tokens = MAX_TOKENS + CONTEXT_SAFETY_TOKENS`。

## 9. 配置键

| key | type | default | env | template |
|---|---|---|---|---|
| `MODEL_CONTEXT_WINDOWS` | dict | `{}` | `YAI_MODEL_CONTEXT_WINDOWS` | `MODEL_CONTEXT_WINDOWS={}` |
| `ENABLE_MODEL_METADATA` | bool | true | `YAI_ENABLE_MODEL_METADATA` | `ENABLE_MODEL_METADATA=true` |
| `CONTEXT_SAFETY_TOKENS` | int | 1024 | `YAI_CONTEXT_SAFETY_TOKENS` | `CONTEXT_SAFETY_TOKENS=1024` |
| `ENABLE_MODEL_LIMITS_CACHE` | bool | true | `YAI_ENABLE_MODEL_LIMITS_CACHE` | `ENABLE_MODEL_LIMITS_CACHE=true` |

`CONTEXT_BUDGET_TOKENS` 保留（默认 0 = 新公式；>0 逐字覆盖）；`CONTEXT_BUDGET_RATIO` 不再使用（从 tokens.py 删除）。

## 10. 目录数据与生成脚本

`yaicli/data/model_limits.json`：

```json
{"version": 1, "generated_at": "2026-11-11",
 "sources": {"openrouter": "https://openrouter.ai/api/v1/models",
             "catalog": "https://models.dev/api.json",
             "litellm": "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"},
 "exact": {"*": {"gpt-4o": {"window": 128000, "max_output": 16384}}},
 "providers": {"deepseek": {"deepseek-chat": {"window": 128000}}}}
```

`scripts/gen_model_limits.py`：`--openrouter <json> --modelsdev <json> --litellm <json> --out <path>`，允许缺省输入（只用已有的 curated base 合并）；不做网络请求；输出稳定排序 + `generated_at` 用 `--date` 可注入（测试/可复现）。

## 11. 兼容性与回滚

- 旧导入面保持：`tokens.DEFAULT_CONTEXT_WINDOW`、`tokens.OLLAMA_DEFAULT_CONTEXT_WINDOW`、`tokens.get_context_window`、`tokens.resolve_context_budget`。
- 行为变化（预算变大、`/context` 行变化）写入 PRD/changelog；`CONTEXT_BUDGET_TOKENS` 为用户提供回退。
- 回滚：删除 `model_limits.py` 与新配置键、恢复 `tokens.py` 旧公式即可（无数据迁移）。
- 缓存是纯 cache：删除文件无副作用。

## 12. 测试策略

- `tests/test_model_limits.py`：归一化、最长前缀、六层优先级、缓存 TTL/开关、预算公式、目录加载、损坏缓存、注入 fetcher。
- 所有外部边界 mock：`httpx.get`（OpenRouter）、`provider.client.models.get`（Gemini）、`provider.client.show`（Ollama）、`Path` 缓存路径用 `tmp_path` + 显式参数/`patch`。
- 不联网、不写真实 config 目录；`clear_limit_cache()` + `YAI_*` 环境隔离。
