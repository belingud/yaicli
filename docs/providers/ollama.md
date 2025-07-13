# Ollama

Local LLM hosting platform for running models on your own hardware.

## Configuration

```ini
PROVIDER=ollama
MODEL=llama3.2:3b
BASE_URL=http://localhost:11434
TEMPERATURE=0.7
ENABLE_FUNCTIONS=true
```

## Key Parameters

| Parameter     | Description               | Default                  |
| ------------- | ------------------------- | ------------------------ |
| `MODEL`       | Model name (required)     | -                        |
| `BASE_URL`    | Ollama server URL         | `http://localhost:11434` |
| `TEMPERATURE` | Randomness (0.0-1.0)      | `0.7`                    |
| `TOP_P`       | Nucleus sampling          | `1.0`                    |
| `TIMEOUT`     | Request timeout (seconds) | `60`                     |
| `THINK`       | Enable reasoning mode     | `false`                  |

## Advanced Options

| Parameter     | Description            | Default |
| ------------- | ---------------------- | ------- |
| `SEED`        | Random seed            | -       |
| `NUM_PREDICT` | Max tokens to generate | -       |
| `NUM_CTX`     | Context window size    | -       |
| `NUM_BATCH`   | Batch size             | -       |
| `NUM_GPU`     | GPU layers             | -       |
| `NUM_THREAD`  | CPU threads            | -       |

## Features

- ✅ Streaming responses
- ✅ Function calling
- ✅ Local execution
- ✅ No API costs
- ✅ Privacy preservation
- ✅ Custom models

## Installation

Install Ollama first:

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.ai/install.sh | sh

# Windows
# Download from https://ollama.ai/download
```

Pull models:

```bash
ollama pull llama3.2:3b
ollama pull qwen3:7b
```

## Important Notes

- Requires Ollama server running locally
- Models must be pulled before use
- Performance depends on hardware specs
- Supports OpenAI-compatible tool calling
- Reasoning mode available with `THINK=true` in config
- GPU acceleration recommended for larger models
