# Doubao (ByteDance)

ByteDance's Doubao models via VolcEngine ARK runtime.

## Configuration

```ini
PROVIDER=doubao
API_KEY=your-doubao-api-key
MODEL=doubao-pro-32k
TEMPERATURE=0.7
MAX_TOKENS=4096
```

## Alternative Authentication

```ini
PROVIDER=doubao
AK=your-access-key
SK=your-secret-key
REGION=cn-beijing
MODEL=doubao-pro-32k
TEMPERATURE=0.7
MAX_TOKENS=4096
```

## Key Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `API_KEY` | Doubao API key | - |
| `AK` | Access key (alternative auth) | - |
| `SK` | Secret key (alternative auth) | - |
| `REGION` | Service region | - |
| `MODEL` | Model to use | - |
| `TEMPERATURE` | Randomness (0.0-1.0) | `0.7` |
| `TOP_P` | Nucleus sampling | `1.0` |
| `MAX_TOKENS` | Max response tokens | `4096` |
| `TIMEOUT` | Request timeout (seconds) | `60` |
| `BASE_URL` | Custom API endpoint | `https://ark.cn-beijing.volces.com/api/v3` |
| `EXTRA_BODY` | Additional request parameters | `{}` |

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support
- ✅ OpenAI-compatible API
- ✅ Chinese language optimization
- ✅ Multiple authentication methods

## Important Notes

- Uses VolcEngine ARK runtime
- Based on OpenAI-compatible implementation
- Supports both API key and AK/SK authentication
- Optimized for Chinese language tasks
- Regional service deployment options