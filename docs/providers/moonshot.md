# Moonshot (月之暗面)

Moonshot's AI models via OpenAI-compatible API.

## Configuration

```ini
PROVIDER=moonshot
API_KEY=sk-your-moonshot-api-key
MODEL=moonshot-v1-8k
TEMPERATURE=0.3
MAX_TOKENS=1024
```

## Key Parameters

| Parameter     | Description                   | Default                      |
| ------------- | ----------------------------- | ---------------------------- |
| `API_KEY`     | Moonshot API key (required)   | -                            |
| `MODEL`       | Model to use                  | -                            |
| `TEMPERATURE` | Randomness (0.0-1.0)          | `0.3`                        |
| `TOP_P`       | Nucleus sampling              | `1.0`                        |
| `MAX_TOKENS`  | Max response tokens           | `1024`                       |
| `TIMEOUT`     | Request timeout (seconds)     | `60`                         |
| `BASE_URL`    | Custom API endpoint           | `https://api.moonshot.cn/v1` |
| `EXTRA_BODY`  | Additional request parameters | `{}`                         |

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support
- ✅ OpenAI-compatible API
- ✅ Chinese language optimization
- ✅ Long context windows

## Important Notes

- Uses OpenAI-compatible client implementation
- Developed by Chinese AI company 月之暗面 (Dark Side of the Moon)
- Optimized for Chinese language understanding
- Supports standard OpenAI API features
- Good performance on Chinese NLP tasks
