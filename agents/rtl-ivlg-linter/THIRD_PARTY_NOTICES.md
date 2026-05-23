# Third-Party Notices

This Discovery agent embeds open-source software components inside its container
image. The wrapper code (agent definition, tool definition, Dockerfile, Python
utilities) is licensed under the MIT License (see [`LICENSE`](LICENSE)). Each
upstream component listed below retains its own license, which governs that
component.

## Components

| Component       | Version | License     | Source                                                  | Notes                                                   |
|-----------------|---------|-------------|---------------------------------------------------------|---------------------------------------------------------|
| Icarus Verilog  | v12_0   | GPL-2.0     | https://github.com/steveicarus/iverilog                 | Provides `iverilog`, `vvp`, `iverilog-vpi`, `vvp-conf`. |
| Azure Linux 3.0 | 3.0     | MIT (most)  | https://github.com/microsoft/azurelinux                 | Base OS image (`mcr.microsoft.com/azurelinux/base/core:3.0`). |
| bash, coreutils, findutils, grep, sed, gawk, make, git, tar, gzip | (distro) | GPL-3.0 / GPL-2.0+ | (Azure Linux packages) | Standard GNU userland for EDA scripting. |
| Python 3        | 3.12    | PSF-2.0     | https://www.python.org                                  | Runtime for `iverilog_utils.py` orchestration.          |
| Jinja2          | latest  | BSD-3-Clause| https://palletsprojects.com/p/jinja/                    | HTML report templating.                                 |
| Matplotlib      | latest  | PSF-based   | https://matplotlib.org                                  | Severity-distribution chart.                            |

The container preserves the upstream Icarus Verilog `COPYING` (GPL-2.0) and
`LICENSE` files at:

- `/app/iverilog/COPYING`
- `/app/iverilog/LICENSE`

## Distribution model

This agent is distributed as **source** (Dockerfile, agent YAML, tool YAML,
utilities, example project). Consumers build their own container image locally
(via `docker build`) or via Azure Container Registry cloud build, and push the
resulting image into their own registry.

Because Icarus Verilog is GPL-2.0, the party that **builds and distributes the
resulting container image** becomes the GPL-2.0 distributor of the embedded
`iverilog`/`vvp` binaries and assumes the corresponding GPL-2.0 obligations
(notably: making the corresponding source available to recipients on request).

The Microsoft-authored wrapper code under `/app/` (the Python utilities, the
agent definition, the tool definition, and this Dockerfile itself) remains
licensed under the **MIT License** regardless of how the resulting image is
distributed.

If you want a permissive-only image, you may substitute Icarus Verilog with a
non-GPL alternative (e.g. a commercial Verilog simulator under a different
license, or a permissively-licensed RTL parser such as Slang) — but doing so
will require modifying `iverilog_utils.py` to call the new tool's CLI.

## Trademark

"Icarus Verilog" is the name of the upstream project authored by Stephen
Williams. This agent uses the descriptive name `rtl-iverilog-linter` and the
display name "RTL Verilog Linter (powered by Icarus Verilog)" to credit the
upstream project without implying endorsement.
