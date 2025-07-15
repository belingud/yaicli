# Bailian (Qwen)

Bailian is Alibaba Cloud's intelligent language model service that provides Qwen series models through an OpenAI-compatible interface.

## Configuration

```ini
PROVIDER=bailian
API_KEY=your-aliyun-api-key
MODEL=qwen-plus
TEMPERATURE=0.3
MAX_TOKENS=2048
```

## International Version

```ini
PROVIDER=bailian-intl
API_KEY=your-aliyun-api-key
MODEL=qwen-plus
TEMPERATURE=0.3
MAX_TOKENS=2048
```

## Key Parameters

| Parameter     | Description                      | Default   |
| ------------- | -------------------------------- | --------- |
| `API_KEY`     | Alibaba Cloud API key (required) | -         |
| `MODEL`       | Model to use                     | -         |
| `TEMPERATURE` | Randomness (0.0-1.0)             | `0.3`     |
| `TOP_P`       | Nucleus sampling                 | `1`       |
| `MAX_TOKENS`  | Max response tokens              | `1024`    |
| `TIMEOUT`     | Request timeout (seconds)        | `60`      |
| `BASE_URL`    | Custom API endpoint              | See below |

## Default API Endpoints

- Domestic version: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- International version: `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`

## Supported Models

Qwen series models:

- `qwen-plus`: Enhanced version
- `qwen-max`: Advanced version
- `qwen-max-longcontext`: Long context version
- `qwen-turbo`: Lightweight fast version

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support

## Important Notes

- Requires an Alibaba Cloud account with Bailian service enabled
- Usage-based billing, refer to Alibaba Cloud official pricing
- Service provided through OpenAI-compatible interface
- Supports Alibaba Cloud region restrictions

## Resources

- [Official API Documentation](https://help.aliyun.com/zh/model-studio/use-qwen-by-calling-api)
- [Alibaba Cloud Bailian Console](https://dashscope.console.aliyun.com/)
