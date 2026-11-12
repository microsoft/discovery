# SiPhy customer readiness and release gates

The original [v1.1 guide](QuickStart-Spec-to-RTL.md) is a reference recipe,
not a validated zero-configuration distribution. Its Section 6 prompt and
engineering acceptance criteria remain unchanged. The bootstrap reduces file
preparation work; it does not turn missing application integration into PASS.

## What "running within five minutes" means

The proposed warm-start target is at most five minutes from opening an already
downloaded package to the first successful **specialist-owned** Microchip
documentation lookup. Prerequisites are a supported, signed-in Discovery app,
an available model, Python, a running Linux container engine, and the three
reviewed images. Record the app/model versions, hardware, cache state, start/end
times and actual specialist response. File extraction or a parent lookup is
not the finish line.

A clean machine also needs application installation, authentication, container
virtualization, image delivery and potentially organization approvals.
Those are separate cold-start measurements, not work to hide outside a claimed
"five-minute install." Full RTL authoring and independent verification are also
separate from startup. No five-minute customer benchmark is established here.

## Step-by-step audit

| Guide step | Current disposition | Required evidence before customer acceptance |
| --- | --- | --- |
| 1. Recipe identity | Full v1.1 recipe supplied; its reference reused an existing contract and RTL. | A fresh-project run without private/historical implementation inputs. |
| 2. Model | Reference parent is `gpt-6.1-sol`; specialists were not independently pinned. | Record the actual parent and each observable specialist setting. A different model is a variant, not the original benchmark. |
| 2. Agents and skills | Archive contains the four agents and report renderer; the bootstrap stages effective files with provenance. | Runtime catalog discovery plus successful invocation. Files alone are not activation. |
| 2. Microchip integration | Current public endpoint and documentation action are identified below. | Required action callable inside `hardware-spec-dev`, not merely the parent. |
| 3. Host requirements | Historical minimums were not established; warm prerequisites can be inspected locally. Image presence is not proof that resource-limited containers start. | Current OS/architecture, Python, engine, image identities, memory, disk and required cgroup controllers. |
| 4. Access/authentication | Discovery model sign-in and organization network policy remain external prerequisites. | Authorized sign-in and actual tool request; never embed credentials in a package. |
| 5.1 Profile and inputs | Archive checksum, safe member paths and effective file provenance are machine-checkable. | Exact archive checksum, full member inventory and unchanged guide/prompt. |
| 5.2 Installation and images | Build contexts, not prebuilt images, are supplied. Bootstrap does not install, pull or build. | All three approved image identities on a working Linux engine. Cold builds need explicit approval. |
| 5.3 Tool import and grants | Importable MCP configuration is supplied. No machine-specific source ID should be copied to another customer. | Supported app import, correct agent grant, new/resumed session loading and specialist probe. |
| 5.4 Handbook | Runtime retrieval remains required; no handbook is fabricated or silently substituted. | Official source, PDF hash, version/revision and actual content inspection. |
| 5.4 Contract | The authorized reference implementation contract is not in the archive. | Parent-authored `knowledge/CORESPI_HB.md`, user decisions for consequential gaps and a frozen run copy. |
| 5.4 Bookshelf | Optional; excluded from default preparation. | No indexing required for the baseline. Consultation must be recorded only if it actually occurs. |
| 5.5 Readiness | Host preflight and endpoint diagnostics are separate from application readiness. | Agent-owned lookup, active report skill and all native prerequisites. |
| 6. Specification | Requires official evidence and explicit unresolved behavior. | Source-grounded reference, measurable requirements and no invented defaults. |
| 6. RTL design | Must be performed by `chip-rtl-design`; a host smoke test is not a substitute. | Native design envelope, exits, legal/illegal parameter evidence and input hash. |
| 6. Lint/format | Must be performed by `chip-rtl-lint`. | DEFAULT rules, no waivers, canonical formatting and identical RTL hash. |
| 6. Independent verification | Must be performed by `chip-functional-verification`. | Independent bench, positive comparison count, zero mismatches, exact PASS marker, native exits and nonempty VCD. |
| 6. Repairs | Failed attempts remain evidence; any adopted RTL change invalidates earlier final gates. | Repeat design, lint/format and simulation against the same final bytes. |
| 6. Reporting | Bundled renderer produces offline HTML from native evidence. | Real renderer exit; disclose exit 2/evidence gaps and unverified visual inspection. |
| 7. Timing | Historic native runtimes are not end-to-end startup measurements. | Separate cold setup, warm startup and engineering timing. |
| 8. Troubleshooting/cleanup | Do not delete shared locks, restart unrelated runtimes, or overwrite earlier artifacts. | Scoped diagnostics and explicit permission for destructive changes. |
| 9. Publication | Missing reference evidence cannot be reconstructed from prose. | Reviewable public artifacts and clean-machine acceptance before claiming turnkey readiness. |

## Microchip: endpoint health versus specialist access

Use the HTTP MCP endpoint:

```text
https://api.microchip.com/mcp/resources
```

The server action is `search_microchip_product_documents`, with a required
string `query` and optional integer `limit`. The bounded probe uses:

