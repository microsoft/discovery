"""Illustrative figures written by the worker. Never inputs to a verdict."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from . import foamio

RES = re.compile(r"Solving for (\w+), Initial residual = ([^,\s]+)")


def render(case: Path, d, out: Path) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    logs = sorted(case.glob("log.foamRun*"))
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in logs)
    hist: dict[str, list[float]] = {}
    for name, val in RES.findall(text):
        try:
            hist.setdefault(name, []).append(float(val))
        except ValueError:
            pass
    if hist:
        fig, ax = plt.subplots(figsize=(7, 4))
        for name, vals in sorted(hist.items()):
            ax.semilogy(np.maximum(vals, 1e-300), label=name, lw=0.8)
        ax.set_xlabel("linear solve"), ax.set_ylabel("initial residual"), ax.legend(fontsize=7)
        fig.tight_layout(), fig.savefig(out / "residuals.png", dpi=110), plt.close(fig)
        written.append("residuals.png")
    series = [(f"flux_{p}", f"flux {p}") for p in d.patches] + [("domain_mass", "domain mass")]
    series += [(f"q_{q.name}", f"quantity {q.name}") for q in d.quantities]
    curves = []
    for key, label in series:
        segs = foamio.read_monitor(case, key)
        if segs:
            t = np.concatenate([s[1][:, 0] for s in segs])
            v = np.concatenate([s[1][:, 1] for s in segs])
            curves.append((label, t, v))
    if curves:
        fig, axes = plt.subplots(len(curves), 1, figsize=(7, 1.8 * len(curves)), sharex=True, squeeze=False)
        for ax, (label, t, v) in zip(axes[:, 0], curves):
            ax.plot(t, v, lw=0.8)
            ax.set_ylabel(label, fontsize=7)
        axes[-1, 0].set_xlabel("time")
        fig.tight_layout(), fig.savefig(out / "monitors.png", dpi=110), plt.close(fig)
        written.append("monitors.png")
    try:
        centres, _ = foamio.read_field(case / "0/C")
        times = [p for t, p in foamio.time_dirs(case) if t > 0]
        if times:
            spread = np.ptp(centres, axis=0)
            ax_idx = [int(i) for i in np.argsort(spread)[::-1][:2]]
            for f in d.fields[:4]:
                v, _ = foamio.read_field(times[-1] / f.name, len(centres))
                mag = np.linalg.norm(v, axis=1) if v.ndim == 2 else v
                fig, ax = plt.subplots(figsize=(7, 3.5))
                sc = ax.scatter(centres[:, ax_idx[0]], centres[:, ax_idx[1]], c=mag, s=2, marker="s",
                                cmap="viridis", linewidths=0)
                fig.colorbar(sc, ax=ax, label=f"{f.name} [{f.unit}]")
                ax.set_aspect("equal"), ax.set_title(f"{f.name} at t = {times[-1].name} (cell centres)", fontsize=9)
                fig.tight_layout(), fig.savefig(out / f"field_{f.name}.png", dpi=110), plt.close(fig)
                written.append(f"field_{f.name}.png")
    except Exception:  # figures are optional; evidence extraction already ran
        pass
    return written
