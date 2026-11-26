#!/usr/bin/env python3
"""Generate publication-quality figures for the paper.

Convention (LaTeX-first layout):
  - Every figure is saved as BOTH .pdf (vector, for LaTeX) and .png (raster,
    for markdown previews / README embeds).
  - matplotlib publication style set once at module level.
  - One `plot_<name>()` function per figure. Callable in isolation.
  - Data loaded from ../experiments/*.json or *.csv — never hardcoded.
  - Output directory is `figures/` next to this script (versioned subdirs
    like `figures/v5/` when the paper is being revised).

Run:
    python3 generate_figures.py           # regenerate all figures
    python3 generate_figures.py fig1      # just one
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ── Publication style ───────────────────────────────────────────────────────
plt.rcParams.update({
    "font.size": 10,
    "font.family": "serif",
    "axes.labelsize": 11,
    "axes.titlesize": 12,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 9,
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "text.usetex": False,   # keep False unless the whole team has LaTeX-in-mpl
})

HERE = Path(__file__).parent
OUTPUT_DIR = HERE / "figures"
OUTPUT_DIR.mkdir(exist_ok=True)


def save(fig, name: str) -> None:
    """Save a figure as BOTH .pdf and .png in the output directory."""
    for ext in ("pdf", "png"):
        path = OUTPUT_DIR / f"{name}.{ext}"
        fig.savefig(path)
        print(f"  wrote {path.relative_to(HERE)}")
    plt.close(fig)


# ── Figures ─────────────────────────────────────────────────────────────────

def plot_fig1_example() -> None:
    """Example figure — replace with real content."""
    fig, ax = plt.subplots(figsize=(6, 3.5))
    x = np.linspace(0, 2 * np.pi, 200)
    ax.plot(x, np.sin(x), label=r"$\sin(x)$")
    ax.plot(x, np.cos(x), label=r"$\cos(x)$", linestyle="--")
    ax.set_xlabel("x")
    ax.set_ylabel("value")
    ax.legend(frameon=False)
    ax.grid(alpha=0.3)
    save(fig, "fig1_example")


FIGURES = {
    "fig1": plot_fig1_example,
    # add more here
}


def main() -> None:
    targets = sys.argv[1:] or list(FIGURES.keys())
    for name in targets:
        fn = FIGURES.get(name)
        if fn is None:
            print(f"unknown figure: {name}", file=sys.stderr)
            sys.exit(2)
        print(f"generating {name}…")
        fn()
    print(f"done — {len(targets)} figure(s) in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
