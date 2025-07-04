# LLM Providers

YAICLI supports a wide range of LLM providers. This page documents the configuration options for each provider.

## Supported Providers

YAICLI currently supports these providers:

- AI21
- Chatglm
- Chuts
- Cohere
- Cohere Badrock
- Cohere Sagemaker
- Deepseek
- Doubao
- Gemini
- Groq
- Huggingface
- Minimax
- Mistral
- ModelScope
- Ollama
- OpenAI
- Sambanova
- Siliconflow
- Spark
- Targon
- Together
- Vertex AI
- X AI
- Yi
- Any OpenAI-compatible provider

## Provider Configuration

### OpenAI (Default)

```ini
PROVIDER=openai
BASE_URL=
API_KEY=
MODEL=gpt-4o
```

Extra parameters:

```ini
# REASONING_EFFORT: [high, medium, low]
REASONING_EFFORT=
```

See official documentation for more details: https://platform.openai.com/docs/guides/reasoning?api-mode=chat

### Deepseek

```ini
PROVIDER=deepseek
API_KEY=
MODEL=deepseek-chat
```

### OpenRouter

```ini
PROVIDER=openrouter
API_KEY=
MODEL=deepseek/deepseek-chat-v3-0324
```

### Mistral

```ini
PROVIDER=mistral
API_KEY=
MODEL=codestral-latest
```

### Gemini

Basic configuration:

```ini
PROVIDER=gemini
API_KEY=
MODEL=gemini-2.5-flash
```

Extra parameters:

```ini
TOP_K=
PRESENCE_PENALTY=
FREQUENCY_PENALTY=
SEED=
THINKING_BUDGET=
API_VERSION=
BASE_URL=
```

### Vertex AI

```ini
PROVIDER=vertexai
MODEL=gemini-2.5-flash
PROJECT=
LOCATION=
```

### Huggingface

Default `HF_PROVIDER` is `auto`.

```ini
HF_PROVIDER=auto
PROVIDER=huggingface
API_KEY=
MODEL=deepseek-ai/DeepSeek-R1-0528
```

See official docs for `HF_PROVIDER`: https://huggingface.co/docs/inference-providers/index

### Groq

```ini
PROVIDER=groq
API_KEY=
MODEL=llama-3.3-70b-versatile
```

### XAI

```ini
PROVIDER=xai
API_KEY=
MODEL=grok-3
```

### Chatglm

```ini
PROVIDER=chatglm
API_KEY=
MODEL=glm-4-plus
```

Extra parameters:

Check official docs: https://bigmodel.cn/dev/api/normal-model/glm-4

```ini
# true or false
DO_SAMPLE=
```

### Cohere

```ini
PROVIDER=cohere
API_KEY=
MODEL=command-a-03-2025
```

Supported parameters:

```ini
ENVIRONMENT=
```

For private deploy and Azure API, you need to set BASE_URL:

```ini
PROVIDER=cohere
API_KEY=
MODEL=command-a-03-2025
BASE_URL=<YOUR_ENDPOINT>
```

For Bedrock and Sagemaker Cohere API:

```ini
PROVIDER=cohere-bedrock
# or PROVIDER=cohere-sagemaker
API_KEY=
MODEL=command-a-03-2025

AWS_REGION=xx
AWS_ACCESS_KEY_ID=xx
AWS_SECRET_ACCESS_KEY=xx
AWS_SESSION_TOKEN=xx
```

Note: `MODEL` for Sagemaker should be the endpoint name:

```ini
MODEL=<YOUR_ENDPOINT_NAME>
```

### Ollama

```ini
PROVIDER=ollama
# BASE_URL=http://localhost:11434
MODEL=qwen3:32b
```

Supported options:

```ini
TEMPERATURE=
TOP_P=
SEED=
NUM_PREDICT=
NUM_CTX=
NUM_BATCH=
NUM_GPU=
MAIN_GPU=
LOW_VRAM=
F16_KV=
LOGITS_ALL=
VOCAB_ONLY=
USE_MMAP=
USE_MLOCK=
NUM_THREAD=
```

### More Providers

Please refer to the [official documentation](https://github.com/vic4code/yaicli) for details on additional providers. 