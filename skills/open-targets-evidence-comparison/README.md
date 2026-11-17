# Open Targets evidence comparison

This skill creates a self-contained, filterable HTML comparison from a bounded
evidence sample. It preserves identifiers, provenance, source links and
uncertainty; it is not a clinical recommendation or a target ranking.

## Use

Install the entire skill directory in a host's skill location and ask for an
evidence comparison. For data not already supplied, the host needs an
authorized Open Targets agent and connection; follow its approval requirements.
The renderer itself makes no network requests and requires Python 3.9 or later
with its standard library.

The [input contract](references/input-contract.md) describes the JSON format.
From the skill directory, a synthetic example can be rendered with:

```text
python scripts/render.py --input tests/example.json --output report.html
```

The example contains fictional data, not Open Targets results. The renderer
refuses to overwrite existing files.

## Tests

From the skill directory, run:

```text
python -m unittest discover -s tests -p test_renderer.py
```
