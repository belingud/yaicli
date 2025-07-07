# Provider Overview & Feature Matrix

YAICLI supports a wide range of LLM providers, giving you flexibility to choose the model that best fits your needs. This page provides an overview of all supported providers and their capabilities.

## Supported Providers

YAICLI currently integrates with the following LLM providers:

| Provider                   | Description                         | Default Base URL                                          | API Documentation                                                                |
| -------------------------- | ----------------------------------- | --------------------------------------------------------- | -------------------------------------------------------------------------------- |
| OpenAI                     | Default provider with GPT models    | `https://api.openai.com/v1`                               | [Docs](https://platform.openai.com/docs/api-reference)                           |
| Claude                     | Anthropic's Claude models           | `https://api.anthropic.com/v1`                            | [Docs](https://docs.anthropic.com/claude/reference/getting-started-with-the-api) |
| Claude (OpenAI-compatible) | Claude via OpenAI-compatible API    | `https://api.anthropic.com/v1/openai`                     | [Docs](https://docs.anthropic.com/en/api/openai-sdk)                             |
| Gemini                     | Google's Gemini models              | `https://generativelanguage.googleapis.com/v1beta/openai` | [Docs](https://ai.google.dev/gemini-api/docs/openai)                             |
| Cohere                     | Cohere's Command models             | `https://api.cohere.com`                                  | [Docs](https://docs.cohere.com/docs)                                             |
| Mistral                    | Mistral AI models                   | `https://api.mistral.ai/v1`                               | [Docs](https://docs.mistral.ai/api/)                                             |
| Ollama                     | Local models via Ollama             | `http://localhost:11434`                                  | [Docs](https://github.com/ollama/ollama)                                         |
| ChatGLM                    | Zhipu.ai's GLM models               |                                                           | [Docs](https://open.bigmodel.cn/dev/api)                                         |
| Deepseek                   | DeepSeek's models                   |                                                           | [Docs](https://platform.deepseek.com)                                            |
| Doubao                     | Doubao models                       |                                                           | -                                                                                |
| HuggingFace                | Various models via HF Inference API |                                                           | [Docs](https://huggingface.co/docs/inference-api)                                |
| Minimax                    | Minimax models                      |                                                           | [Docs](https://www.minimaxi.com)                                                 |
| ModelScope                 | ModelScope models                   |                                                           | [Docs](https://www.modelscope.cn)                                                |
| NVIDIA NIM                 | NVIDIA's NIM models                 |                                                           | [Docs](https://www.nvidia.com/en-us/ai-data-science/products/nim/)               |
| Sambanova                  | SambaNoova's models                 |                                                           | [Docs](https://docs.sambanova.ai/)                                               |
| Siliconflow                | Siliconflow models                  |                                                           | -                                                                                |
| Spark                      | iFlytek's Spark models              |                                                           | [Docs](https://www.xfyun.cn/doc/spark/Web.html)                                  |
| Targon                     | Targon models                       |                                                           | -                                                                                |
| Together                   | Together.ai models                  |                                                           | [Docs](https://docs.together.ai/)                                                |
| Vertex AI                  | Google Cloud Vertex AI              |                                                           | [Docs](https://cloud.google.com/vertex-ai)                                       |
| X AI                       | X AI's Grok models                  |                                                           | -                                                                                |
| Yi                         | 01.ai's Yi models                   |                                                           | [Docs](https://platform.01.ai/)                                                  |

## Feature Comparison

| Provider    | Streaming | Function Calling | MCP Support | Reasoning |
| ----------- | --------- | ---------------- | ----------- | --------- |
| OpenAI      | ✅         | ✅                | ✅           | ✅         |
| Claude      | ✅         | ✅                | ✅           | ✅         |
| Gemini      | ✅         | ✅                | ✅           | ✅         |
| Cohere      | ✅         | ✅                | ✅           | ✅         |
| Mistral     | ✅         | ✅                | ✅           | ✅         |
| Ollama      | ✅         | ✅                | ✅           | ✅         |
| ChatGLM     | ✅         | ✅                | ✅           | ✅         |
| Deepseek    | ✅         | ✅                | ✅           | ✅         |
| HuggingFace | ✅         | ✅                | ✅           | ✅         |
| Vertex AI   | ✅         | ✅                | ✅           | ✅         |
| Together    | ✅         | ✅                | ✅           | ✅         |

## Optional Dependencies

Some providers require additional dependencies that can be installed using pip:

```bash
# Install all dependencies
pip install 'yaicli[all]'

# Install specific provider dependencies
pip install 'yaicli[ollama,cohere,doubao,huggingface,gemini,mistral,anthropic]'
```

## Provider Configuration

Each provider has specific configuration options. Below are basic configuration examples for the most popular providers:

### OpenAI (Default)

```ini
PROVIDER=openai
API_KEY=sk-...
MODEL=gpt-4o
```

### Claude

```ini
PROVIDER=claude
API_KEY=sk-ant-...
MODEL=claude-3-opus-20240229
```

### Gemini

```ini
PROVIDER=gemini
API_KEY=AI...
MODEL=gemini-2.5-flash
```

### Cohere

```ini
PROVIDER=cohere
API_KEY=...
MODEL=command-r-plus
```

### Mistral

```ini
PROVIDER=mistral
API_KEY=...
MODEL=codestral-latest
```

### Ollama (Local)

```ini
PROVIDER=ollama
MODEL=qwen3:32b
```

### Vertex AI (Google Cloud)

```ini
PROVIDER=vertexai
MODEL=gemini-2.5-flash
PROJECT=your-gcp-project-id
LOCATION=us-central1
```

## Provider-Specific Documentation

For detailed configuration options for each provider, refer to the provider-specific pages:

- [OpenAI](openai.md)
- [Azure OpenAI](azure.md) 
- [Gemini](gemini.md)
- [Moonshot](moonshot.md)
- [DashScope](dashscope.md)
- [Zhipu](zhipu.md)
- [Qwen](qwen.md)
- [Baichuan](baichuan.md)
- [Minimax](minimax.md)

## Using Custom OpenAI-Compatible Endpoints

Many providers offer OpenAI-compatible endpoints. To use them:

```ini
PROVIDER=openai
BASE_URL=https://your-custom-endpoint.com/v1
API_KEY=your-api-key
MODEL=model-name
```

## Switching Providers via Environment Variables

You can temporarily switch providers using environment variables:

```bash
export YAI_PROVIDER=gemini
export YAI_API_KEY=AI...
export YAI_MODEL=gemini-2.5-flash
ai "What is quantum computing?"
```

This overrides your config file settings for the current session.
