
---
## [0.0.17](https://github.com/belingud/yaicli/compare/v0.0.16..v0.0.17) - 2025-04-14

### 🐛 Bug Fixes

- Correct stdin TTY check and remove completer - ([e2ee703](https://github.com/belingud/yaicli/commit/e2ee7039c2f9fc707fe9a4eec57d2226a0e25254)) - Belingud

### 🚜 Refactor

- remove unused WordCompleter import - ([968e6f1](https://github.com/belingud/yaicli/commit/968e6f194aee2c1467b1e9b68bb118af614bd5ec)) - Belingud

### ⚙️ Miscellaneous Tasks

- update yaicli version to 0.0.16 in uv.lock and CHANGELOG.md - ([f9376c4](https://github.com/belingud/yaicli/commit/f9376c4fa7e6641ebed20bb071fac997c4467243)) - Belingud


---
## [0.0.16](https://github.com/belingud/yaicli/compare/v0.0.15..v0.0.16) - 2025-04-14

### ⛰️  Features

- **(cli)** add max history limit and stdin support - ([1b685df](https://github.com/belingud/yaicli/commit/1b685df079a0cb3010c73c543bdf8c4fbb72195d)) - Belingud

### 🚜 Refactor

- Remove unused io import - ([1e72f6c](https://github.com/belingud/yaicli/commit/1e72f6c3a1dfaff6326ad171aee360c57592be24)) - Belingud

### 📚 Documentation

- update README with new shortcuts and max history size - ([af70000](https://github.com/belingud/yaicli/commit/af700006e2a5f6b1b4ec1ec90396e00c45b4509f)) - Belingud

### ⚙️ Miscellaneous Tasks

- update yaicli version to 0.0.15 in uv.lock and CHANGELOG.md - ([15faced](https://github.com/belingud/yaicli/commit/15faced8e89e5eebc7ed6984be6b0e1a7743ff8c)) - Belingud


---
## [0.0.15](https://github.com/belingud/yaicli/compare/v0.0.14..v0.0.15) - 2025-04-11

### ⛰️  Features

- add CODE_THEME configuration for code block styling - ([ed0e8f6](https://github.com/belingud/yaicli/commit/ed0e8f62f73128ef2c57a472560ae438c8738103)) - Belingud

### 🐛 Bug Fixes

- handle None value in SHELL environment variable - ([a4e29f5](https://github.com/belingud/yaicli/commit/a4e29f5876f042c71d9a9d36f6577ce751a26eba)) - Belingud

### 📚 Documentation

- update CHANGELOG.md with env key prefix change - ([48b33da](https://github.com/belingud/yaicli/commit/48b33da0d290ac9707e0e441318e50760c7de251)) - Belingud
- update README.md with improved command execution format - ([03b2417](https://github.com/belingud/yaicli/commit/03b2417abc0e3127facb7638b31f07e1e35d8da1)) - Belingud
- update command execution UI in README.md - ([a4aadc8](https://github.com/belingud/yaicli/commit/a4aadc8c47b01117edfadb49db058e5e44847061)) - Belingud

### 🎨 Styling

- fix spacing around 'or' operator in shell detection - ([44cedc9](https://github.com/belingud/yaicli/commit/44cedc993fda3b64df16adfc5a1381c31c04b045)) - Belingud

### 🧪 Testing

- add smoke tests for CLI and fix shell detection tests - ([baa1beb](https://github.com/belingud/yaicli/commit/baa1beb0238eb0c228d0c56310839d53b09c8484)) - Belingud

### ⚙️ Miscellaneous Tasks

- update yaicli version to 0.0.14 in uv.lock and CHANGELOG.md - ([9d21edf](https://github.com/belingud/yaicli/commit/9d21edf9c046fe4c976750b27a0554d4605ccc5a)) - Belingud


---
## [0.0.14](https://github.com/belingud/yaicli/compare/v0.0.13..v0.0.14) - 2025-04-10

### ⛰️  Features

- **(cli)** enhance command execution and output display - ([d101841](https://github.com/belingud/yaicli/commit/d101841b17ee57e421574408fdc643a4f5b1eea7)) - Belingud

### 🚜 Refactor

- clean up unused imports in yaicli.py - ([71c64af](https://github.com/belingud/yaicli/commit/71c64af167b0b0d2b8f771302b86035da0c8f18f)) - Belingud

### 📚 Documentation

- **(Justfile)** update changelog command message - ([b060812](https://github.com/belingud/yaicli/commit/b060812488d8c64bb0bded6433fb93a66946c8aa)) - Belingud

### ⚙️ Miscellaneous Tasks

- update yaicli version to 0.0.13 in uv.lock and CHANGELOG.md - ([3806f70](https://github.com/belingud/yaicli/commit/3806f707e320ec7616264e62c28d3e345fb6a79d)) - Belingud


---
## [0.0.13](https://github.com/belingud/yaicli/compare/v0.0.12..v0.0.13) - 2025-04-09

[!IMPORTANT]
- Change env key prefix from AI_ to YAI_

### ⛰️  Features

- **(cli)** add command edit option and improve console output styling - ([48c14cc](https://github.com/belingud/yaicli/commit/48c14ccff33af8ebeaeb100e002cf15c01d3756e)) - Belingud
- refactor CLI and add new configuration options - ([ad09301](https://github.com/belingud/yaicli/commit/ad093015cd2d54fbd17e6a07dd56af9459b2070f)) - Belingud

### 📚 Documentation

- update README with new ASCII art and command examples - ([cdcb9af](https://github.com/belingud/yaicli/commit/cdcb9af6ece0cfa770390aa5900db5822c80d115)) - Belingud
- update CHANGELOG.md for v0.0.12 release - ([456c454](https://github.com/belingud/yaicli/commit/456c454f995fa2e6bf77fba9ca5d7b904e674f4e)) - Belingud

### ⚙️ Miscellaneous Tasks

- add ruff cache cleanup and uv lock to changelog - ([218b310](https://github.com/belingud/yaicli/commit/218b3103644b8aac6397acc2a765244c3bfae622)) - Belingud


---
## [0.0.12](https://github.com/belingud/yaicli/compare/v0.0.11..v0.0.12) - 2025-04-08

### ⛰️  Features

- add chat history and improve CLI UX with completions - ([7749883](https://github.com/belingud/yaicli/commit/7749883f886c23fc5226965795ae46128caacd13)) - Belingud

### 📚 Documentation

- restructure CLI options documentation in README - ([142ac78](https://github.com/belingud/yaicli/commit/142ac781f677b4285409414402f1493562bd6a90)) - Belingud
- update CHANGELOG.md for v0.0.11 release - ([6a6b3ae](https://github.com/belingud/yaicli/commit/6a6b3ae47d0ee2e3ae41160715f3416c3c1ce3bc)) - Belingud


---
## [0.0.11](https://github.com/belingud/yaicli/compare/v0.0.10..v0.0.11) - 2025-04-07

### 🚜 Refactor

- **(yaicli)** improve stream response parsing and add plaintext test - ([92383ae](https://github.com/belingud/yaicli/commit/92383aea242bebdf6e5149fde44d077d0757fc59)) - Belingud
- replace requests with httpx for HTTP client and update dependencies - ([cfc3823](https://github.com/belingud/yaicli/commit/cfc38232952b1eba8907067a14628fa24a81bfb6)) - Belingud

### 📚 Documentation

- update project title in README - ([cf8aaa7](https://github.com/belingud/yaicli/commit/cf8aaa7ea30c4ff845d27a5fd120b4157f28dc0c)) - Belingud

### ⚙️ Miscellaneous Tasks

- add publish command to Justfile - ([a2a76e5](https://github.com/belingud/yaicli/commit/a2a76e544332cc703a0956426c38dd5bd9301e12)) - Belingud
- update yaicli version to 0.0.10 and CHANGELOG - ([aab8fb2](https://github.com/belingud/yaicli/commit/aab8fb2340950028851577331f87fbbffb75e242)) - Belingud


---
## [0.0.10](https://github.com/belingud/yaicli/compare/v0.0.9..v0.0.10) - 2025-04-05

### 📚 Documentation

- update assistant name in default prompt - ([e92313e](https://github.com/belingud/yaicli/commit/e92313ecbd95191443b26320ae4cc26bf1983718)) - Belingud

### ⚙️ Miscellaneous Tasks

- update yaicli version to 0.0.9 and CHANGELOG - ([2a47a8b](https://github.com/belingud/yaicli/commit/2a47a8b318771139ae5f0515d7c04ccf7fef92eb)) - Belingud


---
## [0.0.9](https://github.com/belingud/yaicli/compare/v0.0.8..v0.0.9) - 2025-04-05

### ⛰️  Features

- add reasoning model support - ([8a3d21b](https://github.com/belingud/yaicli/commit/8a3d21bc1aea147652b345d0015c2468724ee37d)) - Belingud

### 📚 Documentation

- add configuration guide for non-OpenAI LLM providers - ([20f590d](https://github.com/belingud/yaicli/commit/20f590d374a3e6fa4b6c7a21529abec7dbb7d3b6)) - Belingud

### ⚙️ Miscellaneous Tasks

- update yaicli version to 0.0.8 and improve README - ([282d3b5](https://github.com/belingud/yaicli/commit/282d3b5c987a333294ed09bfaca74f2ed0e7db12)) - Belingud


---
## [0.0.8](https://github.com/belingud/yaicli/compare/v0.0.7..v0.0.8) - 2025-04-04

### ⛰️  Features

- add command filtering and improve history management - ([e743b13](https://github.com/belingud/yaicli/commit/e743b1381e07c55e8adb49a4618359c91b1b932d)) - Belingud

### 🧪 Testing

- restructure and add new test files for CLI functionality - ([09c81eb](https://github.com/belingud/yaicli/commit/09c81eb9002ed8735b2cbc41dfd739448960dfce)) - Belingud

### ⚙️ Miscellaneous Tasks

- update yaicli version to 0.0.7 and improve README - ([71a8eff](https://github.com/belingud/yaicli/commit/71a8eff5e77e5aed35a7dc2825be8dbb0a73cebe)) - Belingud


---
## [0.0.7](https://github.com/belingud/yaicli/compare/v0.0.6..v0.0.7) - 2025-04-04

### 🚜 Refactor

- simplify CLI structure and improve code maintainability - ([4eed7d8](https://github.com/belingud/yaicli/commit/4eed7d85abf3a75766e015533682beb2998f8c3e)) - Belingud

### ⚙️ Miscellaneous Tasks

- update yaicli version to 0.0.6 and CHANGELOG - ([563a468](https://github.com/belingud/yaicli/commit/563a4681c1a2e96a0609f2bd9822410567c4d0d0)) - Belingud


---
## [0.0.6](https://github.com/belingud/yaicli/compare/v0.0.5..v0.0.6) - 2025-04-03

### 🚜 Refactor

- update environment variable names and remove max_tokens - ([3abba5f](https://github.com/belingud/yaicli/commit/3abba5fe189b3de0d005907e159a46291a69636f)) - Belingud
- simplify config handling and remove DEFAULT_MODE - ([3439eda](https://github.com/belingud/yaicli/commit/3439eda71fdb24816de9c61c7ccee389e32c53b2)) - Belingud

### ⚙️ Miscellaneous Tasks

- update CHANGELOG and uv.lock for version 0.0.5 - ([d5abef4](https://github.com/belingud/yaicli/commit/d5abef4b602355fe472abaecd07f2701e8a38e4b)) - Belingud


---
## [0.0.5](https://github.com/belingud/yaicli/compare/v0.0.4..v0.0.5) - 2025-04-02

### 🚜 Refactor

- rename ShellAI to YAICLI and update related tests - ([2284297](https://github.com/belingud/yaicli/commit/2284297d018851abcb74f01064554b00df821301)) - Belingud

### 📚 Documentation

- update README with detailed project information and usage instructions - ([c71d50c](https://github.com/belingud/yaicli/commit/c71d50c9d232c47a3cdbe035d03c1f4a0dbbe7d2)) - Belingud

### ⚙️ Miscellaneous Tasks

- update yaicli version to 0.0.4 - ([03cdedb](https://github.com/belingud/yaicli/commit/03cdedb38465adcf4fc10d4379b2d939daf22d9d)) - Belingud


---
## [0.0.4](https://github.com/belingud/yaicli/compare/v0.0.3..v0.0.4) - 2025-04-02

### 🚜 Refactor

- simplify multi-line statements for better readability - ([4870bb7](https://github.com/belingud/yaicli/commit/4870bb7460682791ca79bbe2bcc0cef94bf51c26)) - Belingud
- rename ShellAI to yaicli and improve CLI help handling - ([dad0905](https://github.com/belingud/yaicli/commit/dad090540a7c1f8c8b30e3c688643a76e504b0c0)) - Belingud

### ⚙️ Miscellaneous Tasks

- update yaicli version to 0.0.3 - ([a689a02](https://github.com/belingud/yaicli/commit/a689a02b1c5e0cb278484267ef71f5f3acec8203)) - Belingud


---
## [0.0.3](https://github.com/belingud/yaicli/compare/v0.0.2..v0.0.3) - 2025-04-02

### 🚜 Refactor

- **(changelog)** switch from git log to git cliff for changelog generation - ([242a51d](https://github.com/belingud/yaicli/commit/242a51d93a25675041a7fe19c4a0db1c7c12a663)) - Belingud
- update CLI assistant description and error handling - ([1a8bcdc](https://github.com/belingud/yaicli/commit/1a8bcdc86c72a75259d266291bc9e5350fc81f61)) - Belingud
- fix spacing in clean target and simplify build target - ([2a1050e](https://github.com/belingud/yaicli/commit/2a1050e7a9eea8753c164553b13796e5510b7965)) - Belingud


---
## [0.0.2] - 2025-04-02

### ⛰️  Features

- enhance OS detection and LLM API request handling - ([8c00de0](https://github.com/belingud/yaicli/commit/8c00de099e1c75fedcdd33e9d7e0443818538059)) - Belingud
- add new dependencies and configurable API paths - ([3be3f67](https://github.com/belingud/yaicli/commit/3be3f67b3bd9645a9a8c9909be0e5542612c1c71)) - Belingud

### 🚜 Refactor

- **(config)** migrate config from JSON to INI format and enhance error handling - ([f556872](https://github.com/belingud/yaicli/commit/f556872fdb521adf8e20da6498fdaac26998a5b7)) - Belingud
- update config path to reflect project name change - ([e6bf761](https://github.com/belingud/yaicli/commit/e6bf761aa0fae20b643848c586c6dc55d6f324fb)) - Belingud
- rename project from llmcli to yaicli and update related files - ([cdb5a97](https://github.com/belingud/yaicli/commit/cdb5a97d06c9f042c1c8731c8f11a4a7284783f0)) - Belingud
- rename project from shellai to llmcli and update related files - ([db4ecb8](https://github.com/belingud/yaicli/commit/db4ecb85236b72fd7536c99b21d210037c09889e)) - Belingud
- reorganize imports and improve code readability - ([0f52c05](https://github.com/belingud/yaicli/commit/0f52c05918d177d4623ff2f07aff2fc2e3aa9e91)) - Belingud
- migrate llmcli to class-based ShellAI implementation - ([2509cba](https://github.com/belingud/yaicli/commit/2509cba5cad7c8626f794d88d971fff7eea9a404)) - Belingud

### Build

- add bump2version for version management - ([de287f1](https://github.com/belingud/yaicli/commit/de287f1262eae64ae5fd0cb634dea93762a17282)) - Belingud


