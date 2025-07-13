# Anthropic (Claude)

Anthropic's Claude models via the official Anthropic API.

## Configuration

```ini
PROVIDER=anthropic
API_KEY=sk-ant-api03-your-key-here
MODEL=claude-3-5-sonnet-20241022
TEMPERATURE=0.3
MAX_TOKENS=1024
```

## Key Parameters

| Parameter     | Description                  | Default |
| ------------- | ---------------------------- | ------- |
| `API_KEY`     | Anthropic API key (required) | -       |
| `MODEL`       | Model to use                 | -       |
| `TEMPERATURE` | Randomness (0.0-1.0)         | `0.3`   |
| `TOP_P`       | Nucleus sampling             | `1.0`   |
| `TOP_K`       | Top-k sampling               | -       |
| `MAX_TOKENS`  | Max response tokens          | `1024`  |
| `TIMEOUT`     | Request timeout (seconds)    | `60`    |

## AWS Bedrock Integration

```ini
PROVIDER=anthropic_bedrock
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_REGION=us-east-1
MODEL=anthropic.claude-3-5-sonnet-20241022-v2:0
```

## Google Vertex AI Integration

```ini
PROVIDER=anthropic_vertex
PROJECT_ID=your-gcp-project-id
CLOUD_ML_REGION=us-central1
MODEL=claude-3-5-sonnet@20241022
```

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support
- ✅ System prompts
- ✅ 200K token context

## Important Notes

- API key starts with `sk-ant-`
- Rate limits apply based on your plan
- System prompts are extracted automatically
- All models support vision capabilities
- Bedrock requires AWS credentials
- Vertex AI requires GCP authentication