# preflight-checks/

Encapsulated add-on checks that extend `../preflight.sh`. Every file named
`NN-*.sh` in this directory is auto-sourced by the orchestrator (in numeric
order) after its four built-in checks and before the summary.

Each module is one concern in one file. To disable a module: remove its file
(or rename its numeric prefix out of the `[0-9]` glob). No changes to
`preflight.sh` are needed.

## Module contract

A module is a shell fragment (`.sh`) that is `source`d into the orchestrator.
It runs at top level -- no function wrapper required. It has access to:

| Symbol                | Kind      | Provided by                           |
| --------------------- | --------- | ------------------------------------- |
| `pass "..."`          | function  | `preflight.sh`                        |
| `warn "..."`          | function  | `preflight.sh` (increments `WARN_COUNT`) |
| `fail "..."`          | function  | `preflight.sh` (increments `FAIL_COUNT`) |
| `info "..."`          | function  | `preflight.sh`                        |
| `read_tfvar KEY`      | function  | `preflight.sh` (reads `./terraform.tfvars`) |
| `read_tf_default KEY` | function  | `preflight.sh` (reads `./variables.tf`)     |
| `LOCATION`            | env var   | resolved location (CLI > tfvars > variables.tf) |
| `NODE_POOL_VM_SIZE`   | env var   | resolved node pool SKU                |
| `NODE_POOL_MAX_COUNT` | env var   | resolved max node count               |
| `AKS_SYSTEM_VM_SIZE`  | env var   | Discovery RP internal default         |
| `SUB_ID`              | env var   | `az account show --query id`          |
| `SUB_NAME`            | env var   | `az account show --query name`        |

Modules **must** use `pass` / `warn` / `fail` so the summary count is accurate.

Modules **should not** call `exit`; the orchestrator handles that.

Modules **may** self-skip (with an `info` explaining why) based on an
environment toggle -- see `09-network-security-perimeter.sh` for the pattern.

## Current modules

| File                                  | Check | Purpose                                                              |
| ------------------------------------- | ----- | -------------------------------------------------------------------- |
| `05-additional-resource-providers.sh` | 5     | Registration state of the other 24 RPs Discovery depends on          |
| `06-approved-regions.sh`              | 6     | Positive allowlist match against the Discovery-supported region list |
| `07-cosmosdb-region.sh`               | 7     | `Microsoft.DocumentDB` supports the target region                    |
| `08-ai-foundry-tpm.sh`                | 8     | AI Foundry TPM quota for the chat model in the target region         |
| `09-network-security-perimeter.sh`    | 9     | Opt-in: `AIFSPInfrastructure` SP + NSP Perimeter Joiner role + Reader |

## Provenance

The checks in modules 5-9 mirror the deterministic gates enforced by the
Microsoft Discovery Toolbox VS Code extension (see
`../../discovery-toolbox/README.md`). The toolbox performs 100+ prerequisite
checks; the ones ported here are those that are (a) deterministic
pre-`terraform apply` and (b) relevant to the Terraform module in this
directory (which deploys standard VNet-injected workspaces, not
network-hardened / NSP-joined ones -- hence module 9 is opt-in).
