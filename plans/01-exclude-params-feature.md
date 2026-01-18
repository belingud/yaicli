# Implementation Plan: EXCLUDE_PARAMS Feature

## Overview

Add an `EXCLUDE_PARAMS` configuration option that allows users to exclude specific parameters from being sent to AI API requests. This is useful when certain API providers don't support certain parameters or when users want to override default parameter behavior.

## Architecture Analysis

Based on the codebase review:

1. **Configuration Flow**:
   - Defaults defined in `yaicli/const.py`
   - Config loading/parsing in `yaicli/config.py` (env vars > config file > defaults)
   - Config consumed by providers in `yaicli/llms/providers/`

2. **Provider Parameter Handling**:
   - Each provider has a `COMPLETION_PARAMS_KEYS` dict mapping API param names to config keys
   - `get_completion_params()` builds the request parameters from config
   - Parameters are sent to the API client (e.g., `client.chat.completions.create(**params)`)

3. **Key Files**:
   - `yaicli/const.py:122-166`: DEFAULT_CONFIG_MAP definition
   - `yaicli/config.py:189-203`: Type conversion logic
   - `yaicli/llms/providers/openai_provider.py:25-34`: COMPLETION_PARAMS_KEYS
   - `yaicli/llms/providers/openai_provider.py:83-95`: get_completion_params()

## Design

### Parameter Name Format

The `EXCLUDE_PARAMS` should use **API parameter names** (not config key names) because:
- Different providers may map the same config key to different API params
- API parameter names are what users see in provider documentation
- More intuitive for users (e.g., "temperature" vs "TEMPERATURE")

Examples:
- Exclude `temperature`: user sets `EXCLUDE_PARAMS=temperature`
- Exclude multiple: `EXCLUDE_PARAMS=temperature,top_p,frequency_penalty`

### Configuration Format

```ini
# In config.ini [core] section:
# Comma-separated list of parameter names to exclude from API requests
EXCLUDE_PARAMS=
```

Environment variable:
```bash
export YAI_EXCLUDE_PARAMS="temperature,top_p"
```

### Implementation Approach

The filtering should happen at the **provider level** in the `get_completion_params()` method, after parameters are built from config but before they're sent to the API.

## Implementation Stages

### Stage 1: Add Configuration Constants
**Goal**: Define the new configuration option in constants
**Files**: `yaicli/const.py`
**Changes**:
1. Add default value constant:
   ```python
   DEFAULT_EXCLUDE_PARAMS: str = ""  # Empty by default
   ```
2. Add to `DEFAULT_CONFIG_MAP` dict (around line 165):
   ```python
   "EXCLUDE_PARAMS": {
       "value": DEFAULT_EXCLUDE_PARAMS,
       "env_key": "YAI_EXCLUDE_PARAMS",
       "type": str
   },
   ```
3. Add to `DEFAULT_CONFIG_INI` template string (around line 228):
   ```ini
   # Comma-separated list of API parameters to exclude from requests
   # Example: temperature,top_p,frequency_penalty
   EXCLUDE_PARAMS=
   ```

**Success Criteria**:
- Config constant defined
- Env var mapping configured
- Default config template includes new option
**Tests**: Manual verification that constant exists
**Status**: Not Started

### Stage 2: Parse EXCLUDE_PARAMS in Config
**Goal**: Convert the comma-separated string into a list for easy filtering
**Files**: `yaicli/config.py`
**Changes**:
1. Add a helper method to parse the exclude list:
   ```python
   def get_exclude_params_list(self) -> List[str]:
       """Parse EXCLUDE_PARAMS config into a list of parameter names.

       Returns:
           List of parameter names to exclude (stripped, lowercase)
       """
       exclude_str = self.get("EXCLUDE_PARAMS", "")
       if not exclude_str or not exclude_str.strip():
           return []
       return [param.strip().lower() for param in exclude_str.split(",") if param.strip()]
   ```

