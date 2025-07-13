# Cohere

Cohere's Command models for text generation and analysis.

## Configuration

```ini
PROVIDER=cohere
API_KEY=your-cohere-api-key
MODEL=command-r-plus-latest
TEMPERATURE=0.7
```

## Key Parameters

| Parameter     | Description               | Default                     |
| ------------- | ------------------------- | --------------------------- |
| `API_KEY`     | Cohere API key (required) | -                           |
| `MODEL`       | Model to use              | -                           |
| `TEMPERATURE` | Randomness (0.0-1.0)      | `0.7`                       |
| `TIMEOUT`     | Request timeout (seconds) | `60`                        |
| `BASE_URL`    | Custom API endpoint       | `https://api.cohere.com/v2` |
| `ENVIRONMENT` | Environment setting       | -                           |

## AWS Bedrock Integration

```ini
PROVIDER=cohere_bedrock
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_REGION=us-east-1
AWS_SESSION_TOKEN=your-session-token
MODEL=cohere.command-r-plus-v1:0
```

## AWS SageMaker Integration

```ini
PROVIDER=cohere_sagemaker
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_REGION=us-east-1
AWS_SESSION_TOKEN=your-session-token
MODEL=your-sagemaker-endpoint
```

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ Tool planning
- ✅ RAG capabilities
- ✅ Multi-language support

## Important Notes

- Supports OpenAI-compatible tool schemas
- Tool planning shows reasoning before tool calls
- Supports document format for tool responses
- RAG features with citation support
- Multiple deployment options (API, Bedrock, SageMaker)