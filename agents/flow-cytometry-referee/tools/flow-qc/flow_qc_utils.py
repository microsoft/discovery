"""Utilities for technical quality review of standard FCS flow-cytometry files.

The functions in this module intentionally report measurement and metadata facts.
They do not assign cell types, make clinical predictions, or validate a laboratory assay.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from flowio import FlowData
from flowio.exceptions import FCSParsingError
from sklearn.ensemble import IsolationForest


def load_fcs(path: str | Path) -> tuple[dict[str, Any], pd.DataFrame]:
    """Read an FCS file into metadata and an events-by-channel DataFrame."""
    parse_warnings: list[str] = []
    try:
        flow_data = FlowData(str(path))
    except FCSParsingError as error:
        if "offset" not in str(error).lower():
            raise
        flow_data = FlowData(str(path), ignore_offset_error=True)
        parse_warnings.append(
            "The FCS data offset was inconsistent; parsed with FlowIO's offset-recovery option."
        )
    channel_numbers = sorted(flow_data.channels, key=lambda value: int(value))
    channel_names = [
        flow_data.channels[number].get("pnn") or f"channel_{number}"
        for number in channel_numbers
    ]
    event_count = int(flow_data.event_count)
    channel_count = len(channel_names)
    events = np.asarray(flow_data.events, dtype=float).reshape(event_count, channel_count)
    metadata = {str(key): value for key, value in flow_data.text.items()}
    metadata["_channel_ranges"] = {
        name: flow_data.channels[number].get("pnr")
        for name, number in zip(channel_names, channel_numbers, strict=True)
    }
    metadata["_channel_stains"] = {
        name: flow_data.channels[number].get("pns")
        for name, number in zip(channel_names, channel_numbers, strict=True)
    }
    metadata["_parse_warnings"] = parse_warnings
    return metadata, pd.DataFrame(events, columns=channel_names)


def _channel_roles(events: pd.DataFrame, stains: dict[str, Any]) -> dict[str, list[str]]:
    """Classify measurement channels for QC display, without biological inference."""
    roles = {"scatter": [], "fluorescence": [], "time": [], "index": [], "auxiliary": []}
    for name in events.columns:
        normalized = name.lower().replace(" ", "")
        if normalized in {"time", "acquisition_time"} or normalized.endswith("time"):
            roles["time"].append(name)
        elif "event" in normalized or normalized.endswith("index"):
            roles["index"].append(name)
        elif normalized.startswith(("fsc", "ssc")):
            roles["scatter"].append(name)
        elif normalized.startswith(("width", "pulsewidth")):
            roles["auxiliary"].append(name)
        else:
            roles["fluorescence"].append(name)
    return roles


def _compensation_summary(metadata: dict[str, Any], events: pd.DataFrame) -> dict[str, Any]:
    raw = next(
        (value for key, value in metadata.items() if key.lower().replace("$", "") in {"spillover", "spill"}),
        None,
    )
    if raw is None:
        return {"status": "absent", "matrix_channels": []}
    tokens = [token.strip() for token in str(raw).split(",")]
    try:
        dimension = int(tokens[0])
    except (IndexError, ValueError):
        return {"status": "present_unparsed", "matrix_channels": []}
    channels = tokens[1 : dimension + 1]
    values = tokens[dimension + 1 :]
    missing = [channel for channel in channels if channel not in events.columns]
    valid = len(channels) == dimension and len(values) == dimension * dimension and not missing
    return {
        "status": "present_valid" if valid else "present_invalid",
        "matrix_channels": channels,
        "matrix_dimension": dimension,
        "channels_missing_from_fcs": missing,
    }


def _channel_summary(
    events: pd.DataFrame, ranges: dict[str, Any], range_check_channels: set[str]
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for name in events.columns:
        values = events[name].to_numpy(dtype=float)
        finite = values[np.isfinite(values)]
        channel_range = ranges.get(name)
        try:
            upper_limit = float(channel_range)
        except (TypeError, ValueError):
            upper_limit = None
        at_declared_range_fraction = (
            float(np.mean(finite >= upper_limit))
            if name in range_check_channels and upper_limit and finite.size
            else None
        )
        summaries.append(
            {
                "channel": name,
                "finite_fraction": float(np.mean(np.isfinite(values))),
                "minimum": float(np.min(finite)) if finite.size else None,
                "p01": float(np.percentile(finite, 1)) if finite.size else None,
                "median": float(np.median(finite)) if finite.size else None,
                "p99": float(np.percentile(finite, 99)) if finite.size else None,
                "maximum": float(np.max(finite)) if finite.size else None,
                "at_declared_range_fraction": at_declared_range_fraction,
            }
        )
    return summaries


def _outlier_summary(
    events: pd.DataFrame, measurement_channels: list[str], random_state: int = 0
) -> dict[str, Any]:
    """Return an unsupervised event-outlier metric, never a biological classification."""
    numeric = events[measurement_channels].select_dtypes(include=[np.number])
    numeric = numeric.replace([np.inf, -np.inf], np.nan).dropna(axis=0)
    if len(numeric) < 100 or numeric.shape[1] == 0:
        return {"available": False, "reason": "Need at least 100 complete numeric events."}
    positions = np.linspace(0, len(numeric) - 1, min(len(numeric), 50_000), dtype=int)
    sample = numeric.iloc[positions, : min(numeric.shape[1], 16)]
    standardized = (sample - sample.median()) / sample.std(ddof=0).replace(0, 1)
    model = IsolationForest(contamination="auto", random_state=random_state, n_estimators=100)
    labels = model.fit_predict(standardized)
    return {
        "available": True,
        "events_scored": int(len(sample)),
        "channels_scored": list(sample.columns),
        "outlier_fraction": float(np.mean(labels == -1)),
        "interpretation": "Exploratory unusual multichannel measurements, not cell identities, sample classes, or a validated QC threshold.",
    }


def build_qc_report(metadata: dict[str, Any], events: pd.DataFrame) -> dict[str, Any]:
    """Create a JSON-serializable, evidence-only FCS technical QC report."""
    roles = _channel_roles(events, metadata.get("_channel_stains", {}))
    time_columns = roles["time"]
    time_integrity: dict[str, Any] = {"available": bool(time_columns)}
    if time_columns:
        values = events[time_columns[0]].to_numpy(dtype=float)
        finite = values[np.isfinite(values)]
        differences = np.diff(finite)
        positive_gaps = differences[differences > 0]
        if finite.size > 1 and finite[-1] > finite[0]:
            counts, _ = np.histogram(finite, bins=20)
            nonempty_counts = counts[counts > 0]
            rate_bin_count_cv = (
                float(np.std(nonempty_counts) / np.mean(nonempty_counts)) if nonempty_counts.size else None
            )
        else:
            rate_bin_count_cv = None
        time_integrity.update(
            {
                "channel": time_columns[0],
                "nondecreasing_fraction": float(np.mean(differences >= 0)) if len(finite) > 1 else None,
                "negative_fraction": float(np.mean(finite < 0)) if len(finite) else None,
                "reset_count": int(np.sum(differences < 0)),
                "largest_positive_gap": float(np.max(positive_gaps)) if positive_gaps.size else None,
                "median_positive_gap": float(np.median(positive_gaps)) if positive_gaps.size else None,
                "rate_bin_count_cv": rate_bin_count_cv,
            }
        )
    compensation = _compensation_summary(metadata, events)
    range_check_channels = set(roles["scatter"] + roles["fluorescence"])
    outlier_channels = roles["scatter"] + roles["fluorescence"]
    return {
        "scope": "Technical FCS quality checks only; not biological, clinical, or regulatory validation.",
        "event_count": int(len(events)),
        "channel_count": int(events.shape[1]),
        "channels": list(events.columns),
        "compensation_metadata_present": compensation["status"] != "absent",
        "compensation": compensation,
        "channel_roles": roles,
        "parse_warnings": metadata.get("_parse_warnings", []),
        "time_integrity": time_integrity,
        "channel_summaries": _channel_summary(
            events, metadata.get("_channel_ranges", {}), range_check_channels
        ),
        "outlier_summary": _outlier_summary(events, outlier_channels),
        "limitations": [
            "FCS metadata cannot establish that compensation was correct or that controls were appropriate.",
            "Gate quality requires the gating plan and control evidence in addition to event measurements.",
        ],
    }


def write_qc_artifacts(
    report: dict[str, Any], events: pd.DataFrame, output_dir: str | Path, stem: str = "flow_qc"
) -> dict[str, str]:
    """Write a technical QC dashboard and channel-summary CSV, returning their paths."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    dashboard = target / f"{stem}_dashboard.png"
    summary_csv = target / f"{stem}_channel_summary.csv"
    pd.DataFrame(report["channel_summaries"]).to_csv(summary_csv, index=False)

    roles = report["channel_roles"]
    fsc = next((name for name in roles["scatter"] if name.lower().startswith("fsc")), None)
    ssc = next((name for name in roles["scatter"] if name.lower().startswith("ssc")), None)
    time = roles["time"][0] if roles["time"] else None
    signal = roles["fluorescence"][0] if roles["fluorescence"] else None
    sample = events.iloc[: min(len(events), 20_000)]
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))

    scatter = axes[0, 0]
    if fsc and ssc:
        scatter.scatter(sample[fsc], sample[ssc], s=1, alpha=0.18, rasterized=True)
        scatter.set(xlabel=fsc, ylabel=ssc, title="Forward vs. side scatter")
    else:
        scatter.text(0.5, 0.5, "FSC/SSC channels not found", ha="center", va="center")
        scatter.set_axis_off()

    distribution = axes[0, 1]
    values = sample[signal].to_numpy(dtype=float) if signal else np.array([])
    values = values[np.isfinite(values)]
    if signal and values.size:
        distribution.hist(values, bins=80, color="#3478bf", alpha=0.85)
        distribution.set(xlabel=signal, ylabel="Events", title=f"Fluorescence distribution: {signal}")
    else:
        distribution.text(0.5, 0.5, "Fluorescence channel not found", ha="center", va="center")
        distribution.set_axis_off()

    trend = axes[1, 0]
    if time:
        trend.plot(sample.index, sample[time], linewidth=0.6, color="#4d8c57")
        trend.set(xlabel="Event index", ylabel=time, title="Acquisition time trend")
    else:
        trend.text(0.5, 0.5, "Time channel not found", ha="center", va="center")
        trend.set_axis_off()

    saturation = axes[1, 1]
    summaries = report["channel_summaries"]
    labels = [item["channel"] for item in summaries]
    summaries = [item for item in summaries if item["channel"] in set(roles["scatter"] + roles["fluorescence"])]
    labels = [item["channel"] for item in summaries]
    fractions = [item["at_declared_range_fraction"] or 0.0 for item in summaries]
    saturation.bar(range(len(labels)), fractions, color="#c45a3c")
    saturation.set_xticks(range(len(labels)), labels, rotation=40, ha="right", fontsize=8)
    saturation.set(
        ylabel="Fraction at or above declared range",
        title="Measurements at declared range limit",
    )
    saturation.set_ylim(0, max(0.01, max(fractions, default=0.0) * 1.15))

    fig.suptitle("Flow cytometry technical QC dashboard", fontweight="bold")
    fig.tight_layout()
    fig.savefig(dashboard, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return {"qc_dashboard": str(dashboard), "channel_summary_csv": str(summary_csv)}
