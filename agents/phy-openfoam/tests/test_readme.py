"""Landing-page terminology and the diagnostic primitives used in its examples.

These are documentation/adapter checks, not execution of the advertised studies
or evidence that Scientific Researcher's engine path has been qualified.
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree

from discovery_physics.core.models import Diagnostics
from discovery_physics.openfoam.monitors import monitor_block

ROOT = Path(__file__).resolve().parents[1]


def test_readme_uses_the_user_facing_capability_name():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Scientific Researcher" in text
    # The user now selects the local specialist in Prompt 2. A documented
    # researcher alias is also permitted, but neither proves engine dispatch.
    assert "clio-mode" not in text or "Scientific Researcher (or clio-mode)" in text
    assert "CLIO" not in text
    assert "Historical native-runtime testing" in text
    assert "do not by themselves qualify" in text


def test_readme_preserves_catalog_sections_and_scoped_comparison():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for heading in ("Overview", "Architecture", "Setup", "Prerequisites", "Configuration",
                    "Usage", "Tools", "Known Limitations", "Contributing"):
        assert f"\n## {heading}\n" in text
    assert text.index("\n## Architecture\n") < text.index("\n## Setup\n") < text.index("\n## Tools\n")
    setup = text.split("\n## Setup\n", 1)[1].split("\n## Tools\n", 1)[0]
    headings = [(2, "Prerequisites"), (3, "Prompt 1 — Acquire and install"),
                (3, "Prompt 2 — Test the Scientific Researcher workflow"),
                (2, "Configuration"), (2, "Usage")]
    positions = [setup.index(f"\n{'#' * level} {heading}\n") for level, heading in headings]
    assert positions == sorted(positions)
    install = setup.split("\n### Prompt 1 — Acquire and install\n", 1)[1].split("\n### Prompt 2", 1)[0]
    assert "https://github.com/microsoft/discovery/tree/main/agents/phy-openfoam" in install
    assert "Use this URL only after publication" in install
    assert "complete entry" in install and "resolved source commit or release" in install
    assert ".github/skills/phy-openfoam/SKILL.md" in install
    assert ".github/agents/phy-openfoam.agent.md" in install
    assert "Do not run a CFD simulation yet" in install
    smoke = setup.split("\n### Prompt 2 — Test the Scientific Researcher workflow\n", 1)[1].split("\n## Configuration\n", 1)[0]
    assert "select the phy-openfoam agent in the chat drop down" in smoke
    assert "submit a CFD prompt" in smoke
    assert "not a third routable family" in text
    assert "CFD Forge could be extended" in text
    assert "not claims that" in text and "already run or passed" in text
    assert text.count("**Why this goes beyond CFD Forge's published families:**") == 2
    overview = text.split("\n## Overview\n", 1)[1].split("\n## Architecture\n", 1)[0]
    assert "Start with [installation]" not in overview
    assert "packaging\nupdate" not in overview and "Fresh [0.2.1 source validation]" not in overview
    usage = setup.split("\n## Usage\n", 1)[1]
    assert "Start with [installation]" in usage
    status = text.split("\n## Release status and validation\n", 1)[1]
    assert "proposed **0.2.1** packaging" in status
    assert "Fresh [0.2.1 source validation]" in status
    assert "](media/architecture.svg)" in text
    diagram = ROOT / "media/architecture.svg"
    assert diagram.stat().st_size <= 1024 * 1024
    svg = ElementTree.fromstring(diagram.read_bytes())
    assert svg.attrib["role"] == "img" and svg.attrib["aria-labelledby"]
    labels = " ".join(svg.itertext())
    for boundary in ("CFD prompt", "MICROSOFT DISCOVERY", "Scientific Researcher",
                     "phy-openfoam agent", "phy-openfoam skill", "LOCAL HOST",
                     "discovery-physics CLI", "ISOLATED CONTAINER", "OpenFOAM Foundation 14"):
        assert boundary in labels
    ns = {"svg": "http://www.w3.org/2000/svg"}
    for component in ("phy-openfoam-agent", "phy-openfoam-skill"):
        assert svg.find(f"svg:g[@id='{component}']", ns) is not None
    assert "optional" not in labels and "stroke-dasharray" not in diagram.read_text(encoding="utf-8")
    # The catalog accepts inert, locally embedded SVGs, not active web content.
    for element in svg.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        assert tag not in {"script", "foreignObject", "image", "animate", "set"}
        for key, value in element.attrib.items():
            assert not key.lower().startswith("on")
            assert not key.endswith("href")
            assert not value.startswith(("http:", "https:", "data:", "javascript:"))
    # Named spacing macros and prose percentages survive both math-first and
    # Markdown-first rendering. Markdown may strip backslashes before punctuation.
    for line in text.splitlines():
        if line.startswith("> "):
            assert line.count("$") % 2 == 0
            assert r"\%" not in line and r"\," not in line
            assert "$Re_D" not in line


def test_wsl_docs_separate_native_boot_resource_enforcement_and_cfd():
    guide = (ROOT / "docs/podman-wsl.md").read_text(encoding="utf-8")
    installation = (ROOT / "docs/installation.md").read_text(encoding="utf-8")
    configuration = (ROOT / "docs/configuration.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "WSL-native systemd" in guide and "6.2 or later" in guide
    assert "not automatically migrated" in guide
    assert "not a resource-enforcement check" in guide
    for control in ("cpu.max", "memory.max", "pids.max"):
        assert control in guide
    for argument in ("--cpus 1", "--memory 512m", "--pids-limit 128",
                     "--rootful=false", "--update-connection=false"):
        assert argument in guide
    assert "536870912" in guide and "os.getuid() == 10001" in guide
    assert "Retain" in guide or "Keep the old machine" in guide
    assert "does **not** make its missing" in guide
    assert "CONTAINER_CONNECTION" in configuration and "absolute executable path" in configuration
    for text in (installation, configuration, readme):
        assert "podman-wsl.md" in text
    assert "non-solver resource probe" in readme


def test_on_demand_status_is_read_only_and_does_not_change_supervision():
    skill = (ROOT / "skills/phy-openfoam/SKILL.md").read_text(encoding="utf-8")
    agent = (ROOT / "integrations/phy-openfoam.agent.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs/progress.md").read_text(encoding="utf-8")
    for text in (skill, agent, guide):
        normalized = " ".join(text.lower().split())
        assert "on-demand by default" in normalized
        assert "one fresh read-only snapshot" in normalized
        assert "status" in normalized and "progress" in normalized
        assert "is it still running?" in normalized
        assert "cross-check" in normalized and "liveness" in normalized
        assert "stop after the snapshot" in normalized
        assert "opt-in" in normalized
        assert "supervision" in normalized and "signed evidence" in normalized
        assert "terminal" in normalized
    assert "do not keep the chat open, add a timer, or start a polling loop" in skill
    assert "no timer, polling loop, or forced active turn" in agent
    assert "does not send chat messages" in skill
    assert "does not install" in guide and "host scheduler/notification integration" in guide
    assert "not** bundled with the standalone copied" in guide
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "(docs/progress.md)" in readme
    assert "periodic monitoring is opt-in" in readme


def test_generous_budget_planning_preserves_frozen_and_resource_limits():
    skill = (ROOT / "skills/phy-openfoam/SKILL.md").read_text(encoding="utf-8")
    agent = (ROOT / "integrations/phy-openfoam.agent.md").read_text(encoding="utf-8")
    for text in (skill, agent):
        normalized = " ".join(text.lower().split())
        assert "budget for completion, not a short demo" in normalized
        assert "generous approved headroom" in normalized
        assert "hours-long runs are acceptable" in normalized
        assert "runtime estimate" in normalized
        assert "thermal/pressure-based runtime guarantee" in normalized
        assert "authorized pilot" in normalized and "before freezing" in normalized
        assert "never edit a frozen budget" in normalized
        assert "disable timeouts" in normalized and "weaken tolerances" in normalized
        assert "approval" in normalized and "new lineage" in normalized
    assert "finite budget guarantees convergence" in skill
    assert "CONTINUE_RUN" in skill and "operator cap" in skill


def test_timed_examples_preserve_user_copies_and_expanded_download_context():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    panels = re.findall(r"<details>\s*<summary>(Plain text[^<]+)</summary>\s*(.*?)</details>", text, re.S)
    assert len(panels) == 3
    assert text.count("<details>") == text.count("</details>") == 3
    assert [label for label, _ in panels] == [
        "Plain text — copy the heated-channel prompt",
        "Plain text — copy the isolated-cylinder prompt",
        "Plain text — copy the installation prompt",
    ]
    assert all(len(re.findall(r"```text\n(.*?)\n```", body, re.S)) == 1 for _, body in panels)
    overview = text.split("### Two bounded CFD prompts", 1)[1].split("\n## Architecture", 1)[0]
    copies = re.findall(r"```text\n(.*?)\n```", overview, re.S)
    assert len(copies) == 2
    for copied, name in zip(copies, ("01-thermal-quick.txt", "02-cylinder-hour.txt")):
        original = (ROOT / "examples/prompts" / name).read_text(encoding="utf-8")
        # README copy fields are the user's concise scientific prompts; the
        # downloads retain their surrounding setup, routing and report guidance.
        assert copied in original
        assert copied.isascii() and "$" not in copied and "\\" not in copied
        assert not any(line.startswith((">", "#", "**")) for line in copied.splitlines())
        assert "before" in copied and "convergence guarantee" in copied
        assert "approval" in original and "HTML report" in original
        assert "results-" in original and "project root" in original
    quick, hour = copies
    assert "900-second" in quick and "6000 cells" in quick and "160 by 32" in quick
    assert "no automatic retries" in quick.lower() and "bounded temperature advection" in quick
    assert "native mass-flow-weighted" in quick and "not an area-average substitute" in quick
    assert "exactly two" in hour and "40000 cells" in hour and "20 diameters upstream" in hour
    assert "2700-second" in hour and "5400 worker-seconds" in hour
    assert "two grids cannot establish" in hour.lower() and "third grid" in hour
    assert "No automatic continuation" in hour and "Do not substitute a confined-channel benchmark" in hour
    assert "3 percent point-reference tolerance" in hour
    assert "5–10 minutes" in overview and "about one hour" in overview
    assert "not timing or convergence guarantees" in overview
    assert "cold installation" in overview and "image build" in overview
    setup = text.split("\n## Setup\n", 1)[1].split("\n## Tools", 1)[0]
    installation = setup.split("### Prompt 1 — Acquire and install", 1)[1].split("\n### Prompt 2", 1)[0]
    assert "Plain text" in installation and "```text\n" in installation
    smoke = setup.split("### Prompt 2 — Test the Scientific Researcher workflow", 1)[1].split("\n## Configuration", 1)[0]
    assert "select the phy-openfoam agent in the chat drop down" in smoke
    assert "### Where to find results" in overview
    assert "generated HTML report linked in chat" in overview


def test_budget_docs_distinguish_deadlines_and_post_run_output_from_hard_caps():
    readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
    guide = " ".join((ROOT / "docs/configuration.md").read_text(encoding="utf-8").split())
    assert "not the complete worker lifetime" in readme
    assert "Output size is checked after writing" in readme
    assert "explicit agreement on weaker limits before freezing" in readme
    assert "wall_seconds + 600" in guide
    assert "not a live filesystem quota" in guide
    assert "silently carry an exception to a new request" in guide


def test_final_html_is_required_across_instructions_without_mutating_scientific_authority():
    for name in ("skills/phy-openfoam/SKILL.md", "integrations/phy-openfoam.agent.md", "agent.yaml"):
        text = (ROOT / name).read_text(encoding="utf-8")
        normalized = " ".join(text.lower().split())
        assert "html" in normalized and "summary" in normalized
        assert any(phrase in normalized for phrase in ("opening", "open with", "start with"))
        assert "images" in normalized and "schematic" in normalized
        assert "reject" in normalized and "blocked" in normalized
        assert "signed" in normalized and "outside" in normalized
    skill = (ROOT / "skills/phy-openfoam/SKILL.md").read_text(encoding="utf-8")
    assert "./scripts/render_report.py" in skill
    assert "report-packaging blocker" in skill and "status-only" in skill
    assert "no success claim based solely on a successful renderer exit" in skill
    guide = (ROOT / "docs/reporting.md").read_text(encoding="utf-8")
    assert "not a new scientific decision" in guide
    assert "does not" in guide and "independently verify" in guide
    guide_words = " ".join(guide.replace("*", "").split())
    assert "whole supplied skill folder" in guide_words
    assert "leaf runs" in guide_words and "not necessarily all restart ancestors" in guide_words


def test_project_root_results_policy_is_explicit_in_instructions_and_copy_prompts():
    for relative in ("skills/phy-openfoam/SKILL.md", "integrations/phy-openfoam.agent.md", "agent.yaml"):
        text = " ".join((ROOT / relative).read_text(encoding="utf-8").lower().split())
        assert "results-" in text and "project" in text and "explicit" in text
        assert "agents" in text and "source" in text and "never" in text
        assert "signing keys" in text or "keys" in text
    skill = (ROOT / "skills/phy-openfoam/SKILL.md").read_text(encoding="utf-8")
    assert "./scripts/project_results.py" in skill
    assert "DISCOVERY_PHYSICS_RUNS=<results>/runs" in skill
    assert "no initializer" in skill and "Status-only" in skill
    for file in ("01-thermal-quick.txt", "02-cylinder-hour.txt"):
        text = (ROOT / "examples/prompts" / file).read_text(encoding="utf-8")
        assert "results-" in text and "project root" in text
        assert "agents" in text and "source" in text


def test_thermal_example_uses_supported_flux_weighting_not_ratio_of_averages():
    # Foundation 14 surfaceFieldValue::average applies weightField natively:
    # sum(phi*T)/sum(phi). No invented T-times-U field or division of an
    # unweighted mean by mass flow is needed. The solver must supply phi with
    # the correct mass/volume-flux convention for the chosen density model.
    diagnostics = Diagnostics.model_validate({
        "fields": [{"name": "T", "unit": "K"}], "target_time": 1.0,
        "quantities": [{
            "name": "outlet_bulk_temperature", "function": "surfaceFieldValue",
            "settings": {"select": "patch", "patch": "outlet", "operation": "average",
                         "weightField": "phi", "fields": "(T)"},
            "column": "average(T)", "unit": "K",
        }],
    })
    block = monitor_block(diagnostics)
    assert "operation average;" in block and "weightField phi;" in block
    assert "fields (T);" in block
    assert "weightedAverage" not in block


def test_tandem_example_uses_supported_single_and_combined_force_patches():
    quantities = [{
        "name": name, "function": "forceCoeffs",
        "settings": {"patches": patches, "rho": "rhoInf", "rhoInf": "998.2",
                     "magUInf": "0.002", "lRef": "0.01", "Aref": "0.00002",
                     "dragDir": "(1 0 0)", "liftDir": "(0 1 0)",
                     "pitchAxis": "(0 0 1)", "CofR": "(0 0 0)"},
        "column": "Cd",
    } for name, patches in (("first", "(cylinder1)"), ("second", "(cylinder2)"),
                            ("combined", "(cylinder1 cylinder2)"))]
    diagnostics = Diagnostics.model_validate({
        "fields": [{"name": "p"}], "target_time": 1.0, "quantities": quantities,
    })
    block = monitor_block(diagnostics)
    assert "q_first" in block and "q_second" in block and "q_combined" in block
    assert "patches (cylinder1 cylinder2);" in block