```json
{"query": "CoreSPI HB0089 handbook 5.2", "limit": 10}
```

The optional [endpoint diagnostic](probe_microchip.py) performs MCP
initialization, complete bounded tool listing, live schema checks and one
documentation call. It rejects transport/protocol/application errors and
requires the exact official handbook link. Run it from this directory:

```console
python probe_microchip.py --output microchip-endpoint.json
```

The output path must be new. No extra Python packages or credentials are
required by this script. It uses normal TLS validation, refuses redirects,
does not download the handbook, and never saves an authorization header or MCP
session token. Organization proxies or future service authentication changes
can still block access; do not disable TLS or guess alternate endpoints.

An application-level successful response was observed on 2026-11-12 without
an Authorization header. This is a dated observation, not a promise that the
service will always be unauthenticated. The diagnostic's `endpoint_pass`
status explicitly leaves `workflow_ready` false and `specialist_activation`
unverified.

During the same portability diagnosis, direct parent requests succeeded while
`hardware-spec-dev` exposed no Microchip documentation action. A saved catalog
source reference parsed successfully but did not prove a live tool grant.
A separate exact-action spelling experiment also did not establish activation.
These failures must not be relabeled as network failures or papered over with
a parent HTTP fallback.

File-backed agent references and active MCP grants are different layers.
The installed parser preserves the qualified selector
`sdk/microchip-mcp-server/search_microchip_product_documents` as the exact
`microchip-mcp-server/search_microchip_product_documents` action name.
This avoids copying a customer-specific catalog source ID. It still requires
the matching server to be imported and the host to load the definition.
Parser acceptance is not a successful specialist invocation. A final dispatch
after applying this qualified selector also exposed no documentation action
in the tested host session. The prepared selector is therefore an unvalidated
candidate, not a demonstrated activation repair; the active project's
experimental edits were restored.

The Discovery app's source is not in this repository; see
[Contributing](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md).
A repository bootstrap cannot safely
patch the installed app, refresh a frozen chat through an invented API, or
edit private state to bypass grants. If the supported app import and a
fresh/resumed session do not expose the action, the app integration remains
a release blocker.

### Minimal app-owned regression

1. Import the supplied Microchip plugin into a trusted new project using the
   supported app flow; authorize its use.
2. Discover `hardware-spec-dev` and load its current definition in a new chat.
3. Invoke that specialist with only the bounded query above.
4. Require the specialist's actual tool call, application `success: true` and
   official handbook link. Parent success does not count.
5. Disable or revoke the grant and repeat: the specialist must stop explicitly,
   with no HTTP bypass. Re-enable through the supported flow and verify recovery.
6. Repeat in another clean project without reusing the first project's source
   ID, cached agent definition or session state.

No product-private runtime source or credentials are needed in the public
regression report. Capture app version, sanitized plugin/server identity,
definition hash, observable grants, call outcome and whether a session reload
was required.

## Container health: inspect is not execute

A real startup diagnostic on 2026-11-12 found all three existing image tags and
a responsive Linux Podman engine, but every resource-limited container failed
before its binary ran:

```text
crun: open `memory.max` for writing: No such file or directory
```

The rootless engine reported cgroup v2 with no delegated controllers. Keep the
required CPU, memory and process limits; removing them would change the approved
execution contract, not repair the environment. The bootstrap checks available
controller evidence and never equates image inspection with native execution.

The symptom matches the upstream
[Podman/WSL rootless cgroup issue](https://github.com/podman-container-tools/podman/issues/29966).
Its discussion records a successful report after upgrading to Podman 6.2.0;
that is external issue evidence, **not** a tested upgrade of this environment or
a universal version guarantee. Check both host and guest versions through the
supported distribution/update path. A systemd-manager override and runtime
user-slice accounting did not restore controllers in this diagnosis.

Do not automatically downgrade WSL, install software, switch to rootful
containers, restart a shared VM or edit kernel cgroups. Those changes require
separate owner approval and validation. A supported Docker Linux engine or a
corrected, approved Podman/WSL combination must still pass an actual bounded
container startup check before engineering. An endpoint PASS cannot compensate
for this native runtime failure.

## What maintainers must deliver for a turnkey release

| Deliverable | Why a script alone cannot supply it |
| --- | --- |
| Supported one-action package import with scoped grants and session refresh | Must be implemented and regression-tested in the app host; adding files cannot prove activation. |
| Reviewed, versioned container distribution | Current archive has build contexts only. Prebuilt image publication needs approved hosting, licensing, digests and supply-chain review. |
| Explicit original implementation contract | Vendor documentation does not resolve every new-design behavior. A maintainer-approved contract can avoid repeated customer decisions without inventing vendor equivalence. |
| Public reference outputs or a clearly separate reference run | The five historical guide links, RTL, testbench, waveform and contract are not supplied. Do not fabricate or silently replace them. |
| Clean-machine and warm-start acceptance | Record real timing and outcomes on each supported platform. A unit-test PASS or fast extraction is insufficient. |

The current preparation path is useful for developers and supported pilots.
Until these gates pass, do not advertise it as a 100% self-contained,
zero-configuration, five-minute customer QuickStart.
