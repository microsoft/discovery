# Test results

Run on **2026-11-13** (script, validators, browser, Copilot CLI) and **2026-11-16** (Discovery App,
and an independent check of the pushed commit) on one Windows machine, with Python 3.12.10, Node 22
and Microsoft Edge (headless) for the browser checks. The skill runs used synthetic datasets. The
independent check also used works returned by the public OpenAlex REST API as test input, not the
Discovery OpenAlex connection. No Springer-specific data, prompts or assets were used, and no live
Discovery OpenAlex connection was used.

## What was checked

| Check | Result |
| --- | --- |
| Unit tests (`python -m unittest discover -s skills/evidence-comparison-dashboard/tests`) | **17 passed**: missing-data policy, input rejection, HTML escaping, CSP, tamper detection, nothing written on rejected input |
| Reference validator (`agentskills validate skills/evidence-comparison-dashboard`, PyPI package `skills-ref` 0.1.1) | **Valid skill** |
| Catalog validator (`validate_pr.py` on the 9 skill files) | Passed, 0 failures, 0 warnings |
| Prose spellcheck (`spellcheck_prose.py`) | 0 warnings |
| Clean-directory run of the bundled script, both samples | Built and `verify` OK for `sample-evidence.json` and for `sample-catalysis.json` with `--missing-token NA`; a warning listed the one omitted field |
| Tampered page | `verify` failed (exit 1) when a record id in the HTML was changed |
| Rejected input (record without `source_url`) | Exit 2, the problem listed, no output file written |
| Real browser (Edge, headless) on the sample page | Search, per-field filters, "missing" filter, real `0`, real `false`, "only complete rows", row counts, and CSP all behaved as expected; no console or CSP errors |

## Natural-prompt runs in a clean workspace

Host: GitHub Copilot CLI 1.0.110, **not** the Discovery runtime. Each run was a new session in a
clean folder containing only `.github/skills/evidence-comparison-dashboard/` (a byte-identical copy
of this skill) and a `data/` folder. The skill was never named in the prompt.

| Prompt (paraphrased) | Dataset | Observed |
| --- | --- | --- |
| "Make me a filterable comparison view with a source link on every row, mark missing values as not reported, say how many are missing per field and whether the view matches my file" | A 5-row CSV with different columns than the samples, including blanks, a real `0`, `false`, and the literal `N/A` | Skill loaded; dashboard built; `verify` OK. An independent comparison of the evidence file against the CSV found **0 mismatches** (5 records), and 6 blank cells were marked missing. `0`, `false` and `N/A` stayed values |
| "Put these into a side-by-side comparison with a source link on every row; don't guess anything missing" | A CSV where one row has no source link | Skill loaded; **stopped**, named the row, built nothing, and asked for a link or permission to exclude it. Ran twice with the same outcome |
| "Pull the five most-cited recent works from the OpenAlex connection and build a comparison dashboard" | None (no OpenAlex connection in that session) | Skill loaded; **stopped** and reported that no OpenAlex tool was available. It did not use web search, public APIs, memory, or the sample files, and wrote no records. Ran twice with the same outcome |

Because each run was a fresh session reading the same files, this shows that file-based skill
loading persists across new sessions in that host. It says nothing about other hosts.

## Discovery App runs (2026-11-16)

Host: **Discovery App 0.0.2 (stable, Windows)**, default Discovery agent, model GPT-6.1 Sol,
signed in with GitHub. The workspace was a clean folder holding only
`.github/skills/evidence-comparison-dashboard/` (a byte-identical copy of this skill) and a `data/`
folder. Nothing was attached to the chat, and the skill was never named in a prompt. Every tool
request that needed permission was reviewed before it was allowed.

