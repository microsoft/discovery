#!/usr/bin/env python3
"""Contract-driven functional I/O pad connectivity preflight.

This check distinguishes physical pad presence from an electrically functional
pad boundary. It is intentionally small and fail-closed: a functional-padframe
contract without an inspectable netlist or explicit signal-pad mapping cannot
pass.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_INSTANCE_RE = re.compile(
    r"(?ms)(?P<cell>[A-Za-z_][\w$]*)\s+(?P<inst>[A-Za-z_][\w$]*)\s*\("
    r"(?P<body>.*?)\);"
)
_CONN_RE = re.compile(r"\.(?P<pin>[A-Za-z_][\w$]*)\s*\(\s*(?P<net>[^)]+?)\s*\)")


def _load_netlist(params: dict[str, Any]) -> str:
    if isinstance(params.get("netlist_text"), str):
        return params["netlist_text"]
    path = params.get("netlist_path")
    if not path:
        raise ValueError("functional_padframe requires netlist_path or netlist_text")
    return Path(path).read_text(encoding="utf-8", errors="replace")


def _instances(text: str) -> list[dict[str, Any]]:
    out = []
    for match in _INSTANCE_RE.finditer(text):
        conns = {m.group("pin"): m.group("net").strip()
                 for m in _CONN_RE.finditer(match.group("body"))}
        out.append({"cell": match.group("cell"),
                    "instance": match.group("inst"),
                    "connections": conns})
    return out


def check_pad_connectivity(params: dict[str, Any]) -> dict[str, Any]:
    mode = params.get("io_boundary", {}).get("mode", params.get("mode"))
    if mode not in {"functional_padframe", "core_only"}:
        raise ValueError("io_boundary.mode must be functional_padframe or core_only")

    text = _load_netlist(params)
    instances = _instances(text)
    by_instance = {item["instance"]: item for item in instances}
    required = params.get("signal_pads") or []
    outputs = params.get("outputs") or []
    findings: list[dict[str, Any]] = []

    if mode == "functional_padframe" and not required:
        findings.append({"code": "MISSING_SIGNAL_PAD_CONTRACT",
                         "detail": "functional_padframe has no signal_pads mapping"})

    connected = 0
    for pad in required:
        instance = pad.get("instance")
        signal_pin = pad.get("signal_pin", "PAD")
        expected_net = pad.get("net")
        item = by_instance.get(instance)
        if item is None:
            findings.append({"code": "MISSING_PAD_INSTANCE", "instance": instance})
            continue
        actual_net = item["connections"].get(signal_pin)
        if not actual_net or actual_net in {"", "1'b0", "1'b1", "NC", "unused"}:
            findings.append({"code": "DANGLING_SIGNAL_PAD", "instance": instance,
                             "signal_pin": signal_pin, "actual_net": actual_net})
            continue
        if expected_net and actual_net != expected_net:
            findings.append({"code": "PAD_NET_MISMATCH", "instance": instance,
                             "expected_net": expected_net, "actual_net": actual_net})
            continue
        connected += 1

    # A direct core-cell output is forbidden when the contract requires a
    # functional pad. Callers may supply the expected output nets and the
    # driver cell inventory from a netlist parser/database.
    direct = params.get("direct_core_outputs") or []
    for output in direct:
        if output in outputs:
            findings.append({"code": "DIRECT_CORE_OUTPUT_WITHOUT_PAD",
                             "output": output})

    required_count = len(required)
    verdict = "pass" if not findings and connected == required_count else "fail"
    return {
        "tool": "pad-connectivity-preflight",
        "status": "completed" if verdict == "pass" else "failed",
        "mode": mode,
        "results": {
            "required_signal_pad_count": {"value": required_count, "unit": "count"},
            "functional_signal_pad_count": {"value": connected, "unit": "count"},
            "dangling_signal_pad_count": {"value": sum(
                f["code"] == "DANGLING_SIGNAL_PAD" for f in findings), "unit": "count"},
            "signal_net_mismatch_count": {"value": sum(
                f["code"] == "PAD_NET_MISMATCH" for f in findings), "unit": "count"},
        },
        "findings": findings,
        "validation": {
            "verdict": verdict,
            "gate_closed": verdict == "pass",
            "note": ("all required signal pads are electrically connected"
                     if verdict == "pass" else
                     "functional pad boundary is incomplete; do not proceed to physical implementation"),
        },
    }
