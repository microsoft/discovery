# Starter Kit Authoring Guide

> **Audience:** Anyone authoring a starter kit for the Discovery catalog. Starter kits bundle one or more existing catalog agents into a deployable, opinionated workflow that customers can launch from Discovery Studio.
>
> **Scope:** Defining and submitting a starter kit via `kit.json`, with optional Markdown documentation and modest documentation images.

For agent authoring, see [`agent-authoring-guide.md`](./agent-authoring-guide.md).

---

## 1. Overview

A starter kit references one or more **agents that already exist in this catalog** and presents them as a single launchable experience in Discovery Studio. The kit contains metadata and may include supporting Markdown documentation — the agents it references must be authored separately.

Every kit lives under `starter-kits/<kit-name>/` and is described by a single `kit.json` file that conforms to [`docs/schemas/starter-kit-schema.json`](../schemas/starter-kit-schema.json).

---

## 2. Folder layout

```text
starter-kits/
└── drug-discovery/
  ├── kit.json
  ├── README.md                 # Optional
  └── media/                    # Optional; Markdown images only
    └── workflow.png
```

Besides `kit.json`, the kit folder may contain Markdown and local PNG, JPEG,
GIF, WebP, or inert SVG images. Each local image must be no larger than **1
MiB** and embedded by Markdown in the same kit folder. This includes the
Markdown in `kit.json`'s `longDescription`, for example
`![Workflow](media/workflow.png)`. Unreferenced images are rejected.

The structured `logo` and `screenshots` fields remain HTTPS URLs because they
feed catalog-card metadata; local images are documentation assets only.

The folder name must match `kit.json`'s `name` field.

---

## 3. Required top-level fields

| Field | Purpose |
|---|---|
| `name` | Kebab-case kit identifier; must match the kit folder name. |
| `version` | Semantic version (`MAJOR.MINOR.PATCH`). |
| `description` | One-line summary shown in catalog and CLI output. Max 200 characters. |
| `displayName` | Card title shown in Discovery UI. Max 80 characters. |
| `longDescription` | Markdown detail-view body (≥ 50 characters). |
| `author` | Maintainer `name`, `email`, and optional `url`. |
| `keywords` | Search terms (non-empty array). |
| `category` | One of `Biology`, `Chemistry`, `Physics`, `Silicon`, `Quantum`, `Materials`, `Neuroscience`. |
| `lifecycle` | `active` or `archived`. |
| `agentRefs` | Agents that make up the kit (see §5). |

Optional top-level fields include `$schema` (relative path to the schema for editor IntelliSense — recommended), `license` (SPDX identifier), `homepage`, `repository`, `featureFlag`, `logo` (HTTPS URL), `screenshots` (HTTPS URLs), `websiteURL`, `privacyPolicyURL`, `riskProfile`, and `party` (`1p` / `3p` — drives the contribution-source PR label). Local documentation images belong in Markdown, not in `logo` or `screenshots`.

Active kits must also include `samplePrompts`.

---

## 4. Lifecycle

| Value | Meaning |
|---|---|
| `active` | The kit is published and surfaced in Discovery Studio. All `agentRefs[].ref` paths must exist in the agent registry. `samplePrompts` is required. |
| `archived` | The kit is kept for history but not surfaced. Missing agent refs become informational warnings instead of failures. |

Newly added kits must be created with `lifecycle: active`.

---

## 5. Agent references

`agentRefs` lists every agent used by the kit. Exactly one entry must have `role: primary` and `required: true` — that entry is the launch agent.

```json
"agentRefs": [
  {
    "ref": "agents/aizynthfinder",
    "role": "primary",
    "required": true,
    "description": "Plans retrosynthetic routes from a target SMILES."
  },
  {
    "ref": "agents/chembl",
    "role": "supporting",
    "required": false,
    "description": "Queries ChEMBL for bioactivity data."
  }
]
```

**Constraints**

- Each `ref` must point to an existing catalog agent under `agents/<agent-name>` (no duplicates inside the array).
- For `lifecycle: active` kits, every `ref` must resolve to an agent that the registry rebuild can see (i.e. the agent folder has a valid `metadata.yaml` with a `name`).

---

## 6. Sample prompts

Active kits must provide at least one `samplePrompts` entry. The starter-kit deployer uses the first prompt for post-deploy validation, so write each prompt as an executable workflow specification — not just a scientific goal. Include expected file formats, naming conventions, and handoff expectations so the kit's converged agent can pass real outputs from one tool into the next.

```json
"samplePrompts": [
  {
    "id": "sp-1",
    "title": "Cross-query bioactivity databases for a target",
    "prompt": "I'm working on an EGFR inhibitor programme. Retrieve candidates, save the merged candidate table as egfr_candidates.csv, save structures as egfr_structures.sdf, and use those exact returned files as input to the ranking step.",
    "difficulty": "intermediate",
    "expectedOutput": "egfr_candidates.csv, egfr_structures.sdf, ranked_egfr_candidates.csv, and a report listing exact file paths or resource URIs returned by each step and consumed by the next step."
  }
]
```

`difficulty` may be `beginner`, `intermediate`, or `advanced`.

---

## 7. Risk profile (optional)

```json
"riskProfile": {
  "requiresExternalCompute": true,
  "dataResidency": "user-managed Azure subscription"
}
```

