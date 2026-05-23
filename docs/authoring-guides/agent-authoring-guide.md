# Agent Authoring Guide

> **Audience:** Anyone authoring an agent for the Discovery catalog — Microsoft engineers and external contributors alike. Both use the same submission flow; the only difference is that Microsoft-authored content may set `publisher.party: 1p` while third-party content uses `publisher.party: 3p`.
>
> **Scope:** Defining and submitting **prompt agents** (`kind: prompt`). Only prompt agents are accepted in this repository.

For starter-kit authoring, see [`starter-kit-authoring-guide.md`](./starter-kit-authoring-guide.md).

---

## Table of contents

1. [Overview](#1-overview)
2. [Before you start](#2-before-you-start)
3. [Folder layout](#3-folder-layout)
4. [`metadata.yaml`](#4-metadatayaml)
5. [`agent.yaml`](#5-agentyaml)
6. [Tools (optional)](#6-tools-optional)
7. [`README.md`](#7-readmemd)
8. [Submitting a pull request](#8-submitting-a-pull-request)
9. [Schema reference](#9-schema-reference)

---

## 1. Overview

This repository is the canonical metadata catalog that powers Microsoft Discovery. Every agent is validated, reviewed, and published through this repo before it is surfaced to customers in Discovery Studio. Agent code, container images, and model weights live in your own infrastructure; you contribute **metadata + documentation** here.

The catalog uses a single, flat layout: every agent lives under `agents/<agent-name>/` regardless of who authored it. Whether the agent is from a Microsoft team or an external partner is captured by the optional `publisher.party` field inside `metadata.yaml`.

---

## 2. Before you start

- [ ] Confirm your agent is a **prompt agent** (`kind: prompt`). Workflow and hosted-container agents are not currently accepted.
- [ ] You have access to a model deployment your agent will use (typically an Azure AI Foundry deployment).
- [ ] Your proposed agent name is unique across `agents/`.
- [ ] You have a fork of this repository and have signed the Microsoft CLA when prompted (the CLA bot will guide you on your first PR).
- [ ] You have a support URL and contact email ready.

---

## 3. Folder layout

```text
agents/
└── <agent-name>/
    ├── metadata.yaml       ← Required
    ├── agent.yaml          ← Required
    ├── README.md           ← Required
    └── tools/              ← Optional; only if your agent uses custom containerised tools
        └── <tool-name>/
            ├── tool.yaml
            └── Dockerfile
```

**Folder-name rules**

- Kebab-case (`a-z`, `0-9`, `-`).
- Maximum 64 characters.
- Must equal the `name:` value inside `metadata.yaml`.
- Must be unique across `agents/`.

---

## 4. `metadata.yaml`

`metadata.yaml` is the discovery contract for your agent. It drives the agent's appearance in Discovery Studio and its entry in `.auto-registry/agent-registry.json`.

```yaml
name: clinical-summary-agent          # Required — kebab-case, must match the folder name
type: agent                           # Required — must be 'agent'
version: 1.0.0                        # Required — semantic version: MAJOR.MINOR.PATCH

associated_tools:                     # Optional — list of paths to each tool sub-folder under this agent
  - agents/clinical-summary-agent/tools/clinical-summary

associated_agents:                    # Optional — paths to other agents this one depends on at runtime
  - agents/another-agent

publisher:
  name: Contoso Legal Tech            # Required — display name of the team or company
  contact: support@contoso.com        # Required — valid email
  support_url: https://contoso.com/support       # Required — HTTPS URL
  party: 3p                           # Optional — '1p' for Microsoft, '3p' for third-party (drives PR labelling)

description: >                        # Required — up to 500 characters
  Summarises clinical notes into structured SOAP format. Supports English-language
  input from US hospital systems.

tags:                                 # Required — at least one lowercase kebab-case tag
  - healthcare
  - clinical
  - summarisation

supported_regions:                    # Optional — omit if globally available
  - eastus
  - swedencentral

compliance:                           # Optional — include only if certified
  hipaa: true
  soc2: false
```

**Field reference**

| Field | Required | Notes |
|---|---|---|
| `name` | ✅ | Kebab-case; must equal the folder name. |
| `type` | ✅ | Always `agent`. |
| `version` | ✅ | SemVer (`MAJOR.MINOR.PATCH`). Bump on meaningful change. |
| `publisher.name` | ✅ | Display name of the publishing team or company. |
| `publisher.contact` | ✅ | Valid email address. |
| `publisher.support_url` | ✅ | HTTPS URL (issue tracker or support page). |
| `publisher.party` | optional | `1p` (Microsoft) or `3p` (third-party). Used only for the contribution-source PR label; not validated against folder location. |
| `description` | ✅ | Plain-language description, up to 500 characters. |
| `tags` | ✅ | Non-empty array of kebab-case strings. |
| `associated_tools` | optional | Paths to tool sub-folders inside this agent's `tools/` directory. Each path must exist on disk. |
| `associated_agents` | optional | Paths to other agents this one depends on at runtime. |
| `supported_regions` | optional | Azure region aliases (e.g. `eastus`, `uksouth`, `swedencentral`). Omit for global. |
| `compliance` | optional | Boolean flags for `hipaa` and `soc2`. |

> **YAML hygiene:** duplicate mapping keys, hidden / OS-artefact files (`.DS_Store`, `.env`, `*.swp`, …), and binary blobs are rejected by the PR pipeline. Model-weight files must be Git-LFS tracked, ≤ 5 GB each, and in an allowed format — see the validator output for details if these checks fire.

---

## 5. `agent.yaml`

`agent.yaml` defines the agent's behaviour. It must conform to [`docs/schemas/agent-schema-v2.json`](../schemas/agent-schema-v2.json).

**Only `kind: prompt` is accepted in this repo.**

```yaml
kind: prompt                          # Required — must be "prompt"
name: ClinicalSummaryAgent            # Required — PascalCase or camelCase
displayName: Clinical Summary Agent
description: Summarises clinical notes into SOAP format.

model:                                # Required
  id: "{{CHAT-MODEL}}"                # Parameterised — end user supplies their model deployment name
  options:
    temperature: 0.3
    maxOutputTokens: 2048

instructions: |                       # Required — system prompt; YAML block scalar (|); max 32,000 chars
  You are a clinical documentation specialist. Given raw clinical notes,
  produce a structured SOAP note with the following sections:
  - Subjective: patient-reported symptoms
  - Objective: observed findings
  - Assessment: clinical impression
  - Plan: recommended next steps

  Always use formal medical language. Never speculate beyond the provided notes.
  If a section cannot be completed from the input, write "Insufficient information."

discoveryExtensions:                  # Required when the agent has a tools/ directory
  humanInTheLoop: Disabled
  tools:
    - toolId: '{{ehrLookupToolId}}'   # ARM resource ID — resolved at deploy time
      confirmation: Disabled
  disableDataHandlingTools: false
  disableDiscoveryInjectedTools: false
```

**Notes**

- **Parameterised values** use `{PLACEHOLDER}` syntax. They pass schema validation as plain strings; Discovery Studio identifies them as deploy-time inputs.
- **Knowledge-base agents** can omit `tools/` and the `discoveryExtensions.tools` block, and instead use `discoveryExtensions.knowledgeBases`:

  ```yaml
  discoveryExtensions:
    knowledgeBases:
      - knowledgeBaseId: "/bookshelves/{BOOKSHELF}/knowledgeBases/{KB}/versions/{VERSION}"
  ```

- Do **not** use the AgentSchema `tools:` array with `kind: custom` — that type is not recognised by AI Foundry and will cause HTTP 400 errors at deploy time. Only use the top-level `tools:` array for Foundry-native tool kinds (`web_search`, `file_search`, `code_interpreter`, `mcp`, `openapi`, etc.).

---

## 6. Tools (optional)

Only add a `tools/` subfolder if your agent uses **custom containerised tools**. Each tool needs:

```text
tools/
└── ehr-lookup/
    ├── tool.yaml         ← Conforms to docs/schemas/tool-definition-schema.json
    └── Dockerfile
```

**`tool.yaml` example:**

```yaml
name: ehr-lookup
description: Retrieves patient records from the EHR system.
version: 1.0.0
category: healthcare

infra:
  - name: ehr-lookup-container
    infra_type: container
    image:
      acr: "{ACR-NAME}.azurecr.io/ehr-lookup:1.0.0"
    compute:
      min_resources: { cpu: 1, ram: 2 }
      max_resources: { cpu: 4, ram: 8 }

actions:
  - name: get_patient_record
    description: Returns the full record for a given patient ID.
    infra_node: ehr-lookup-container
    command: "python run_action.py --action get_patient_record"
    input_schema:
      type: object
      properties:
        patient_id:
          type: string
          description: The unique patient identifier.
      required:
        - patient_id
```

**Constraints enforced by the PR pipeline**

- A tool can be **infra-only** (no `actions:`) — `actions` is an optional array that defaults to empty. Only `name`, `description`, `version`, `category`, and `infra` are strictly required.
- `infra[].name`, `actions[].name`, `actions[].output_mount_configurations[].output_name`, and `actions[].inline_files[].mount_path` must all be unique within a single `tool.yaml`.
- Every name listed in `actions[].input_schema.required` must appear in `properties`.
- Each `actions[].infra_node` must reference an entry in `infra[].name`.
- Every tool subfolder must contain both `tool.yaml` and `Dockerfile`.
- If a `tools/` directory exists, `agent.yaml.discoveryExtensions` must declare the corresponding tools so they are wired up at deploy time.

---

## 7. `README.md`

The README is the **primary documentation surface** for your agent — it's what customers see in Discovery Studio and what reviewers evaluate your contribution against. A thin or placeholder README will fail the documentation checks.

### Required sections

Your `README.md` must include all of these section headings:

- `# <Agent display name>` (top-level heading)
- `## Overview` (or `## Description`)
- `## Architecture` (or `## How it works`)
- `## Prerequisites`
- `## Configuration` (or `## Parameters`)
- `## Usage` (or `## Getting Started`)
- `## Known Limitations` (or `## Limitations`)
- `## Tools` — required when `tools/` exists
- `## Contributing` (or a reference to `CONTRIBUTING.md`)

> Avoid placeholder markers (`TODO`, `FIXME`, `XXX`) in the README, `metadata.yaml`, or `agent.yaml` — they are blocked by the validator.

### Example skeleton

```markdown
# Clinical Summary Agent

A concise one-paragraph description: what the agent does, who it is for,
and what the primary outcome is. This appears as the agent's summary card
in Discovery Studio.

## Overview

Explain the problem this agent solves. Answer:
- What scenario or workflow does it address?
- Who is the intended user?
- What does a successful outcome look like?

## Architecture

Describe how the agent works end-to-end. Include:
- The model being used and why
- External dependencies: APIs, databases, services, knowledge bases
- Data flow: what goes in, what comes out, what state (if any) is maintained

## Prerequisites

List everything a user needs before they can deploy this agent:
- Azure subscription and required role assignments
- Azure AI Foundry project with the required model deployment
- API endpoints / credentials your tools require

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{CHAT-MODEL}}` | Azure AI Foundry model deployment name | `gpt-4o-deployment` |

| Variable | Required | Description |
|---|---|---|
| `EHR_API_ENDPOINT` | ✅ | Base URL of the EHR REST API |
| `EHR_API_KEY` | ✅ | API key — store in Azure Key Vault |

## Usage

1. Deploy via Discovery Studio.
2. Fill in the configuration parameters above.
3. Invoke the agent with a sample input.

## Tools

Document each tool the agent uses, with inputs and outputs.

## Known Limitations

List any caveats, unsupported scenarios, or known issues.

## Support

For issues or questions, contact <support@example.com> or open an issue at
https://github.com/<your-org>/<your-repo>/issues.

## Contributing

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for the catalog's contribution
workflow.
```

---

## 8. Submitting a pull request

All contributors submit PRs from a **fork**. Direct pushes to `main` are not permitted; only Microsoft Discovery maintainers can merge.

```bash
# 1. Fork the repo at https://github.com/microsoft/discovery (use the GitHub UI)

# 2. Clone your fork
git clone https://github.com/<your-org>/discovery.git
cd discovery

# 3. Add the upstream remote to stay current
git remote add upstream https://github.com/microsoft/discovery.git

# 4. Sync before starting work
git fetch upstream && git merge upstream/main

# 5. Create a working branch in your fork
git checkout -b add-clinical-summary-agent

# 6. Add your agent folder
mkdir -p agents/clinical-summary-agent
# … create metadata.yaml, agent.yaml, README.md, and (optionally) tools/ …

# 7. Push to your fork and open a PR against microsoft/discovery:main
git add agents/clinical-summary-agent/
git commit -m "feat: add clinical-summary-agent"
git push origin add-clinical-summary-agent
# Open the PR from your fork in the GitHub UI.

# 8. Sign the CLA when prompted (one-time per GitHub account).
```

What happens next:

1. The automated review runs (structural, schema, policy, documentation, and security checks).
2. Any failures are posted as inline review comments with a rule identifier and remediation hint. Address each comment and push a follow-up commit.
3. When all checks pass, the `pr-validation-passed` label is applied and the CODEOWNERS maintainers are auto-requested for review.
4. One approval from a CODEOWNERS reviewer is required to merge.

---

## 9. Schema reference

| Schema | Validates | Path |
|---|---|---|
| `metadata-schema.json` | `metadata.yaml` in every agent | [`docs/schemas/metadata-schema.json`](../schemas/metadata-schema.json) |
| `agent-schema-v2.json` | `agent.yaml` for every agent | [`docs/schemas/agent-schema-v2.json`](../schemas/agent-schema-v2.json) |
| `tool-definition-schema.json` | `tool.yaml` inside each tool subfolder | [`docs/schemas/tool-definition-schema.json`](../schemas/tool-definition-schema.json) |
| `registry-schema.json` | The auto-generated `.auto-registry/agent-registry.json` | [`docs/schemas/registry-schema.json`](../schemas/registry-schema.json) |
