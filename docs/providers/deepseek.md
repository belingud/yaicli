# DeepSeek

DeepSeek's AI models via OpenAI-compatible API.

## Configuration

```ini
PROVIDER=deepseek
API_KEY=sk-your-deepseek-api-key
MODEL=deepseek-chat
TEMPERATURE=0.3
MAX_TOKENS=1024
```

### Thinking Mode

DeepSeek thinking mode can be controlled with the existing `EXTRA_BODY` and `REASONING_EFFORT` settings:

```ini
PROVIDER=deepseek
API_KEY=sk-your-deepseek-api-key
MODEL=deepseek-v4-pro
REASONING_EFFORT=high
EXTRA_BODY={"thinking":{"type":"enabled"}}
```

To explicitly disable thinking mode:

```ini
EXTRA_BODY={"thinking":{"type":"disabled"}}
```

## Key Parameters

| Parameter     | Description                   | Default                       |
| ------------- | ----------------------------- | ----------------------------- |
| `API_KEY`     | DeepSeek API key (required)   | -                             |
| `MODEL`       | Model to use                  | -                             |
| `TEMPERATURE` | Randomness (0.0-1.0)          | `0.3`                         |
| `TOP_P`       | Nucleus sampling              | `1.0`                         |
| `MAX_TOKENS`  | Max response tokens           | `1024`                        |
| `TIMEOUT`     | Request timeout (seconds)     | `60`                          |
| `BASE_URL`    | Custom API endpoint           | `https://api.deepseek.com/v1` |
| `EXTRA_BODY`  | Additional request parameters | `{}`                          |
| `REASONING_EFFORT` | Thinking effort (`high` or `max` for DeepSeek thinking models) | - |

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support
- ✅ OpenAI-compatible API
- ✅ Code generation
- ✅ Mathematical reasoning

## Important Notes

- Uses OpenAI-compatible client implementation
- Supports standard OpenAI API features
- Thinking mode returns `reasoning_content`, which YAICLI displays as reasoning output
- In thinking mode, DeepSeek ignores `temperature`, `top_p`, `presence_penalty`, and `frequency_penalty`
- Live tool-call conversations preserve DeepSeek `reasoning_content` for follow-up requests; saved chat files do not yet persist full reasoning/tool metadata for exact replay after reload
- Designed for coding and reasoning tasks
- Cost-effective alternative to other providers