| Prompt (paraphrased) | Dataset | Observed |
| --- | --- | --- |
| "Build an offline comparison dashboard from this CSV: filter by lab type and encapsulation, link each row to its source, show blanks as missing, save under outputs, double-check the numbers against the CSV" | The 5-row perovskite CSV (blanks, a real `0`, `false`, literal `N/A`) | First attempt: the skill was loaded, then the agent escalated to the App's Scientific Reasoning tool (`clio-start`) and, after about 10 minutes, asked for consent to a longer run. We denied it; the turn ended with no answer and no dashboard. |
| Same prompt plus "do it directly in this chat rather than starting a long investigation" | Same CSV | **Built and verified in about 2 minutes.** The agent ran `build` then `verify` from the skill's own script. An independent check afterwards found **0 mismatches** across 5 records, 5 links and 30 cells, and the app's `verify` printed OK. The 6 blank cells show as not reported; `0`, `false` and `N/A` stayed values. |
| "Build an offline comparison dashboard from this CSV, every row linked to its source, blanks as missing" | A CSV where one row has no source link | **Stopped.** Named the row (MAT-2, CSV line 3), asked whether to exclude it or get a URL, and wrote nothing. |
| "Pull the 10 most-cited 2024 papers on perovskite solar cell stability from OpenAlex and build a dashboard" | None (no OpenAlex connection in the workspace) | Skill loaded and `references/openalex-mapping.md` read, then the agent tried its built-in `web_fetch` against the public OpenAlex API. We skipped that request twice. **No records were invented and no file was written**, but the turn ended with no message to the user. |

What the App's own session log shows (`.discovery/copilot-chat/session-state/*/events.jsonl`):

- In all four sessions the first tool call was `skill` with `evidence-comparison-dashboard`, and the
  log has a `skill.invoked` event with the skill's `SKILL.md` as content. The delivered skill
  context had the same SHA-256 in every session.
