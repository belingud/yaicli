
---
## [0.6.3](https://github.com/belingud/yaicli/compare/v0.6.2..v0.6.3) - 2025-06-23

### ⛰️  Features

- add error handling for better error show - ([ced63b8](https://github.com/belingud/yaicli/commit/ced63b81cc9339f4bd5569b5bd61d0455c4b2ab5)) - Belingud
- add gemini and vertexai providers - ([1cb56ad](https://github.com/belingud/yaicli/commit/1cb56ada4dde53146ff5a0ad3e2c932577b244d7)) - Belingud

### 🐛 Bug Fixes

- use display_stream return content for command execute - ([5443822](https://github.com/belingud/yaicli/commit/54438224cd6278b6281abe2c282ec79ad3dec276)) - Belingud
- ensure non-empty config values are used in completion params - ([c319ade](https://github.com/belingud/yaicli/commit/c319ade3d041243b445321c450a2efa7966ec2db)) - Belingud

### 🚜 Refactor

- remove unused BaseProvider class - ([1166114](https://github.com/belingud/yaicli/commit/116611461d621f68c85e7bc96d0faa8f30dd08eb)) - Belingud

### 📚 Documentation

- update CHANGELOG.md for v0.6.2 release - ([b9e6354](https://github.com/belingud/yaicli/commit/b9e63547d65eb0a0e875e7acb42917ad309ced14)) - Belingud

### 🧪 Testing

- add tests for gemini and vertexai providers - ([7a9f755](https://github.com/belingud/yaicli/commit/7a9f755a8a4de584db47e3408f9028eb0e71d982)) - Belingud

### ⚙️ Miscellaneous Tasks

- update default reasoning effort to empty string - ([e7f59c3](https://github.com/belingud/yaicli/commit/e7f59c3390f0e3aed443436d335b4ee1f114dec0)) - Belingud


---
## [0.6.2](https://github.com/belingud/yaicli/compare/v0.6.1..v0.6.2) - 2025-06-23

### ⛰️  Features

- update provider mappings in ProviderFactory - ([3dce344](https://github.com/belingud/yaicli/commit/3dce344a7b30de315fd69d7af692a0e160d7b58d)) - Belingud
- add XaiProvider class based on OpenAIProvider - ([f177da8](https://github.com/belingud/yaicli/commit/f177da88c35d5934bf14c111d7bf61e4e8a6cf73)) - Belingud

### 🚜 Refactor

- standardize completion parameter handling across providers - ([25be368](https://github.com/belingud/yaicli/commit/25be368ca67ac57c9beecb0c35223f9fe28c5244)) - Belingud

### 📚 Documentation

- update default settings and add XAI provider - ([1cef2f8](https://github.com/belingud/yaicli/commit/1cef2f8e558162536db8eb22cf58922db0f63b87)) - Belingud
- update CHANGELOG.md for v0.6.1 release - ([0c5ece3](https://github.com/belingud/yaicli/commit/0c5ece3c6da82267b280b96dbea8c52c86d1ca32)) - Belingud

### 🧪 Testing

- add xai to provider factory test - ([f89068f](https://github.com/belingud/yaicli/commit/f89068f401955de4f1f9fdcd862d3a4885d324bb)) - Belingud
- add tests for XaiProvider and new Role class - ([c77d070](https://github.com/belingud/yaicli/commit/c77d0708c395ab1a7dd78e44ed86f87d39ebdf66)) - Belingud
- update provider referer and add new providers - ([423cbbd](https://github.com/belingud/yaicli/commit/423cbbdb1e5bc6296f0262bee62337bd6e343cf6)) - Belingud


---
## [0.6.1](https://github.com/belingud/yaicli/compare/v0.6.0..v0.6.1) - 2025-06-22

### ⛰️  Features

- add error handling for empty choices in OpenAIProvider for better error message - ([9cd2a28](https://github.com/belingud/yaicli/commit/9cd2a285a52c0b1c5a646aadfbcc97eb71c44394)) - Belingud
- add minimax and targon providers - ([e8df86f](https://github.com/belingud/yaicli/commit/e8df86fdb7757e454162661051883a621066fc58)) - Belingud

### 🚜 Refactor

- Unify completion params handling in LLM providers - ([9132020](https://github.com/belingud/yaicli/commit/913202089e7763808ee45186563b332155dca98f)) - Belingud

### 📚 Documentation

- update CHANGELOG.md for v0.6.0 release - ([f9b9085](https://github.com/belingud/yaicli/commit/f9b908507c82b2ac0b03e51e7cbd5a833c6468a4)) - Belingud

### 🧪 Testing

- update mocking strategy for provider tests - ([4b9c410](https://github.com/belingud/yaicli/commit/4b9c41018504ffa4632b4d7af393979543532360)) - Belingud


---
## [0.6.0](https://github.com/belingud/yaicli/compare/v0.5.9..v0.6.0) - 2025-06-22

### ⛰️  Features

- refactor OllamaProvider and update default temperature - ([cf2dbe9](https://github.com/belingud/yaicli/commit/cf2dbe9d105f2731b1e08915027c12f3917d123e)) - Belingud

### 🚜 Refactor

- Update provider naming and Groq N param handling - ([309f70e](https://github.com/belingud/yaicli/commit/309f70e1794dc2f39bf9cd511c26ec0c22db1340)) - Belingud
- revamp LLM client and provider architecture - ([90f7d46](https://github.com/belingud/yaicli/commit/90f7d46ceb79b2ac8b35ce03a5da33ce533aa1bd)) - Belingud

### 📚 Documentation

- update README with installation options and provider configs - ([c7c088f](https://github.com/belingud/yaicli/commit/c7c088fe8b7bcb2e1f9b756913c8166824656484)) - Belingud
- update CHANGELOG.md for v0.5.9 release - ([ba73961](https://github.com/belingud/yaicli/commit/ba7396141440cdc175002356a52954af33e0aaf8)) - Belingud

### 🧪 Testing

- add llms package tests - ([9c3e5c2](https://github.com/belingud/yaicli/commit/9c3e5c2da6c74f274e860cc6c17350a93a9463ba)) - Belingud

### ⚙️ Miscellaneous Tasks

- Update optional dependencies in pyproject.toml - ([cc8f865](https://github.com/belingud/yaicli/commit/cc8f8657166223fc3589f2cde68f5406a90068e3)) - Belingud
- Configure ruff linting and add 'all' optional deps - ([3d660e3](https://github.com/belingud/yaicli/commit/3d660e3a428b4ac2fdbda9bb600ea58247892d98)) - Belingud
- Update project keywords for broader AI model support - ([5e09e7b](https://github.com/belingud/yaicli/commit/5e09e7b9fc2243fd15e129a5928516850e29b98e)) - Belingud


---
## [0.5.9](https://github.com/belingud/yaicli/compare/v0.5.8..v0.5.9) - 2025-06-12

### 📚 Documentation

- update CHANGELOG.md for v0.5.8 release - ([18a47d2](https://github.com/belingud/yaicli/commit/18a47d2a95c0d87b842c6c83884165dcd5fa89f0)) - Belingud

### ⚙️ Miscellaneous Tasks

- update click and typer dependencies - ([1f99298](https://github.com/belingud/yaicli/commit/1f992982905e280ecd676b315f73b184c83cc3c3)) - Belingud


---
## [0.5.8](https://github.com/belingud/yaicli/compare/v0.5.7..v0.5.8) - 2025-05-22

### 🚜 Refactor

- move schemas imports and update StrEnum compatibility - ([a8a5b3b](https://github.com/belingud/yaicli/commit/a8a5b3b8e5dd2d817e71aa4e4d6585d33724062c)) - Belingud

### 📚 Documentation

- update CHANGELOG.md for v0.5.7 release - ([a0a641a](https://github.com/belingud/yaicli/commit/a0a641a032eac9737d7c1f99544651f9f958e322)) - Belingud


---
## [0.5.7](https://github.com/belingud/yaicli/compare/v0.5.6..v0.5.7) - 2025-05-22

### ⛰️  Features

- add support for EXTRA_HEADERS and EXTRA_BODY configuration - ([7f8622f](https://github.com/belingud/yaicli/commit/7f8622fec170c31e9cb0116eb2f7f300ca1a62df)) - Belingud

### 📚 Documentation

- update README with new config options and dependencies - ([ebe2023](https://github.com/belingud/yaicli/commit/ebe202385bad3ae085f9a7e90f235fcbc1acfad0)) - Belingud
- update CHANGELOG.md for v0.5.6 release - ([2cf8e82](https://github.com/belingud/yaicli/commit/2cf8e823d42dfd0d45d6f1a219fda27db39854e4)) - Belingud


---
## [0.5.6](https://github.com/belingud/yaicli/compare/v0.5.5..v0.5.6) - 2025-05-22

### 🐛 Bug Fixes

- update project config and simplify printer logic - ([029b7e2](https://github.com/belingud/yaicli/commit/029b7e26c0502e4ae7f32931cdaa2dd2f1d167a8)) - Belingud

### 📚 Documentation

- Fix formatting in README - ([7e440da](https://github.com/belingud/yaicli/commit/7e440da0fe9492736bf1ad160095447d5fce010b)) - Belingud
- update CHANGELOG.md for v0.5.5 release - ([5d12c69](https://github.com/belingud/yaicli/commit/5d12c692d5f692f8d5ede2e57f0a2a81a16e75a8)) - Belingud

### ⚙️ Miscellaneous Tasks

- add 'ai' as alternative command in pyproject.toml - ([d1852f1](https://github.com/belingud/yaicli/commit/d1852f175ec3a821498640df8755f6e165d71fff)) - Belingud


---
## [0.5.5](https://github.com/belingud/yaicli/compare/v0.5.4..v0.5.5) - 2025-05-21

### 🚜 Refactor

- Improve case-insensitive command handling in CLI - ([a9f1382](https://github.com/belingud/yaicli/commit/a9f13829a66c7e9c3a7726222964f99aece1555b)) - Belingud

### 📚 Documentation

- add producthunt badge to README - ([3b2d98b](https://github.com/belingud/yaicli/commit/3b2d98b586b0d25917aba8c25d12c7f548b489f0)) - Belingud
- add example image for reasoning shell - ([99ff117](https://github.com/belingud/yaicli/commit/99ff1171e1ffef550d1ee3ba01137664428384b8)) - Belingud
- update CHANGELOG.md for v0.5.4 release - ([fb5d95a](https://github.com/belingud/yaicli/commit/fb5d95a145f23760b2b0d72c078014e5874a16c4)) - Belingud


---
## [0.5.4](https://github.com/belingud/yaicli/compare/v0.5.3..v0.5.4) - 2025-05-14

### 📚 Documentation

- Update CHANGELOG.md for v0.5.3 release - ([a0bf128](https://github.com/belingud/yaicli/commit/a0bf1286fce96ff4074c2b2284186e9261c8ca64)) - Belingud

### ⚙️ Miscellaneous Tasks

- Update dependencies - ([698a054](https://github.com/belingud/yaicli/commit/698a054224e49194b59cd6e096a91804a0b859d5)) - Belingud


---
## [0.5.3](https://github.com/belingud/yaicli/compare/v0.5.2..v0.5.3) - 2025-05-14

### 📚 Documentation

- update CHANGELOG.md for v0.5.2 release - ([4393332](https://github.com/belingud/yaicli/commit/4393332566110fa2c0ceac8b223923039987c579)) - Belingud


---
## [0.5.2](https://github.com/belingud/yaicli/compare/v0.5.1..v0.5.2) - 2025-05-14

### 📚 Documentation

- Update sologan and logo - ([1ccd4b5](https://github.com/belingud/yaicli/commit/1ccd4b56fcbd0fcc6f028c48e9b2b19a0f1972f5)) - Belingud
- Update CHANGELOG.md for v0.5.1 release - ([d7023dc](https://github.com/belingud/yaicli/commit/d7023dcb82b17e37c8e493c6209c04d3a7d893d1)) - Belingud


---
## [0.5.1](https://github.com/belingud/yaicli/compare/v0.5.0..v0.5.1) - 2025-05-14

### 🚜 Refactor

- remove unused command line argument - ([2daf0e0](https://github.com/belingud/yaicli/commit/2daf0e04c2ee2e9b1cbac030f19ea6a5653f03d7)) - Belingud

### 📚 Documentation

- add function call support to README - ([191b5ae](https://github.com/belingud/yaicli/commit/191b5aed9ea4d4b42747a258bf2fb8b8c41ebc83)) - Belingud
- Update CHANGELOG.md for v0.5.0 release - ([db7a328](https://github.com/belingud/yaicli/commit/db7a328746b45e2b99c176842fc157e0fc063cf3)) - Belingud


---
## [0.5.0](https://github.com/belingud/yaicli/compare/v0.4.0..v0.5.0) - 2025-05-14

### ⛰️  Features

[!IMPORTANT]
- Add Function Call support.

- Add reasoning effort configuration and function output panel - ([f21d29b](https://github.com/belingud/yaicli/commit/f21d29bcd1b9ebf411a6329dd98b659ded5ec1fa)) - Belingud
- refactor client and printer logic, add function call support - ([9f008be](https://github.com/belingud/yaicli/commit/9f008bed2f1ef42665da0c453474044bb809c9ce)) - Belingud
- add non-stream completion function call - ([572e2e2](https://github.com/belingud/yaicli/commit/572e2e212c1911155467bcc85274e6f536526899)) - Belingud
- add non-stream completion function call - ([13d6154](https://github.com/belingud/yaicli/commit/13d6154ff95a1622365efb49b2b48931c4fcc070)) - Belingud

### 📚 Documentation

- Enhance README with function calling and provider info - ([ab69e5c](https://github.com/belingud/yaicli/commit/ab69e5ca1befe0d14b974451ec96262a6db7a3c0)) - Belingud
- update changelog for v0.4.0 release - ([66db3ee](https://github.com/belingud/yaicli/commit/66db3eed4fd9866b1711477753092de6ab171d57)) - Belingud

### 🧪 Testing

- update test case for refactored project - ([26e0faf](https://github.com/belingud/yaicli/commit/26e0faf8ebf7ce9ebebcc096371f000183c00b4a)) - Belingud

### ⚙️ Miscellaneous Tasks

- update dependencies and script name - ([562d930](https://github.com/belingud/yaicli/commit/562d930fcddf5b874f1eefb9db08a1966490ef37)) - Belingud


---
## [0.4.0](https://github.com/belingud/yaicli/compare/v0.3.3..v0.4.0) - 2025-05-01

**From this version, yaicli will use provider sdk instead of httpx raw request**

Providers:
- OpenAI
- Cohere

### ⛰️  Features

- add provider-based API client architecture with OpenAI and Cohere support - ([9f68de1](https://github.com/belingud/yaicli/commit/9f68de1a545dc297abb2f5479820121cfd753099)) - Belingud
- add role modify warning config and optimize lru_cache - ([9c25162](https://github.com/belingud/yaicli/commit/9c25162f26f6767d90ce24cb8d64780ad45c0219)) - Belingud
- add role modification warnings and singleton pattern for RoleManager - ([e2f9596](https://github.com/belingud/yaicli/commit/e2f959665488b856acec863f121a1126f9529c7c)) - Belingud

### 🚜 Refactor

- reorganize imports and improve code formatting - ([c1ee133](https://github.com/belingud/yaicli/commit/c1ee13399d5cdd503821fadfe2dc8c4f56656854)) - Belingud

### 📚 Documentation

- refine README with updated configurations and provider info - ([90b8170](https://github.com/belingud/yaicli/commit/90b8170e1adefb21ab2fca88c15ca38aaa54ea91)) - Belingud
- update changelog for v0.3.3 release - ([3c73873](https://github.com/belingud/yaicli/commit/3c73873afad339f5d247299b6ffeb3526e1827b3)) - Belingud

### 🧪 Testing

- add provider tests for base, cohere, openai, and factory - ([26e6ef2](https://github.com/belingud/yaicli/commit/26e6ef2ec80763910fe4114a0a1f2f1f8c50e9f9)) - Belingud

### ⚙️ Miscellaneous Tasks

- add chat demo cast and use asciinema for example - ([36f3dea](https://github.com/belingud/yaicli/commit/36f3dea8fecfdc05601c86311a8069b60640c893)) - Belingud
- add yaicli to isort formatting in Justfile - ([d47def9](https://github.com/belingud/yaicli/commit/d47def9e4b021ba4eb7c63715cad2edb787195dd)) - Belingud


---
## [0.3.3](https://github.com/belingud/yaicli/compare/v0.3.2..v0.3.3) - 2025-04-29

### 🚜 Refactor

- remove redundant console print in CLI prompt logic - ([1cf8241](https://github.com/belingud/yaicli/commit/1cf824164db92cb7d91ab49ab44fd1e65ab35533)) - Belingud

### 📚 Documentation

- update changelog for v0.3.2 release - ([328f51b](https://github.com/belingud/yaicli/commit/328f51b79c7d1a982a942c833417841476ec70aa)) - Belingud


---
## [0.3.2](https://github.com/belingud/yaicli/compare/v0.3.1..v0.3.2) - 2025-04-29

### 🐛 Bug Fixes

- mode change in repl should also change role - ([9dea555](https://github.com/belingud/yaicli/commit/9dea5552da2026c5de90a8a9ae8bb77708539100)) - Belingud

### 📚 Documentation

- Update CHANGELOG.md for release 0.3.1 - ([4511255](https://github.com/belingud/yaicli/commit/4511255df1a0c9f3be43a7ecdbc67f6272eb20dc)) - Belingud

### 🧪 Testing

- add X-Title header to API client test - ([f786c48](https://github.com/belingud/yaicli/commit/f786c48cc08aa824126e877c35a4e29e94612eea)) - Belingud

### ⚙️ Miscellaneous Tasks

- configure GitHub Actions for PyPI publishing - ([b2d0cd4](https://github.com/belingud/yaicli/commit/b2d0cd46e77f3994ed0be49ab6a9ae0d943c7124)) - Belingud


---
## [0.3.1](https://github.com/belingud/yaicli/compare/v0.3.0..v0.3.1) - 2025-04-29

### ⛰️  Features

- Add X-Title header to API requests - ([e30060b](https://github.com/belingud/yaicli/commit/e30060b64eafa2ad361c28ef6471e9eebe5e955d)) - Belingud
- clarify --code option help message - ([74349c9](https://github.com/belingud/yaicli/commit/74349c9b38cd7773c53c211da955003294dcf04e)) - Belingud

### 🚜 Refactor

- simplify chat manager test setup - ([8650b05](https://github.com/belingud/yaicli/commit/8650b05df1e6228597be741a2d95c805cf6db0b9)) - Belingud

### 📚 Documentation

- refine CLI documentation and add code example - ([658ecf9](https://github.com/belingud/yaicli/commit/658ecf9444601277a5c63f57fe28ca6936365fba)) - Belingud
- Update README with new features and usage examples - ([756942b](https://github.com/belingud/yaicli/commit/756942b9a80b13dfc49e0e773b1ff98b086c9c3e)) - Belingud
- Update 0.3.0 feat changelog - ([34ad75a](https://github.com/belingud/yaicli/commit/34ad75ab026e44bd2749e9c99f97d187e4e50ca5)) - Belingud
- update CHANGELOG for v0.3.0 - ([ce27418](https://github.com/belingud/yaicli/commit/ce27418275697b8a6919285a153c89326477913a)) - Belingud

### ⚙️ Miscellaneous Tasks

- update Justfile commands and descriptions - ([0c5b841](https://github.com/belingud/yaicli/commit/0c5b841201060eb3dc87ff68c0f6edecce3bb182)) - Belingud


---
## [0.3.0](https://github.com/belingud/yaicli/compare/v0.2.0..v0.3.0) - 2025-04-28

1. Add roles create/delete/list/show commands
2. Add role management functionality
3. Improve configuration management
4. Add reasoning show config, justify config

### ⛰️  Features

- add roles and improve configuration management - ([fa883e9](https://github.com/belingud/yaicli/commit/fa883e9a39a9d72a60d1832b71c67a1bf6492b3c)) - Belingud

### 🚜 Refactor

- reorder imports and remove unused imports - ([28699dd](https://github.com/belingud/yaicli/commit/28699dde7df4c06ba252c5fa98923e373a28cfcd)) - Belingud
- Improve typing and streamline code for maintainability, add role funtion - ([7f7230b](https://github.com/belingud/yaicli/commit/7f7230b6cf5ef07f7bc857f5ba9f710565886107)) - Belingud

### 📚 Documentation

- improve documentation and configuration details - ([28287d0](https://github.com/belingud/yaicli/commit/28287d0a622e1934a7fcb7da0158d65bf3b70be9)) - Belingud
- Add reasoning example and update README - ([c80da0f](https://github.com/belingud/yaicli/commit/c80da0fdd957a13c91a6a55b4ee54dc10c5576ed)) - Belingud
- Update README.md - ([1c169e5](https://github.com/belingud/yaicli/commit/1c169e5895ca0533ab1cfbca948872af30cdb4af)) - belingud
- update CHANGELOG.md for v0.2.0 release - ([9cda1ea](https://github.com/belingud/yaicli/commit/9cda1eaa73c5e81e127eaac3ade8265a2a7ffb61)) - Belingud

### 🧪 Testing

- update CLI input handling and improve test cases for chat mode - ([7a12f71](https://github.com/belingud/yaicli/commit/7a12f716653db7e5215bfa421206951977d5a713)) - Belingud


---
## [0.2.0](https://github.com/belingud/yaicli/compare/v0.1.0..v0.2.0) - 2025-04-22

### ⛰️  Features

- enhance chat management and command-line interface - ([6898273](https://github.com/belingud/yaicli/commit/68982737221b18416ba1eb8201c328203ada2b72)) - Belingud
- add chat persistent - ([291d7b7](https://github.com/belingud/yaicli/commit/291d7b7a9c2595dcc2794e3b36617cb186a6dc56)) - Belingud

### 📚 Documentation

- improve documentation and add chat history features - ([c0f1545](https://github.com/belingud/yaicli/commit/c0f15453862bb23fca29c8f283dcd4c82181d1c5)) - Belingud
- Update README to clarify project description - ([21d6389](https://github.com/belingud/yaicli/commit/21d6389ea70a8770ff798c9b4d4ba22d7d075533)) - Belingud
- update CHANGELOG.md for v0.1.0 release - ([474aaa4](https://github.com/belingud/yaicli/commit/474aaa4a120366a607edc584a8d4b698a16390ca)) - Belingud

### 🧪 Testing

- Update chat management and CLI tests - ([1b3ccb0](https://github.com/belingud/yaicli/commit/1b3ccb027066ec3cd80e8a0d2f9fb0cc65908f50)) - Belingud
- update test case for chat persistent - ([af4f7e7](https://github.com/belingud/yaicli/commit/af4f7e76c2129373b5c3f9ec5971bda14bd961ea)) - Belingud

### Chroe

- Add format command to Justfile - ([676ba1b](https://github.com/belingud/yaicli/commit/676ba1b1759c5439593f57e26d67b7c47b9b26bd)) - Belingud


---
## [0.1.0](https://github.com/belingud/yaicli/compare/v0.0.19..v0.1.0) - 2025-04-20

### ⛰️  Features

- split content and reasoning content for better display - ([83c7cff](https://github.com/belingud/yaicli/commit/83c7cffb6a278320ef6d3884ac6ff9a8a7c4910f)) - Belingud

### 🚜 Refactor

- Replace "reasoning" with "thinking" in tests, fix CLI exit - ([519d210](https://github.com/belingud/yaicli/commit/519d21024993db434671375310ce0417610d30ee)) - Belingud
- Rename INTERACTIVE_MAX_HISTORY to INTERACTIVE_ROUND - ([ac17cad](https://github.com/belingud/yaicli/commit/ac17cadad1015cf4650a84f1ca566da4afc08e54)) - Belingud
- refactor yaicli, imporve logic - ([71d19d6](https://github.com/belingud/yaicli/commit/71d19d6f0acc4ea1f139392473ddc7a968b78896)) - Belingud
- extract completion response processing logic - ([d9f8d08](https://github.com/belingud/yaicli/commit/d9f8d085198bc1374f021f24204d81f23a923949)) - Belingud
- refactor yaicli structure - ([e2ad1be](https://github.com/belingud/yaicli/commit/e2ad1bec6426120bf2ff162a248a7cf6b82e21c7)) - Belingud

### 📚 Documentation

- improve README with detailed features and usage - ([555f2b7](https://github.com/belingud/yaicli/commit/555f2b7832649b6de035298454f3332f2d1917a2)) - Belingud
- add example artwork - ([8b40706](https://github.com/belingud/yaicli/commit/8b40706e644c9c7a1c31c19286accd23d055f578)) - Belingud
- update README with timeout option and improved help text - ([cd0f031](https://github.com/belingud/yaicli/commit/cd0f031148bc1dfe19602ea23ff0a98c75464ad0)) - Belingud
- update CHANGELOG for v0.0.19 release - ([4ff2781](https://github.com/belingud/yaicli/commit/4ff2781334957dd6b13dd694ac6f52f045094a95)) - Belingud

### 🧪 Testing

- add new options to mock CLI config - ([0279155](https://github.com/belingud/yaicli/commit/0279155bbb53db57c128834d35d17193970d2bbe)) - Belingud
- update test case for refactor - ([d6072b3](https://github.com/belingud/yaicli/commit/d6072b39bc4e798030fe28ed09fede9150cd933e)) - Belingud
- update tests for refactor - ([024edb7](https://github.com/belingud/yaicli/commit/024edb7f22fd479ecf2f225d5d8f7d59af4777e0)) - Belingud


---
## [0.0.19](https://github.com/belingud/yaicli/compare/v0.0.18..v0.0.19) - 2025-04-16

### ⛰️  Features

- enhance configuration handling with type support and improve default config initialization - ([34bc896](https://github.com/belingud/yaicli/commit/34bc896df1ae97f5a111cc95a4ebd58caafc6d07)) - Belingud

### 📚 Documentation

- update CHANGELOG.md for v0.0.18 release - ([bc19008](https://github.com/belingud/yaicli/commit/bc190086d5b1bcc9b083b057f891d3cdaff6ef0d)) - Belingud


---
## [0.0.18](https://github.com/belingud/yaicli/compare/v0.0.17..v0.0.18) - 2025-04-14

### ⛰️  Features

- add auto-suggest from history and improve config handling - ([22b31de](https://github.com/belingud/yaicli/commit/22b31ded71b4ecb87e1829076416b615affa38b4)) - Belingud

### 📚 Documentation

- update CHANGELOG.md for v0.0.17 release - ([af27d29](https://github.com/belingud/yaicli/commit/af27d29351d5c37c7473bb4021eaf31f2d7a2cfb)) - Belingud


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


