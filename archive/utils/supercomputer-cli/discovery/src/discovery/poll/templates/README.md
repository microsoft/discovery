# discovery_poll Templates

This directory holds templates specific to polling workflows (e.g. sample payloads or operation definitions) that need to be shipped with the package.

## Conventions
- Use JSON for API payload examples: `<name>.json`.
- Keep environment-specific variants minimal (e.g. `payload.dev.json`, `payload.prod.json`).
- Prefer parameter placeholders like `__PROJECT__`, `__LOCATION__`, `__WORKSPACE_URL__`.
- No secrets or credentials – inject at runtime.

## Access Pattern
```python
from importlib.resources import files

payload_text = files("discovery_poll").joinpath("templates/sample_payload.json").read_text(encoding="utf-8")
```

## Adding New Templates
1. Create the base file inside this folder (or a subfolder if grouping needed).
2. Add any variants with a suffix before the extension (e.g. `sample_payload.dev.json`).
3. Update or create tests to load and validate JSON parses.
4. Bump version if template structure changes for downstream consumers.

## Local Overrides
Optionally support a user override directory (not yet implemented here) like `poll_templates_local/` searched before packaged templates.


## TODO:
- Add gpu, cpu, mem, and image name selection into tool run
    - Use override. 
- print out tool def before asking to submit
- print out tool run before submitting if verbose
- Randomize ANF mount when starting job
- List out blobstore containers and selection
    - Q: How do you prevent concurrent access?
        - Mount using blobfuse under /archive
        - Mount ANF under /scratch 