# SambaNova

SambaNova's AI platform for high-performance inference.

## Configuration

```ini
PROVIDER=sambanova
API_KEY=your-sambanova-api-key
MODEL=Meta-Llama-3.1-405B-Instruct
TEMPERATURE=0.3
MAX_TOKENS=1024
```

## Key Parameters

| Parameter     | Description                   | Default                       |
| ------------- | ----------------------------- | ----------------------------- |
| `API_KEY`     | SambaNova API key (required)  | -                             |
| `MODEL`       | Model to use                  | -                             |
| `TEMPERATURE` | Randomness (0.0-1.0)          | `0.3`                         |
| `TOP_P`       | Nucleus sampling              | `1.0`                         |
| `MAX_TOKENS`  | Max response tokens           | `1024`                        |
| `TIMEOUT`     | Request timeout (seconds)     | `60`                          |
| `BASE_URL`    | Custom API endpoint           | `https://api.sambanova.ai/v1` |
| `EXTRA_BODY`  | Additional request parameters | `{}`                          |

## Function Call Support

Only specific models support function calling:

- `Meta-Llama-3.1-8B-Instruct`
- `Meta-Llama-3.1-405B-Instruct`
- `Meta-Llama-3.3-70B-Instruct`
- `Llama-4-Scout-17B-16E-Instruct`
- `DeepSeek-V3-0324`

## Features

- ✅ Streaming responses
- ✅ Function calling (select models)
- ✅ MCP support
- ✅ OpenAI-compatible API
- ✅ High-performance inference
- ✅ Large model support

## Important Notes

- Uses OpenAI-compatible client implementation
- Temperature automatically clamped to 0.0-1.0 range
- Function calling only supported on specific models
- Warning displayed if function calling used with unsupported model
- Optimized for large-scale model inference