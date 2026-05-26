# Copilot Instructions for Python API Polling Project

## Project Context
This is a Python-based API polling application designed for portability across different environments (local development, Docker containers, and cloud platforms like Azure Discovery).

## Code Style Guidelines

### Python Standards
- Use Python 3.9+ features and type hints for all function signatures
- Follow PEP 8 naming conventions (snake_case for functions/variables, UPPER_CASE for constants)
- Use `pathlib.Path` instead of `os.path` for file operations
- Prefer f-strings for string formatting
- Add docstrings to all functions using Google style format

### Configuration Management
- Use environment variables for all configuration with sensible defaults
- Support both `.env` files (via python-dotenv) and direct environment variables
- Implement configuration precedence: CLI args > env vars > config files > defaults
- Use `pydantic` Settings classes for configuration validation when possible

### API Interaction Patterns
```python
# Always use exponential backoff for retries
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def call_api(endpoint: str, **kwargs) -> dict:
    """Make API call with automatic retry logic."""
    pass
```

### Polling Implementation
- Use async/await patterns with `asyncio` for efficient polling
- Implement configurable poll intervals with jitter to avoid thundering herd
- Always include timeout mechanisms
- Log poll attempts and results at appropriate levels (DEBUG for success, WARNING for retries, ERROR for failures)

### Error Handling
- Use custom exception classes for different error scenarios
- Always catch and log exceptions at the appropriate level
- Implement graceful shutdown handling (SIGTERM, SIGINT)
- Return meaningful exit codes (0=success, 1=general error, 2=config error, 3=connection error)

### Logging
```python
import logging
import sys

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
```

### Dependency Management
- Keep dependencies minimal for portability
- Use `pyproject.toml` with Poetry for dependency management
- Pin major versions but allow minor updates (e.g., `requests>=2.28,<3.0`)

### Docker Considerations
- Run as non-root user (UID 1000)
- Use multi-stage builds to minimize image size
- Copy only necessary files (use .dockerignore)
- Set PYTHONUNBUFFERED=1 for proper log streaming

### Security Practices
- Never hardcode secrets or credentials
- Support multiple authentication methods (managed identity, service principal, API keys)
- Use Azure Key Vault or similar for secret management when available
- Validate and sanitize all external inputs
- Use HTTPS for all API calls

### Testing
- Write unit tests for all business logic using `pytest`
- Always write unit tests
- Mock external API calls in tests
- Aim for >80% code coverage
- Include integration tests that can run against test endpoints

### Linting & Type Checking
- Always run linters after substantive edits.
- Use Ruff for linting and formatting fixes; prefer `ruff --fix` on staged/changed files.
- Use MyPy for type checking with the repo's `pyproject.toml` settings.
- Quality gate before completing a task:
    - Lint: Ruff passes (or fixes applied)
    - Typecheck: MyPy passes on `src/` and relevant tests
    - Tests: Pytest passes for affected modules
    - No new warnings/errors introduced by changes
-
Example quick checks (conceptually run by the assistant):
    - ruff check --fix src tests
    - mypy src tests

### Project Structure
```
project/
├── src/
│   ├── __init__.py
│   ├── config.py       # Configuration management
│   ├── client.py       # API client implementation
│   ├── poller.py       # Polling logic
│   └── utils.py        # Helper functions
├── tests/
│   ├── test_client.py
│   ├── test_poller.py
│   └── fixtures/
├── scripts/
│   ├── poll.sh         # Bash wrapper for polling
│   └── run-local.sh    # Local development runner
├── .env.example        # Example environment variables
├── requirements.txt    # Production dependencies
├── Dockerfile          # Container definition
└── README.md          # Usage documentation
```

### CLI Design
- Use `typer` for CLI parsing
- Support both flags and environment variables
- Provide --help with clear examples
- Include --debug flag for verbose output
- Support --dry-run for testing configuration

### Portability Checklist
- [ ] Works on Linux, macOS, and Windows (WSL)
- [ ] Runs in Docker containers
- [ ] Supports both local and cloud environments
- [ ] Handles different authentication methods
- [ ] Configurable via environment variables
- [ ] Graceful degradation when optional services unavailable
- [ ] Clear error messages for missing dependencies

