# YAICLI: Your AI Assistant in Command Line

<p align="center">
  <img src="./assets/artwork/logo.png" width="150" alt="YAICLI Logo" />
</p>

YAICLI is a powerful yet lightweight command-line AI assistant that brings the capabilities of Large Language Models (LLMs) like GPT-4o directly to your terminal. Interact with AI through multiple modes: have natural conversations, generate and execute shell commands, or get quick answers without leaving your workflow.

**Supports both standard and deep reasoning models across all major LLM providers.**

## ✨ Key Features

### 🔄 Multiple Interaction Modes

- **💬 Chat Mode**: Engage in persistent conversations with full context tracking
- **🚀 Execute Mode**: Generate and safely run OS-specific shell commands
- **⚡ Quick Query**: Get instant answers without entering interactive mode

### 🧠 Smart Environment Awareness

- **Auto-detection**: Identifies your shell (bash/zsh/PowerShell/CMD) and OS
- **Safe Command Execution**: Verification before running any command
- **Flexible Input**: Pipe content directly (`cat log.txt | ai "analyze this"`)

### 🔌 Universal LLM Compatibility

- **OpenAI-Compatible**: Works with any OpenAI-compatible API endpoint
- **Multi-Provider Support**: Support multiple providers

### 💻 Enhanced Terminal Experience

- **Real-time Streaming**: See responses as they're generated with cursor animation
- **Rich History Management**: Manage histories with 500 entries by default
- **Syntax Highlighting**: Beautiful code formatting with customizable themes

### 🛠️ Developer-Friendly

- **Layered Configuration**: Environment variables > Config file > Sensible defaults
- **Debugging Tools**: Verbose mode with detailed API tracing

### 📚 Function Calling

- **Function Calling**: Enable function calling in API requests
- **Function Output**: Show the output of functions

### 📚 MCP Calling

- **MCP Calling**: Call LLM with MCP tools
- **MCP Output**: Show the output of MCP tools

## Quick Links

- [Installation](installation.md)
- [Basic Usage](usage/basic.md)
- [Advanced Features](usage/advanced.md)
- [API Reference](api/overview.md)
- [Contributing](contributing.md)
- [GitHub Repository](https://github.com/vic4code/yaicli)
