# Yi (01.AI)

01.AI's Yi models via OpenAI-compatible API.

## Configuration

```ini
PROVIDER=yi
API_KEY=your-yi-api-key
MODEL=yi-large
TEMPERATURE=0.3
MAX_TOKENS=1024
```

## Key Parameters

| Parameter     | Description                   | Default                          |
| ------------- | ----------------------------- | -------------------------------- |
| `API_KEY`     | Yi API key (required)         | -                                |
| `MODEL`       | Model to use                  | -                                |
| `TEMPERATURE` | Randomness (0.0-1.0)          | `0.3`                            |
| `TOP_P`       | Nucleus sampling              | `1.0`                            |
| `MAX_TOKENS`  | Max response tokens           | `1024`                           |
| `TIMEOUT`     | Request timeout (seconds)     | `60`                             |
| `BASE_URL`    | Custom API endpoint           | `https://api.lingyiwanwu.com/v1` |
| `EXTRA_BODY`  | Additional request parameters | `{}`                             |

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support
- ✅ OpenAI-compatible API
- ✅ Multilingual support
- ✅ Long context windows

## Important Notes

- Uses OpenAI-compatible client implementation
- Developed by 01.AI (Kai-Fu Lee's company)
- Strong performance in Chinese and English
- Competitive with leading international models
- Cost-effective alternative for Asian markets