## Example Implementation Pattern
```python
async def poll_api(
    endpoint: str,
    poll_interval: int = 5,
    max_attempts: int = None,
    timeout: int = 300
) -> dict:
    """
    Poll an API endpoint until completion or timeout.
    
    Args:
        endpoint: API endpoint URL
        poll_interval: Seconds between polls
        max_attempts: Maximum poll attempts (None for unlimited)
        timeout: Total timeout in seconds
        
    Returns:
        Final API response
        
    Raises:
        TimeoutError: If polling exceeds timeout
        APIError: If API returns an error
    """
    # Implementation here
```

## Documentation Requirements
- Include inline comments for complex logic
- Add README with quick start, configuration, and troubleshooting sections
- Document all environment variables and their defaults
- Provide example .env file
- Include Docker and local run instructions

## Template Management Guidelines

### Location & Packaging
- Place active (non-legacy) infrastructure or resource templates under `src/discovery_infra/templates/`.
- Use subdirectories per resource domain (e.g. `supercomputer/`, `workspace/`, `network/`, `storage/`).
- Keep legacy / deprecated templates only in `legacy/` – do not copy them into the package path unless migrated.
- Include all template files (json, yaml) in the built wheel by adding package data rules. Example (pyproject.toml):
    ```toml
    [tool.setuptools.package-data]
    discovery_infra = ["templates/**/*.json", "templates/**/*.yaml", "templates/**/*.yml"]
    ```

### Variant Strategy
- Use a single `template.json` as the base plus optional environment variants: `template.dev.json`, `template.prod.json`.
- Keep variant deltas minimal; prefer parameterization over full duplication.
- Document any required template parameters in a `README.md` co-located with the templates folder.

### Access Pattern
Use `importlib.resources` for runtime-safe access (works in packaged wheels and zipped installs):
```python
from importlib.resources import files

tmpl = files("discovery_infra").joinpath("templates/supercomputer/template.json")
data = tmpl.read_text(encoding="utf-8")
```
- Never rely on relative file paths (`../../`) from execution cwd.
- Avoid hardcoding absolute paths; always resolve through the package.

### Dynamic Parameter Injection
- Load template JSON as dict, then apply a substitution layer (e.g. string placeholders like `__LOCATION__`, `__PREFIX__`).
- Centralize substitutions in a helper: `render_template(name: str, params: dict[str, str]) -> dict`.
- Validate required placeholders: fail fast if any `__PLACEHOLDER__` tokens remain after render.

### Testing Templates
- Add unit tests that:
    * Load each template through `importlib.resources`.
    * Render with minimal params and assert required keys exist.
    * (Optional) JSON Schema validation if schema is available.
- Provide a fixture to supply common parameters (location, prefix, subscription id).

### Local / User Overrides
- Allow an override directory (e.g. `templates_local/`) outside the package for experimentation; never package it.
- Lookup order when loading: local override path (if configured) -> packaged template.
- Log which source was chosen at INFO level.

### Versioning & Changes
- Treat template changes as potentially breaking: bump project version when structure or required parameters change.
- Keep a brief CHANGELOG entry for template adjustments affecting downstream deployments.

### Security & Hygiene
- Strip secrets, keys, or credentials from templates; inject at runtime via parameters or environment variables.
- Avoid embedding large binary data; store such assets externally or generate them dynamically.

### Linting / Validation Automation
- Optional: add a CI step that loads & parses every template to guarantee JSON validity.
- Consider a lightweight schema (dict of required top-level keys) enforced in tests.

### Example Helper Skeleton
```python
from __future__ import annotations
import json
from importlib.resources import files
from typing import Any

TEMPLATE_ROOT = "discovery_infra"

def render_template(relative_path: str, params: dict[str, str]) -> dict[str, Any]:
        raw = files(TEMPLATE_ROOT).joinpath(f"templates/{relative_path}").read_text(encoding="utf-8")
        for k, v in params.items():
                raw = raw.replace(f"__{k.upper()}__", v)
        if "__" in raw:  # naive leftover check
                # Optionally implement a stricter regex scan
                raise ValueError("Unresolved placeholders remain in template")
        return json.loads(raw)
```

Follow these guidelines whenever adding or modifying infrastructure templates to ensure portability and consistent packaging.