**Success Criteria**:
- Method correctly parses comma-separated values
- Returns empty list when not configured
- Handles whitespace and case normalization
**Tests**: Unit tests for the parser method
**Status**: Not Started

### Stage 3: Update Base Provider Class
**Goal**: Add filtering logic to the base Provider class
**Files**: `yaicli/llms/provider.py`
**Changes**:
1. Add filtering method to Provider base class:
   ```python
   def _filter_excluded_params(self, params: Dict[str, Any], config: dict) -> Dict[str, Any]:
       """Filter out excluded parameters from completion params.

       Args:
           params: The completion parameters dict
           config: The config dict containing EXCLUDE_PARAMS

       Returns:
           Filtered params dict with excluded parameters removed
       """
       exclude_list = []
       exclude_str = config.get("EXCLUDE_PARAMS", "")
       if exclude_str and exclude_str.strip():
           exclude_list = [p.strip().lower() for p in exclude_str.split(",") if p.strip()]

       if not exclude_list:
           return params

       # Filter params, using lowercase comparison
       filtered = {
           k: v for k, v in params.items()
           if k.lower() not in exclude_list
       }

       return filtered
   ```

**Note**: We add this to the base Provider class so all provider implementations can use it without code duplication.

**Success Criteria**:
- Base method available for all providers
- Correctly filters parameters
- Case-insensitive matching
**Tests**: Unit tests for the filter method
**Status**: Not Started

### Stage 4: Integrate Filtering in OpenAI Provider
**Goal**: Apply parameter filtering in the OpenAI provider implementation
**Files**: `yaicli/llms/providers/openai_provider.py`
**Changes**:
1. Modify `get_completion_params()` method (around line 83-95):
   ```python
   def get_completion_params(self) -> Dict[str, Any]:
       """Get the completion parameters based on config and parameter mapping."""
       completion_params = {}
       params_keys = self.get_completion_params_keys()
       for api_key, config_key in params_keys.items():
           if self.config.get(config_key, None) is not None and self.config[config_key] != "":
               completion_params[api_key] = self.config[config_key]

       # Apply exclude params filtering
       completion_params = self._filter_excluded_params(completion_params, self.config)

       return completion_params
   ```

**Success Criteria**:
- OpenAI provider respects EXCLUDE_PARAMS
- Filtered parameters don't appear in API requests
- No breaking changes to existing behavior
**Tests**: Integration tests with OpenAI provider
**Status**: Not Started

### Stage 5: Add Verbose Logging
**Goal**: Log excluded parameters when verbose mode is enabled
**Files**: `yaicli/llms/provider.py`
**Changes**:
1. Update the filter method to support optional logging:
   ```python
   def _filter_excluded_params(
       self,
       params: Dict[str, Any],
       config: dict,
       verbose: bool = False,
       console = None
   ) -> Dict[str, Any]:
       """Filter out excluded parameters from completion params."""
       exclude_list = []
       exclude_str = config.get("EXCLUDE_PARAMS", "")
       if exclude_str and exclude_str.strip():
           exclude_list = [p.strip().lower() for p in exclude_str.split(",") if p.strip()]

       if not exclude_list:
           return params

       # Track what was excluded for logging
       excluded_keys = [k for k in params.keys() if k.lower() in exclude_list]

       # Filter params
       filtered = {
           k: v for k, v in params.items()
           if k.lower() not in exclude_list
       }

       # Log if verbose and something was excluded
       if verbose and excluded_keys and console:
           console.print(
               f"[yellow]Excluded parameters:[/yellow] {', '.join(excluded_keys)}",
               style="dim"
           )

       return filtered
   ```

2. Update OpenAI provider call to pass verbose flag:
   ```python
   completion_params = self._filter_excluded_params(
       completion_params,
       self.config,
       verbose=self.verbose,
       console=self.console
   )
   ```

**Success Criteria**:
- Verbose logging shows excluded parameters
- No logging when verbose=False
- Helpful for debugging
**Tests**: Manual testing with verbose mode
**Status**: Not Started

