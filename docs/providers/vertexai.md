# Vertex AI

Google Cloud Vertex AI platform for accessing Gemini and other models.

## Configuration

```ini
PROVIDER=vertexai
PROJECT=your-gcp-project-id
LOCATION=us-central1
MODEL=gemini-1.5-pro
TEMPERATURE=0.3
```

## Key Parameters

| Parameter     | Description               | Default |
| ------------- | ------------------------- | ------- |
| `PROJECT`     | GCP project ID (required) | -       |
| `LOCATION`    | GCP region (required)     | -       |
| `MODEL`       | Model to use              | -       |
| `TEMPERATURE` | Randomness (0.0-1.0)      | `0.3`   |
| `TOP_P`       | Nucleus sampling          | `1.0`   |
| `TOP_K`       | Top-k sampling            | -       |
| `MAX_TOKENS`  | Max response tokens       | `1024`  |
| `TIMEOUT`     | Request timeout (seconds) | `60`    |

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ MCP support
- ✅ Vision capabilities
- ✅ Enterprise features
- ✅ Multi-modal support

## Authentication

Vertex AI requires Google Cloud authentication. Set up authentication using one of these methods:

```bash
# Application Default Credentials
gcloud auth application-default login

# Service Account Key
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# Workload Identity (for GKE)
# Configured automatically in GKE environment
```

## Important Notes

- Based on Gemini provider implementation
- Requires GCP project and location configuration
- Automatic authentication via Google Cloud SDK
- Enterprise-grade security and compliance
- Regional model availability may vary
- Billing through Google Cloud Console