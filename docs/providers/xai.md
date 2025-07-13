# XAI (Grok)

X AI's Grok models via OpenAI-compatible API.

## Configuration

```ini
PROVIDER=xai
API_KEY=xai-your-api-key
MODEL=grok-2-latest
TEMPERATURE=0.3
MAX_TOKENS=1024
```

## Key Parameters

| Parameter     | Description                   | Default                  |
| ------------- | ----------------------------- | ------------------------ |
| `API_KEY`     | XAI API key (required)        | -                        |
| `MODEL`       | Model to use                  | -                        |
| `TEMPERATURE` | Randomness (0.0-1.0)          | `0.3`                    |
| `TOP_P`       | Nucleus sampling              | `1.0`                    |
| `MAX_TOKENS`  | Max response tokens           | `1024`                   |
| `TIMEOUT`     | Request timeout (seconds)     | `60`                     |
| `BASE_URL`    | Custom API endpoint           | `https://api.xai.com/v1` |
| `EXTRA_BODY`  | Additional request parameters | `{}`                     |

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support
- ✅ OpenAI-compatible API
- ✅ Real-time information access
- ✅ Multimodal capabilities

## Important Notes

- Uses OpenAI-compatible client implementation
- Built by X (formerly Twitter) AI team
- Designed for real-time information and analysis
- Supports standard OpenAI API features
- Integration with X platform data when available