# Provider Overview & Feature Matrix

YAICLI supports a wide range of LLM providers, giving you flexibility to choose the model that best fits your needs. This page provides an overview of all supported providers and their capabilities.

## Supported Providers

YAICLI currently integrates with the following LLM providers:

### Major Cloud Providers

| Provider           | Description                   | Default Base URL                                          | API Documentation                                                                |
| ------------------ | ----------------------------- | --------------------------------------------------------- | -------------------------------------------------------------------------------- |
| OpenAI             | GPT models and advanced AI    | `https://api.openai.com/v1`                               | [Docs](https://platform.openai.com/docs/api-reference)                           |
| Anthropic (Claude) | Advanced reasoning and safety | `https://api.anthropic.com`                               | [Docs](https://docs.anthropic.com/claude/reference/getting-started-with-the-api) |
| Google Gemini      | Multimodal AI models          | `https://generativelanguage.googleapis.com/v1beta/openai` | [Docs](https://ai.google.dev/gemini-api/docs/openai)                             |
| Cohere             | Enterprise-focused models     | `https://api.cohere.com/v2`                               | [Docs](https://docs.cohere.com/docs)                                             |
| Mistral            | European AI models            | `https://api.mistral.ai/v1`                               | [Docs](https://docs.mistral.ai/api/)                                             |

### High-Performance Inference

| Provider   | Description                    | Default Base URL                      | API Documentation                                                     |
| ---------- | ------------------------------ | ------------------------------------- | --------------------------------------------------------------------- |
| Groq       | Ultra-fast inference platform  | `https://api.groq.com/openai/v1`      | [Docs](https://console.groq.com/docs/quickstart)                      |
| Cerebras   | Hardware-accelerated inference | `https://api.cerebras.ai`             | [Docs](https://inference-docs.cerebras.ai/)                           |
| NVIDIA NIM | GPU-optimized models           | `https://integrate.api.nvidia.com/v1` | [Docs](https://www.nvidia.com/en-us/ai-data-science/products/nim/)    |
| SambaNova  | High-performance AI platform   | `https://api.sambanova.ai/v1`         | [Docs](https://docs.sambanova.ai/sambastudio/latest/open-ai-api.html) |

### Multi-Provider & Aggregation

| Provider    | Description                        | Default Base URL                  | API Documentation                                 |
| ----------- | ---------------------------------- | --------------------------------- | ------------------------------------------------- |
| OpenRouter  | Unified API for multiple providers | `https://openrouter.ai/api/v1`    | [Docs](https://openrouter.ai/docs)                |
| Together    | Open-source model platform         | `https://api.together.xyz/v1`     | [Docs](https://docs.together.ai/)                 |
| HuggingFace | Open-source model hub              | -                                 | [Docs](https://huggingface.co/docs/inference-api) |
| LongCat     | OpenAI-compatible API provider     | `https://api.longcat.chat/openai` | [Docs](https://docs.longcat.chat)                 |

### Cloud Platform Integration

| Provider  | Description              | Default Base URL | API Documentation                          |
| --------- | ------------------------ | ---------------- | ------------------------------------------ |
| Vertex AI | Google Cloud AI platform | -                | [Docs](https://cloud.google.com/vertex-ai) |

### Specialized & Regional

| Provider   | Description                   | Default Base URL                                    | API Documentation                                                       |
| ---------- | ----------------------------- | --------------------------------------------------- | ----------------------------------------------------------------------- |
| DeepSeek   | Code and reasoning specialist | `https://api.deepseek.com/v1`                       | [Docs](https://platform.deepseek.com)                                   |
| XAI (Grok) | Real-time information models  | `https://api.xai.com/v1`                            | [Docs](https://docs.x.ai/)                                              |
| Yi (01.AI) | Multilingual AI models        | `https://api.lingyiwanwu.com/v1`                    | [Docs](https://platform.01.ai/)                                         |
| Doubao     | ByteDance AI models           | `https://ark.cn-beijing.volces.com/api/v3`          | [Docs](https://www.volcengine.com/docs/82379)                           |
| ChatGLM    | Zhipu AI models               | `https://open.bigmodel.cn/api/paas/v4/`             | [Docs](https://open.bigmodel.cn/dev/api)                                |
| Moonshot   | Chinese AI models             | `https://api.moonshot.cn/v1`                        | [Docs](https://platform.moonshot.cn/docs/api/chat)                      |
| Minimax    | Chinese multimodal models     | `https://api.minimaxi.com/v1`                       | [Docs](https://platform.minimaxi.com/document/platform)                 |
| ModelScope | Alibaba's model platform      | `https://api-inference.modelscope.cn/v1/`           | [Docs](https://modelscope.cn/docs/model-service/API-Inference/intro)    |
| Bailian    | Alibaba Cloud AI              | `https://dashscope.aliyuncs.com/compatible-mode/v1` | [Docs](https://help.aliyun.com/zh/model-studio/use-qwen-by-calling-api) |

### Local & Self-Hosted

| Provider | Description         | Default Base URL         | API Documentation                        |
| -------- | ------------------- | ------------------------ | ---------------------------------------- |
| Ollama   | Local model hosting | `http://localhost:11434` | [Docs](https://github.com/ollama/ollama) |

## Feature Comparison

### Core Features

| Provider           | Streaming | Function Calling | MCP Support |
| ------------------ | --------- | ---------------- | ----------- |
| OpenAI             | ✅        | ✅               | ✅          |
| Anthropic (Claude) | ✅        | ✅               | ✅          |
| Google Gemini      | ✅        | ✅               | ✅          |
| Cohere             | ✅        | ✅               | ✅          |
| Mistral            | ✅        | ✅               | ✅          |
| Groq               | ✅        | ✅               | ✅          |
| Cerebras           | ✅        | ✅               | ✅          |
| NVIDIA NIM         | ✅        | ✅               | ✅          |
| SambaNova          | ✅        | ✅               | ✅          |
| OpenRouter         | ✅        | ✅               | ✅          |
| Together           | ✅        | ✅               | ✅          |
| HuggingFace        | ✅        | ✅               | ✅          |
| Vertex AI          | ✅        | ✅               | ✅          |
| DeepSeek           | ✅        | ✅               | ✅          |
| XAI (Grok)         | ✅        | ✅               | ✅          |
| Yi (01.AI)         | ✅        | ✅               | ✅          |
| Doubao             | ✅        | ✅               | ✅          |
| ChatGLM            | ✅        | ✅               | ✅          |
| LongCat            | ✅        | ✅               | ✅          |
| Ollama             | ✅        | ✅               | ✅          |

### Performance Characteristics

| Provider  | Speed  | Cost   | Context    | Special Features      |
| --------- | ------ | ------ | ---------- | --------------------- |
| Groq      | 🔥🔥🔥 | 💰💰   | Standard   | Ultra-fast inference  |
| Cerebras  | 🔥🔥🔥 | 💰💰💰 | Standard   | Hardware acceleration |
| OpenAI    | 🔥🔥   | 💰💰💰 | Large      | Industry standard     |
| Anthropic | 🔥🔥   | 💰💰💰 | Very Large | Safety-focused        |
| Ollama    | 🔥     | Free   | Varies     | Local, private        |
| DeepSeek  | 🔥🔥   | 💰     | Large      | Code specialist       |
| Together  | 🔥🔥   | 💰     | Standard   | Open source focus     |

**Legend:** 🔥 = Speed level, 💰 = Cost level

## Optional Dependencies

Some providers require additional dependencies that can be installed using pip:

```bash
# Install all dependencies
pip install 'yaicli[all]'

# Install specific provider dependencies
pip install 'yaicli[ollama,cohere,doubao,huggingface,gemini,mistral,anthropic]'
```

## Provider-Specific Documentation

For detailed configuration options for each provider, refer to the provider-specific pages:

### Major Cloud Providers

- [OpenAI](openai.md)
- [Anthropic (Claude)](anthropic.md)
- [Google Gemini](gemini.md)
- [DeepSeek](deepseek.md)
- [Cohere](cohere.md)
- [Mistral](mistral.md)
- [ChatGLM](chatglm.md)
- [Moonshot](moonshot.md)
- [XAI (Grok)](xai.md)
- [Yi (01.AI)](yi.md)
- [Doubao](doubao.md)
- [Minimax](minimax.md)

### High-Performance Inference

- [Groq](groq.md)
- [Cerebras](cerebras.md)
- [NVIDIA NIM](nvidia.md)
- [SambaNova](sambanova.md)

### Multi-Provider & Aggregation

- [OpenRouter](openrouter.md)
- [Together](together.md)
- [HuggingFace](huggingface.md)
- [LongCat](longcat.md)
- [ModelScope](modelscope.md)
- [Bailian](bailian.md)

### Cloud Platform Integration

- [Vertex AI](vertexai.md)

### Local & Self-Hosted

- [Ollama](ollama.md)

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
