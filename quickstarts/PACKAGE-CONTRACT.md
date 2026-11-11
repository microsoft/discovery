# QuickStart Scenarios package contract

This is a **proposed repository packaging contract**, version 1, not a
Discovery scenario catalog API. Maintainers must approve the new top-level
area. Existing agent, starter-kit and skill contracts remain unchanged.

The earlier local Solution Validator prototype mixed packaging checks with
scientific grading and required YAML/JSON Schema dependencies. This skeleton
retains its useful identity/version, prompt, surface and evidence distinctions
but uses a small JSON inventory and standard-library-only packaging helper.
It does not introduce another scientific grader or import that unvalidated
prototype as a trusted repository check.

## Layout

Each of `siphy`, `biopharma`, `cms`, and `bookshelf` contains `scenario.json`,
`README.md`, `profile.md`, `assets.json`, and an explicit file inventory.
Use the display heading **QuickStart Scenarios**, keeping filesystem names
lowercase. The single canonical runner lives in
[`skills/quickstart-runner`](../skills/quickstart-runner/SKILL.md).

## scenario.json

Required fields:

- `schemaVersion`: integer `1`.
- `id`: matches its folder (`siphy`, `biopharma`, `cms`, or `bookshelf`).
- `title`, `vertical`, `version`: nonempty strings; version uses `0.1.0` form.
- `status`: `draft` or `ready`. `ready` is not inferred by a checker.
- `guide`: `README.md`; `profile`: `profile.md`; `assetManifest`: `assets.json`.
- `files`: exhaustive, unique, forward-slash relative paths of shipped text
  files within this scenario, including `scenario.json` itself. No directories,
  links, absolute paths, `..`, caches, binaries or hidden session state.
- `prompt`: object with `path` (relative file), `sha256` (64 lowercase hex),
  `status` (`owner-supplied` or `proposed`), and `source` (sanitized provenance).
  Prompt digests normalize UTF-8 BOM and CRLF to UTF-8/LF, with all other
  whitespace preserved. Asset and staged-file digests are exact raw-byte hashes.
- `components`: array of `{id, kind, status, repository, revision, path, note}`.
  `status` is `repository`, `host`, or `unpublished`. Repository references use
  `repository: "microsoft/discovery"`, a 40-character commit SHA and an actual
  repository-relative `path`. Missing components use `path: null` and
  `revision: null`, with a blocker; never pretend a similarly named agent is
  the owner component. Host capabilities likewise use null path/revision.
- `blockers`: array of `{id, detail}`; unresolved source, rights, owner,
  runtime and publication gaps are explicit. Drafts must have at least one.
- `validation`: `{package: "not-run", workflow: "not-run", scientific:
  "not-run", evidence: null}` initially. Do not copy previous-run badges.
  Historical observations belong in the guide, explicitly scoped. The
  `ready` state requires each status `passed` and a shipped evidence path.

The helper validates structure, references, prompt hashes and link targets.
Its successful exit is **package integrity**, not workflow/scientific success.
`validate --release` additionally fails for drafts, open blockers, unpublished
components, proposed prompts, unresolved required assets and missing evidence.
An evidence document's presence does not independently prove its assertions.

## assets.json

An array of `{id, role, required, delivery, path, url, bytes, sha256,
license, redistribution, note}` objects. Every input, archive, corpus and
supporting integrity attachment is accounted for, including withheld items.

- `delivery`: `included`, `download`, or `unpublished`.
- `path`: scenario-relative file for included assets; otherwise a safe relative
  name expected in the user-selected asset directory. Never a personal path.
- `url`: HTTPS public acquisition URL for `download`, otherwise null. No
  credentials, query strings, expiring links or internal SharePoint URLs.
- `bytes` / `sha256`: exact source metadata when known, otherwise null for
  unpublished assets. Included/download assets require both and hash checking.
- `redistribution`: `documented` or `pending`; preserve the source licence and
  attribution separately from this repository's code licence. Download does
  not mean licence-free; verify publisher terms and third-party exclusions.
- `required`: boolean. An optional item never silently becomes a prerequisite.

Local byte verification is permitted even for unpublished inputs; it is not
permission to upload, redistribute, ingest, deserialize or execute them.
The helper does not download assets. It verifies pre-acquired local files
only, and it never extracts archives.

## Paths, staging and provenance

The offline staging helper copies the explicitly inventoried text packages,
shared documentation, repository code licence and runner into a **new
destination**. All four guides
are retained so their navigation still works; only one scenario is selected.
It does not copy agent/tool implementations. Components remain resolved at
pinned public repository locations for later approved setup. Repository
validation checks their source paths locally; a staged review bundle is not
a repository checkout and does not claim that those components are installed.

An activation shim under `.github/skills/quickstart-runner/` delegates to the
single canonical runner copied under `skills/quickstart-runner/`. It does not
grant tools or establish Discovery runtime activation. A generated selection
record names the selected scenario and draft state; it contains no approvals.
Verify discovery in a new chat; a supported explicit file-load fallback is
documented in the getting-started guide. No personal skill directory is read.

Staging refuses existing destinations, unsafe paths and symbolic links. Draft
staging requires `--allow-draft`; that flag authorizes inspection/staging only,
never installs, indexing, agent calls or scientific computation. No live test
is started by validation or staging. Keep environment readiness, completed
workflow and scientific acceptance separate in every report.

Source-to-destination ownership is described in
[`SOURCE-INVENTORY.md`](SOURCE-INVENTORY.md). Local authoring paths and private
evidence remain outside the distributable package. A clean project must not
receive old sessions, credentials, virtual environments, run outputs or a
prebuilt index. Maintain hashes for retained baselines and never relabel them
as newly computed results.