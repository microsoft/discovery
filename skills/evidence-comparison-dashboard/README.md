# evidence-comparison-dashboard

Builds a self-contained, filterable comparison page from sourced evidence records. Every row links
to its source, missing values are shown as "not reported" (never guessed), and a `verify` command
checks that the page still shows exactly the input values.

The skill is the instructions in [SKILL.md](SKILL.md) plus one standard-library Python script. It
does not search for data, call the network, or need credentials. Pair it with a research agent such
as the OpenAlexResearchLandscape agent: the agent finds sourced records, this skill compares them.

## Try it in two minutes (no Discovery needed)

Requires Python 3.9 or newer. The Discovery team says Python comes with Workbench. In the Discovery
App 0.0.2 the agent's shell found `python` on our test machine, but it was the same version as the
machine's own install, so treat it as provided by the host rather than bundled. Check
`python --version` in the agent's shell first: if the agent cannot run Python, the skill cannot
build or verify a dashboard. From the repository root:

```sh
python skills/evidence-comparison-dashboard/scripts/build_dashboard.py build \
  skills/evidence-comparison-dashboard/assets/sample-evidence.json --out dashboard.html
python skills/evidence-comparison-dashboard/scripts/build_dashboard.py verify \
  skills/evidence-comparison-dashboard/assets/sample-evidence.json dashboard.html
```

Open `dashboard.html` in a browser. Expected: "Showing 6 of 6 records", a search box, filters,
a source link on each row, and `OK` from `verify`. A second, different synthetic dataset is in
`assets/sample-catalysis.json` (use `--missing-token NA` with it).

Do not commit generated `.html` files: the catalog file-type policy does not allow them. They are
created on demand.

## How it differs from a general report skill

A skill that writes an HTML report from session data can make a good-looking page, but nothing
checks it afterward. This skill adds a fixed missing-data policy, a required source link on every
row, a build manifest with the input hash, and a `verify` step that fails if the page no longer
matches the input.

## Make it available to an agent

The repository does not document how a Discovery runtime installs a skill, and the catalog
`metadata.yaml` has no `associated_skills` field. Do not assume that adding this folder to the
catalog connects it to an agent.

| Route | Status |
| --- | --- |
| Run the script directly (above) | Verified |
| Copy the folder to `.github/skills/evidence-comparison-dashboard/` in a project workspace so the host discovers it | **Verified in two hosts.** GitHub Copilot CLI: new sessions in a clean workspace loaded it and triggered it from natural prompts without naming it. Discovery App 0.0.2 (Windows): the App copied the folder into its own storage at startup, and the default agent loaded it in every new chat from natural prompts, built a dashboard, and ran `verify`; the session log records the `skill.invoked` event. The App asks permission for each read of the skill's files, and it has no skills list, so confirm loading from the session log or behavior. Not verified in the Discovery Studio runtime, in App 0.0.4, or across an App restart. If the agent starts a long Scientific Reasoning run instead, add "do this directly in this chat" to the request |
| Attach [SKILL.md](SKILL.md) and the `scripts/` folder to a chat and ask the assistant to follow it ("manual skill loading") | Not yet verified in the Discovery runtime |

Whichever route you use, record which one it was. Results from manual loading must not be reported as
automatic discovery.

## Use

Ask in natural language, for example: "Compare these studies side by side with links to each
source and show which values are missing." The assistant should build an input file from real tool
output, run `build` and then `verify`, and report coverage and any sources that failed.

## What `verify` proves, and what it does not

- It proves the page shows the input file's record order, source links, labels and cell text, with
  missing values flagged exactly per the policy, and that the input file has not changed since the
  build (SHA-256).
- It does **not** prove the input file equals the original source's output. Build the input
  programmatically from saved tool output rather than retyping it, and keep `source_tool` and
  `retrieved_at` on each record.

## Behavior when a source is unavailable

If a connection asks for consent, errors, or returns nothing, the assistant stops for that source
and reports it. It must not create records from memory. It can continue with a user-supplied file
if you agree, and that file is labelled as the provenance.

## Tests

```sh
python -m unittest discover -s skills/evidence-comparison-dashboard/tests
```

The tests cover the missing-data policy, input rejection, HTML escaping, the Content-Security-Policy,
and tamper detection. They were run on Python 3.12; the code uses only Python 3.9-compatible
syntax but has not been run on 3.9. The full record, including what was not tested, is in
[TEST_RESULTS.md](TEST_RESULTS.md).

## Provenance and license

The sample datasets are synthetic, dedicated to the public domain (CC0-1.0), and use `example.org`
source links. They contain no Springer-specific or other third-party data, prompts or assets. The
skill is released under the MIT license, as declared in its frontmatter.