Only `requiresExternalCompute` and `dataResidency` are accepted today. Do not include data-tier or credential fields.

---

## 8. Minimal example

```json
{
  "$schema": "../../docs/schemas/starter-kit-schema.json",
  "name": "drug-discovery",
  "version": "1.0.0",
  "description": "Accelerate small-molecule drug discovery with AI-driven retrosynthesis and bioactivity screening.",
  "displayName": "Drug Discovery",
  "longDescription": "# Drug Discovery\n\nPlan synthesis routes, predict properties, and query bioactivity data.",
  "author": {
    "name": "Microsoft",
    "email": "discovery-catalog@microsoft.com",
    "url": "https://github.com/microsoft/discovery"
  },
  "license": "MIT",
  "keywords": ["drug-discovery", "retrosynthesis", "bioactivity"],
  "category": "Chemistry",
  "homepage": "https://github.com/microsoft/discovery/tree/main/starter-kits/drug-discovery",
  "party": "1p",
  "lifecycle": "active",
  "agentRefs": [
    {
      "ref": "agents/aizynthfinder",
      "role": "primary",
      "required": true,
      "description": "Plans retrosynthetic routes."
    }
  ],
  "samplePrompts": [
    {
      "id": "sp-1",
      "title": "Assess synthetic accessibility",
      "prompt": "Can aspirin be synthesised from commercially available starting materials? Save the retrosynthetic route as routes.json and produce a one-paragraph human summary.",
      "difficulty": "beginner",
      "expectedOutput": "routes.json containing the planned retrosynthetic route and a one-paragraph summary."
    }
  ],
  "riskProfile": {
    "requiresExternalCompute": true,
    "dataResidency": "user-managed Azure subscription"
  }
}
```

---

## 9. Submitting a pull request

```bash
# 1. Fork https://github.com/microsoft/discovery in the GitHub UI.
git clone https://github.com/<your-org>/discovery.git
cd discovery
git remote add upstream https://github.com/microsoft/discovery.git
git fetch upstream && git merge upstream/main

# 2. Create your kit folder
git checkout -b add-drug-discovery-kit
mkdir starter-kits/drug-discovery
# … create kit.json and optional Markdown documentation assets …

# 3. Open the PR
git add starter-kits/drug-discovery/kit.json
git commit -m "feat: add drug-discovery starter kit"
git push origin add-drug-discovery-kit
```

The automated PR review will validate:

- `kit.json` conforms to `starter-kit-schema.json`.
- `name` equals the parent directory name.
- Exactly one `agentRefs[]` entry has `role: primary` and `required: true`.
- No duplicate refs.
- For active kits, every `ref` resolves to an existing agent.
- The kit folder contains only `kit.json`, Markdown, and compliant Markdown images.
- For active kits, `samplePrompts` is non-empty.
- Newly added kits have `lifecycle: active`.
- Kit `name` is globally unique across the catalog.

Read the required checks and source run logs, then address findings in follow-up
commits. **PR Review Report** publishes diagnostic labels and comments
asynchronously; rule feedback may be inline or summarized. Missing comments or a
`pr-validation-passed` label do not replace the status rollup. GitHub requests
CODEOWNERS review independently of labels. All required checks, at least one
CODEOWNERS approval, and other configured review requirements must be satisfied
before a maintainer merges or enables GitHub's native auto-merge.

Fork runs may require maintainer authorization. Resolve merge conflicts before
`pull_request` checks can run. See
[workflow troubleshooting](../validation-workflow-testing.md#troubleshoot-missing-or-stale-feedback)
if feedback is absent.

### Agent removal impact

When agent paths change, **Check Agent Removal Impact** compares the trusted base
registry with valid PR-head metadata and checks the PR's active starter kits.
Removing or renaming an agent still required by an active kit fails the gate.
Optional references and archived/deleted kits do not block removal.

Resolve the impact in the same PR by replacing required refs with valid agents,
making a reference optional where the kit schema permits, or archiving/deleting
the affected kit. Other kit schema checks still apply.

For non-fork PRs only, a maintainer may apply `starter-kit-impact-approved` and
rerun the removal check. The gate must verify the latest label applier's current
write/maintain/admin permission using read-only API requests; unavailable
authorization does not grant an override. Applying the label alone does not
trigger a run. Fork PRs must fix the kit references instead.

The required gate is independent of diagnostic publication. Blocked/error
results may receive summary comments from **PR Review Report**; success/no-op
results need no removal comment. Feedback cannot approve the PR, change review
state, or modify PR Review labels.

---

## 10. Schema reference

| Schema | Validates | Path |
|---|---|---|
| `starter-kit-schema.json` | Every `kit.json` | [`docs/schemas/starter-kit-schema.json`](../schemas/starter-kit-schema.json) |
| `registry-schema.json` | The auto-generated `.auto-registry/agent-registry.json` that `agentRefs[].ref` resolve against | [`docs/schemas/registry-schema.json`](../schemas/registry-schema.json) |
| `starter-kit-registry-schema.json` | The auto-generated `.auto-registry/starter-kit-registry.json` aggregate of every `kit.json` (with `availability`, `missingAgents`, `kitPath`, and per-ref `agentMeta` enrichments) | [`docs/schemas/starter-kit-registry-schema.json`](../schemas/starter-kit-registry-schema.json) |
