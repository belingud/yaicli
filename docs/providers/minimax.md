# Minimax

Minimax is a Chinese AI company providing language models with an OpenAI-compatible API.

## Configuration

```ini
PROVIDER=minimax
API_KEY=your-minimax-api-key
MODEL=MiniMax-M2.1
TEMPERATURE=0.3
TOP_P=1.0
MAX_TOKENS=1024
```

## Key Parameters

| Parameter     | Description                   | Default                      |
| ------------- | ----------------------------- | ---------------------------- |
| `API_KEY`     | Minimax API key (required)    | -                            |
| `MODEL`       | Model to use                  | -                            |
| `TEMPERATURE` | Randomness (0.0-1.0)          | `0.3`                        |
| `TOP_P`       | Nucleus sampling              | `1.0`                        |
| `MAX_TOKENS`  | Max response tokens           | `1024`                       |
| `TIMEOUT`     | Request timeout (seconds)     | `60`                         |
| `BASE_URL`    | Custom API endpoint           | `https://api.minimaxi.com/v1` |
| `EXTRA_BODY`  | Additional request parameters | -                            |

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support
- ✅ OpenAI-compatible API
- ✅ Chinese language optimization
- ✅ Multi-modal capabilities
- ✅ **Interleaved Thinking (reasoning)**

## Interleaved Thinking

MiniMax-M2.1 and newer models support **Interleaved Thinking** (交错思维链), which allows the model to reason before each tool use and make decisions based on tool results.

### How It Works

When `reasoning_split=True` is enabled (default), the API returns reasoning content separately from the main response:

```json
{
    "message": {
        "content": "The weather in Beijing is sunny...",
        "role": "assistant",
        "reasoning_details": [
            {
                "type": "reasoning.text",
                "text": "I need to check the weather for Beijing..."
            }
        ]
    }
}
```

### Configuration

Interleaved Thinking is **enabled by default** for MiniMax provider. You can control it via:

**Environment Variable:**
```bash
export YAI_MINIMAX_REASONING_SPLIT=true
```

**Config File:**
```ini
[core]
MINIMAX_REASONING_SPLIT=true
```

**EXTRA_BODY (advanced):**
```ini
EXTRA_BODY={"reasoning_split": true}
```

> **Note:** When `reasoning_split` is explicitly set in `EXTRA_BODY`, it takes precedence over `MINIMAX_REASONING_SPLIT`.

### Important Notes

- Reasoning content is **preserved in conversation history** and sent back to the model in subsequent requests
- This ensures the model maintains continuity in its thinking process across multiple tool calls
- Reasoning content is displayed alongside the main response when `SHOW_REASONING=true`

## Important Notes

- Uses OpenAI-compatible client implementation
- Strong performance on Chinese language tasks
- Supports image understanding in compatible models
- Requires registration on the Minimax platform
- API documentation primarily available in Chinese
- Pay-as-you-go billing based on token usage

## Resources

- [Official Website](https://platform.minimaxi.com/)
- [Developer Documentation](https://platform.minimaxi.com/document/platform)
- [Model Catalog](https://platform.minimaxi.com/document/guides/models)