- The skill was read from an App-managed copy, not from the workspace folder: the App mirrors
  `.github/skills/<name>/` into its own storage
  (`...\globalStorage\ms-discovery.studio\local-chat-project-skills\<workspace hash>\<name>\`).
  The mirror appeared within seconds of the App starting, before any chat, held all 9 files
  byte-identical to the source, and was rewritten again when later sessions started (still
  identical). Edits to the workspace copy therefore reach new sessions.
- The agent's shell ran `python --version` and `node --version` and got **Python 3.12.10** and
  **Node v22.23.4**, the same versions as this machine's own installs. We saw no sign that the App
  bundles Python, so on this machine it was host-provided. A machine without Python was not tried.
- Persistence across new chats: three further new sessions after the first each loaded the skill
  the same way. Persistence across an App restart was not tested.
- Permissions: the agent asked for permission for every read of the skill's own bundled files, for
  shell commands, and for the web fetch (4 to 11 prompts per session). Nothing was auto-approved by
  the App.
- Output location: the agent saved its files under
  `sessions/<session id>/perovskite-comparison/outputs/` inside the workspace, not under a
  top-level `outputs/` folder.
- The App's "AI capabilities" view listed Agents, Bookshelves and Tools. It has no skills list, so
  a loaded skill can only be confirmed from the session log or by observing the behavior.

## Independent check of the pushed commit (2026-11-16)

Made from a fresh shallow clone of the pushed branch (commit `2834ede`), using only the README
commands, with test harnesses that are not part of this folder. The clone's nine skill files were
byte-identical to the local copy.

| Check | Result |
| --- | --- |
| README quickstart, verbatim, on system Python 3.12.10 | `build` then `verify` OK for `sample-evidence.json`; the catalysis sample also built and verified OK |
| `agentskills validate`, `validate_pr.py`, `spellcheck_prose.py`, `pytest .github/tests/test_skill_contributions.py`, unit tests | All passed (0 failures; 19 pytest tests; 17 unit tests). The unit tests pass on plain Python with no extra packages installed |
| Real works from the public OpenAlex REST API (125 works, three queries: 2024 solid-state electrolytes, 1998, 2003) | `build` and `verify` OK. Compared with the raw API response, **0 mismatches** in links, labels or cell text. Blank venue, first author and DOI cells were flagged as not reported (7, 5 and 40); 48 real `0` citation counts stayed values; 32 non-ASCII titles were preserved |
| Edge (headless) on the sample page and the three real pages | "Showing N of N records" appears (the page script writes it; it is not in the static HTML). On the three real pages every search and filter count equalled the count computed from the raw API response. No console or CSP errors on any page |
| Hostile text (script and image tags, quotes, `&`, newlines, emoji, a right-to-left override character in titles, labels, field names and values) | Built and verified OK. In Edge nothing executed, only one `<script>` element existed, no extra elements appeared, and every filter option showed exactly the matching rows |
| Rejected input (34 cases: `javascript:`, `data:`, `file:` and scheme-less links, missing or duplicate ids, empty records, `NaN`, duplicate JSON keys, nested values, invalid UTF-8) | Every case exited non-zero with a message, no traceback, and no output file. A UTF-8 byte order mark is also rejected with a clear message (see Known limits) |
| `verify` on a tampered page (value, zero marked missing, missing value filled in, link, label, deleted row, added row, reordered input, edited input) | Failed every time |
| 5,000 synthetic records | `build` 0.2 s, `verify` 0.5 s, 2.6 MB page; one search keystroke took 3 ms in Edge |
| OpenAlex hosted MCP endpoint, unauthenticated request | `401` with an OAuth challenge and scope `openalex:query` only |

## Live MCP end-to-end (2026-11-16)

Real output from the hosted OpenAlex MCP, produced by the deployed OpenAlexResearchLandscape agent
in a Discovery Studio dev project, was fed to the skill in two clean workspaces. Prompts were
natural requests for a searchable, filterable dashboard with source links; neither named the skill.
Both were run with the Copilot CLI (not the Discovery App) and the skill loaded in both.

The source was a 2-call `search_works` run: 10 of 5,896 results, all 2026 works. Three had no DOI,
four had no open-access URL, three had no FWCI, and all ten had a real citation count of `0`.

| Check | Result |
| --- | --- |
| Run 1: the raw MCP JSON as input | An independent script (its own HTML parser, not the skill's code) found all 110 value cells equal to the raw MCP values, row order and links equal, 10 absent values flagged not reported, and 17 real `0` values kept as values. `verify` OK |
| Run 2: the agent's chat table as input | All 60 dashboard cells equal the chat table, and the chat table equals the raw MCP values for title, year, venue, citations, URL, DOI and first author. `verify` OK |
| Pages in Edge (headless) | Both passed: one `<script>`, no console or CSP errors, links open safely, filter options match their rows, search is literal |
| Input files and skill copies | Unchanged after the runs |
| Rebuild of each page from the saved input | Only two lines differ from the agent's page: the build-time metadata tag and the visible "built" line |

Observations that came out of this run (also reflected in the docs):

- **Consent lapses.** The OAuth grant given four days earlier had expired. The agent listed no tools,
  returned a consent request, and stopped without inventing data. The first call also failed once
  with a generic `foundry_server_error` before the consent request appeared on retry. Consent links
  were valid for about 15 minutes.
- **Query error.** A `search_works` query with a wildcard was rejected unless `mode` was `exact`.
  The agent reported the error, built nothing, and succeeded on an allowed retry.
- **Placeholder text.** In run 2 the cells `not provided` stayed as literal text and counted as
  reported (5 cells, including the 3 missing DOIs, so DOI coverage read 10/10). The nested agent said
  so in its summary. The skill now tells the agent to ask the user, or to disclose this.
- **Provenance.** With a saved file as input the agent recorded `source_tool` as the file name and
  left `retrieved_at` empty. The skill now asks for the real tool name when it is known.

- Discovery Studio (cloud) runtime, and Discovery App 0.0.4 (the version the Discovery team
  described). Everything above is 0.0.2.
- Persistence across an App restart, and a machine without Python.
- A live OpenAlex connection feeding the skill **inside the Discovery App or Studio**. The live MCP
  run above used the Copilot CLI to run the skill; the App run in 2026-11-16 covered only the case
  with no connection, and it showed that the agent will reach for its web fetch tool when
  permission is granted, which the skill's text does not address.
- The Discovery runtime's behavior when the same skill is attached manually instead of discovered.
- Python 3.9 to 3.11 (the code uses only syntax valid on 3.9) and browsers other than Edge.

## Known limits

- `verify` proves the page matches the input file. It cannot prove the input file matches the
  original source; the skill requires building the input programmatically from saved tool output.
- `verify` checks the table rows only (record order, links, labels, cell text, missing flags) and
  the input hash. In the independent check it did **not** notice edits to the page script, the
  Content-Security-Policy, the styles, the filter dropdown labels, the coverage table, the title,
  or the dataset and synthetic-data banner. A page that passes `verify` should still come from the
  script, not from a hand-edited file.
- Filter dropdowns exist only for fields with 2 to 12 distinct values (or one value plus missing
  ones). Fields such as titles, DOIs and authors are searched with the search box.
- The build rejects a UTF-8 byte order mark. Windows PowerShell 5.1 `Set-Content -Encoding UTF8` and
  `Out-File -Encoding utf8` write one; save the input without it.
- Filters need JavaScript. Without it all rows are still shown.
- In the CSV runs the assistant carried every value as the original text, so no number or date was
  converted. The skill's instructions ask for this but the script cannot enforce it.
