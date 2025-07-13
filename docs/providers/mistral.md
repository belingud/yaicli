# Mistral

Mistral AI's foundation models for general-purpose and specialized tasks.

## Configuration

```ini
PROVIDER=mistral
API_KEY=your-mistral-api-key
MODEL=mistral-large-latest
TEMPERATURE=0.7
MAX_TOKENS=4096
```

## Key Parameters

| Parameter       | Description                | Default                     |
| --------------- | -------------------------- | --------------------------- |
| `API_KEY`       | Mistral API key (required) | -                           |
| `MODEL`         | Model to use               | -                           |
| `TEMPERATURE`   | Randomness (0.0-1.0)       | `0.7`                       |
| `TOP_P`         | Nucleus sampling           | `1.0`                       |
| `MAX_TOKENS`    | Max response tokens        | `4096`                      |
| `TIMEOUT`       | Request timeout (seconds)  | `60`                        |
| `BASE_URL`      | Custom API endpoint        | `https://api.mistral.ai/v1` |
| `SERVER`        | Server configuration       | -                           |
| `EXTRA_HEADERS` | Additional HTTP headers    | `{}`                        |

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support
- ✅ Parallel tool calls (disabled by default)
- ✅ Document processing
- ✅ Image analysis

## Important Notes

- Timeout is specified in seconds but converted to milliseconds internally
- Parallel tool calls are disabled for better compatibility
- Supports document and image content types
- Reference handling for RAG applications
- Custom server configurations supported