### Stage 6: Update Other Major Providers
**Goal**: Apply the same filtering to other commonly-used providers
**Files**:
- `yaicli/llms/providers/anthropic_provider.py`
- `yaicli/llms/providers/gemini_provider.py`
- `yaicli/llms/providers/deepseek_provider.py`
- `yaicli/llms/providers/groq_provider.py`
- `yaicli/llms/providers/ollama_provider.py`

**Changes**:
For each provider, add the filtering call in their `get_completion_params()` method:
```python
completion_params = self._filter_excluded_params(
    completion_params,
    self.config,
    verbose=self.verbose,
    console=self.console
)
```

**Success Criteria**:
- All major providers support EXCLUDE_PARAMS
- Consistent behavior across providers
**Tests**: Smoke tests for each provider
**Status**: Not Started

### Stage 7: Documentation and Testing
**Goal**: Document the feature and add comprehensive tests
**Files**:
- README or docs
- Test files

**Changes**:
1. Add documentation explaining:
   - What EXCLUDE_PARAMS does
   - When to use it (incompatible providers, debugging, etc.)
   - Configuration examples
   - How to find valid parameter names

2. Add tests:
   - Unit tests for config parsing
   - Unit tests for filter logic
   - Integration tests with mock API calls
   - Test edge cases (empty config, invalid params, case sensitivity)

**Success Criteria**:
- Feature is documented
- Test coverage > 80%
- All tests pass
**Tests**: Run full test suite
**Status**: Not Started

## Usage Examples

### Example 1: Exclude temperature for a provider that doesn't support it
```ini
[core]
PROVIDER=some-provider
EXCLUDE_PARAMS=temperature
```

### Example 2: Exclude multiple parameters via environment variable
```bash
export YAI_EXCLUDE_PARAMS="temperature,top_p,frequency_penalty"
yaicli "your prompt"
```

### Example 3: Debugging with verbose mode
```bash
yaicli --verbose "your prompt"
# Output will show: "Excluded parameters: temperature, top_p"
```

## Testing Strategy

1. **Unit Tests**:
   - Config parsing: empty, single, multiple, whitespace
   - Filter logic: case sensitivity, partial matches, empty list

2. **Integration Tests**:
   - Mock API calls to verify excluded params don't appear
   - Test with different providers

3. **Manual Tests**:
   - Real API calls with excluded parameters
   - Verify API doesn't reject requests
   - Check verbose logging output

## Considerations

### Why Filter at Provider Level?

**Pros**:
- Provider-specific parameter names are used
- Each provider can customize if needed
- Doesn't affect config loading

**Cons**:
- Need to update each provider implementation

**Decision**: Filter at provider level but provide base implementation in Provider class to minimize code duplication.

### Case Sensitivity

Parameter names will be matched **case-insensitively** to prevent user errors:
- Config: `EXCLUDE_PARAMS=Temperature,TOP_P`
- Will match: `temperature`, `top_p`

### Invalid Parameter Names

If a user specifies a parameter name that doesn't exist in the params dict, it will be silently ignored (no error). This is intentional because:
- Different providers have different parameters
- User might configure once for multiple providers
- Failing would be too strict

### Performance Impact

Minimal - the filtering is a simple dict comprehension done once per request.

## Risks and Mitigations

1. **Risk**: Users exclude required parameters (like "model")
   **Mitigation**: Documentation warns about this; API will return clear error

2. **Risk**: Different providers use different parameter names
   **Mitigation**: Documentation provides parameter name reference per provider

3. **Risk**: Breaking existing behavior
   **Mitigation**: Default is empty (no exclusions), so existing users unaffected

## Open Questions

1. Should we validate parameter names against known parameters?
   - **Decision**: No, too restrictive. Let API validate.

2. Should we support wildcard patterns (e.g., `*_penalty`)?
   - **Decision**: Not in initial version. Can add later if needed.

3. Should excluded params be shown in non-verbose mode?
   - **Decision**: No, only in verbose mode to avoid noise.
