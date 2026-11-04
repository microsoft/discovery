"""End-to-end tests for the flow-cytometry QC helper."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from flowio import create_fcs

sys.path.insert(0, str(Path(__file__).parent))
import flow_qc_utils
from flow_qc_utils import build_qc_report, load_fcs, run_qc, write_qc_artifacts


def test_load_fcs_preserves_channel_names_and_time_qc(tmp_path: Path) -> None:
    """A generated standards-compliant FCS file retains names needed by technical checks."""
    destination = tmp_path / "synthetic.fcs"
    rng = np.random.default_rng(42)
    events = np.column_stack(
        (
            rng.normal(50_000, 5_000, 500),
            rng.normal(20_000, 3_000, 500),
            np.arange(500),
            rng.uniform(0, 60_000, 500),
        )
    ).astype("float32")
    with destination.open("wb") as handle:
        create_fcs(
            handle,
            events.flatten().tolist(),
            ["FSC-A", "SSC-A", "Time", "FITC-A"],
            metadata_dict={"$SPILLOVER": "synthetic"},
        )

    metadata, parsed_events = load_fcs(destination)
    report = build_qc_report(metadata, parsed_events)

    assert parsed_events.columns.tolist() == ["FSC-A", "SSC-A", "Time", "FITC-A"]
    assert report["event_count"] == 500
    assert report["compensation_metadata_present"] is True
    assert report["time_integrity"]["available"] is True
    assert report["outlier_summary"]["available"] is True
    assert json.dumps(report)


def test_write_qc_artifacts_creates_dashboard_and_csv(tmp_path: Path) -> None:
    events = pd.DataFrame(
        {
            "FSC-A": [100, 200, 300],
            "FSC-H": [90, 190, 290],
            "SSC-A": [20, 30, 40],
            "Time": [0, 1, 2],
            "Event #": [1, 2, 3],
            "FITC-A": [10, 30, 20],
        }
    )
    report = build_qc_report(
        {"_channel_ranges": {"Event #": 3, "FITC-A": 100}, "_channel_stains": {}}, events
    )
    artifacts = write_qc_artifacts(report, events, tmp_path, "fixture")
    assert Path(artifacts["qc_dashboard"]).read_bytes().startswith(b"\x89PNG")
    assert Path(artifacts["channel_summary_csv"]).is_file()
    assert report["channel_roles"]["index"] == ["Event #"]
    event_summary = next(item for item in report["channel_summaries"] if item["channel"] == "Event #")
    assert event_summary["at_declared_range_fraction"] is None
    assert "FSC-H" not in report["channel_roles"]["fluorescence"]


def test_declared_range_fraction_counts_values_at_instrument_maximum() -> None:
    """$PnR = 1024 means values 0-1023, so events recorded at 1023 are at the range limit."""
    events = pd.DataFrame(
        {
            "FSC-H": [100.0, 1023.0, 1023.0, 500.0],
            "SSC-H": [10.0, 20.0, 30.0, 1022.0],
            "Time": [0.0, 1.0, 2.0, 1023.0],
        }
    )
    report = build_qc_report(
        {"_channel_ranges": {"FSC-H": "1024", "SSC-H": "1024", "Time": "1024"}, "_channel_stains": {}},
        events,
    )
    fractions = {row["channel"]: row["at_declared_range_fraction"] for row in report["channel_summaries"]}
    assert fractions == {"FSC-H": 0.5, "SSC-H": 0.0, "Time": None}


def test_dashboard_sample_spans_whole_run() -> None:
    events = pd.DataFrame({"Time": np.arange(50_000, dtype=float)})

    sample = flow_qc_utils._dashboard_sample(events)

    assert len(sample) == 20_000
    assert sample["Time"].iloc[0] == 0.0
    assert sample["Time"].iloc[-1] == 49_999.0
    assert flow_qc_utils._dashboard_sample(events.iloc[:100]).equals(events.iloc[:100])


def test_run_qc_writes_report_csv_and_dashboard(tmp_path: Path) -> None:
    source = tmp_path / "sample-01.fcs"
    index = np.arange(100)
    events = np.column_stack((1_000 + index, 2_000 + 2 * index, index, index + 1)).astype("float32")
    with source.open("wb") as handle:
        create_fcs(handle, events.flatten().tolist(), ["FSC-A", "SSC-A", "Time", "FITC-A"])

    result = run_qc(source, tmp_path / "output")

    artifacts = {key: Path(value) for key, value in result["artifacts"].items()}
    assert {key: path.name for key, path in artifacts.items()} == {
        "qc_report_json": "sample-01_qc_report.json",
        "qc_dashboard": "sample-01_dashboard.png",
        "channel_summary_csv": "sample-01_channel_summary.csv",
    }
    persisted = json.loads(artifacts["qc_report_json"].read_text(encoding="utf-8"))
    assert persisted == result["report"]
    assert persisted["event_count"] == 100
    fitc = next(item for item in persisted["channel_summaries"] if item["channel"] == "FITC-A")
    assert (fitc["minimum"], fitc["median"], fitc["maximum"]) == (1.0, 50.5, 100.0)
    summary = pd.read_csv(artifacts["channel_summary_csv"])
    assert summary["channel"].tolist() == ["FSC-A", "SSC-A", "Time", "FITC-A"]
    assert artifacts["qc_dashboard"].read_bytes().startswith(b"\x89PNG")
    assert json.dumps(result)


def test_run_qc_rejects_fcs_without_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = pd.DataFrame(columns=["FSC-A", "SSC-A", "Time", "FITC-A"], dtype=float)
    monkeypatch.setattr(flow_qc_utils, "load_fcs", lambda path: ({}, empty))

    with pytest.raises(ValueError, match="contains no events"):
        run_qc(tmp_path / "empty.fcs", tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="The tool launcher runs in a POSIX shell.",
)
@pytest.mark.parametrize(
    ("script", "expected_status", "expected_output"),
    [
        ("print('flow-qc ok')", 0, "flow-qc ok"),
        ("raise RuntimeError('deliberate failure')", 1, "RuntimeError: deliberate failure"),
        ("raise SystemExit(3)", 3, ""),
    ],
)
def test_tool_launcher_returns_python_exit_status(
    tmp_path: Path, script: str, expected_status: int, expected_output: str
) -> None:
    yaml = pytest.importorskip("yaml")
    tool = yaml.safe_load((Path(__file__).parent / "tool.yaml").read_text(encoding="utf-8"))
    script_path = tmp_path / "script.py"
    script_path.write_text(script + "\n", encoding="utf-8")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    command = (
        tool["code_environments"][0]["command"]
        .replace("{{scriptName}}", str(script_path).lstrip("/"))
        .replace("{{output_directory}}", str(output_dir))
    )

    completed = subprocess.run(
        ["bash", "-c", command], capture_output=True, text=True, timeout=60, check=False
    )

    assert completed.returncode == expected_status
    assert expected_output in completed.stdout


def test_rate_bin_count_cv_reflects_acquisition_pause() -> None:
    """A long pause leaves empty time bins, which must raise the rate CV."""
    steady_time = np.linspace(0, 100, 10_000)
    paused_time = np.concatenate(
        (np.linspace(0, 10, 5_000, endpoint=False), np.linspace(90, 100, 5_000))
    )
    steady = build_qc_report({}, pd.DataFrame({"Time": steady_time}))
    paused = build_qc_report({}, pd.DataFrame({"Time": paused_time}))

    assert steady["time_integrity"]["rate_bin_count_cv"] < 0.05
    assert paused["time_integrity"]["rate_bin_count_cv"] > 1.0
