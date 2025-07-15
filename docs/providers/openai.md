# OpenAI

OpenAI's GPT models and API services.

## Configuration

```ini
PROVIDER=openai
API_KEY=sk-your-openai-api-key
MODEL=o3
TEMPERATURE=0.3
TOP_P=1.0
MAX_TOKENS=1024
REASONING_EFFORT=low
```

## Key Parameters

| Parameter          | Description                   | Default                     |
| ------------------ | ----------------------------- | --------------------------- |
| `API_KEY`          | OpenAI API key (required)     | -                           |
| `MODEL`            | Model to use                  | -                           |
| `TEMPERATURE`      | Randomness (0.0-1.0)          | `0.3`                       |
| `TOP_P`            | Nucleus sampling              | `1.0`                       |
| `MAX_TOKENS`       | Max response tokens           | `1024`                      |
| `TIMEOUT`          | Request timeout (seconds)     | `60`                        |
| `REASONING_EFFORT` | Thinking depth (0-10)         | -                           |
| `BASE_URL`         | Custom API endpoint           | `https://api.openai.com/v1` |
| `EXTRA_HEADERS`    | Additional request headers    | -                           |
| `EXTRA_BODY`       | Additional request parameters | -                           |

## Azure OpenAI Configuration

```ini
PROVIDER=openai_azure
API_KEY=your-azure-openai-key
ENDPOINT=https://your-resource.openai.azure.com/
API_VERSION=2024-02-01
DEPLOYMENT=your-deployment-name
MODEL=gpt-4
```

## Azure Key Parameters

| Parameter       | Description                     | Default      |
| --------------- | ------------------------------- | ------------ |
| `API_KEY`       | Azure OpenAI key                | -            |
| `ENDPOINT`      | Azure OpenAI endpoint           | -            |
| `API_VERSION`   | Azure OpenAI API version        | `2024-02-01` |
| `DEPLOYMENT`    | Azure deployment name           | -            |
| `AD_TOKEN`      | Azure AD OAuth token (optional) | -            |
| `DEFAULT_QUERY` | Default query parameters        | -            |

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support
- ✅ Vision capabilities
- ✅ Reasoning parameters
- ✅ Azure integration
- ✅ High context windows

## Important Notes

- API keys start with `sk-`
- Rate limits apply based on your plan
- Azure requires additional configuration
- Models have different token limits and capabilities
- Pricing varies by model and usage
- Some models support image input
- Custom base URLs can be set for compatible endpoints

## Resources

- [OpenAI API Documentation](https://platform.openai.com/docs/api-reference)
- [Azure OpenAI Documentation](https://learn.microsoft.com/en-us/azure/ai-services/openai/)
- [OpenAI Models](https://platform.openai.com/docs/models)
- [OpenAI Pricing](https://openai.com/pricing)
