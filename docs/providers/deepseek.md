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
- Designed for coding and reasoning tasks
- Cost-effective alternative to other providers