"""Publication-quality plots for BO/DoE workflows (headless Agg backend)."""

from __future__ import annotations

from typing import Optional, Sequence

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from acquisition import pareto_front  # noqa: E402

__all__ = [
    "plot_convergence",
    "plot_pareto",
    "plot_design",
    "plot_parity",
    "plot_ternary_mixture",
    "plot_benchmark",
]

_DPI = 150


def _directed_front(Y: np.ndarray, sign: np.ndarray) -> np.ndarray:
    """Pareto front in native units; ``sign`` is +1 to minimize, -1 to maximize."""
    return pareto_front(np.asarray(Y, dtype=float) * sign) * sign


def plot_convergence(traces: dict, output_file: str = "convergence.png",
                     title: str = "Optimization convergence",
                     ylabel: str = "Best scalarized objective (lower is better)",
                     log_y: bool = False) -> str:
    """Plot best-so-far traces for one or more methods.

    Args:
        traces: Mapping ``method -> list[float]`` or ``method -> (n_runs, n_evals)``
            array. Arrays are shown as median with an inter-quartile band.
        output_file: Destination path.
    """
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for name, tr in traces.items():
        arr = np.atleast_2d(np.asarray(tr, dtype=float))
        x = np.arange(1, arr.shape[1] + 1)
        med = np.median(arr, axis=0)
        ax.plot(x, med, lw=2, label=name)
        if arr.shape[0] > 1:
            lo = np.percentile(arr, 25, axis=0)
            hi = np.percentile(arr, 75, axis=0)
            ax.fill_between(x, lo, hi, alpha=0.18)
    ax.set_xlabel("Experiments evaluated")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if log_y:
        ax.set_yscale("log")
    ax.grid(alpha=0.3)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(output_file, dpi=_DPI)
    plt.close(fig)
    return output_file


def plot_pareto(Y: np.ndarray, objective_names: Sequence,
                output_file: str = "pareto.png",
                highlight: Optional[np.ndarray] = None,
                title: str = "Objective space and Pareto front",
                directions: Optional[Sequence[str]] = None) -> str:
    """Scatter the observed objective space and highlight the Pareto front.

    For more than two objectives a pairwise grid of the first three is drawn.

    Args:
        Y: ``(n, n_obj)`` responses in native units.
        objective_names: Axis labels, or the :class:`optimize.Objective` list
            itself -- in which case each objective's direction is used.
        output_file: Destination path.
        highlight: Optional points (e.g. predicted suggestions) to mark.
        title: Figure title.
        directions: ``"minimize"``/``"maximize"`` per objective. Defaults to the
            directions of ``Objective`` instances, else all ``"minimize"``.
            Passing the wrong directions draws the wrong front.
    """
    Y = np.atleast_2d(np.asarray(Y, dtype=float))
    m = Y.shape[1]
    names = [getattr(o, "name", o) for o in objective_names]
    if directions is None:
        directions = [getattr(o, "direction", "minimize") for o in objective_names]
    if len(directions) != m or any(d not in ("minimize", "maximize")
                                   for d in directions):
        raise ValueError("directions must give 'minimize' or 'maximize' for "
                         "every objective")
    sign = np.array([1.0 if d == "minimize" else -1.0 for d in directions])
    pairs = [(0, 1)] if m == 2 else [(i, j) for i in range(min(m, 3))
                                     for j in range(i + 1, min(m, 3))]
    fig, axes = plt.subplots(1, len(pairs), figsize=(5.2 * len(pairs), 4.4),
                             squeeze=False)
    for ax, (i, j) in zip(axes[0], pairs):
        ax.scatter(Y[:, i], Y[:, j], s=26, c="#9bb7d4", label="observed",
                   edgecolors="none")
        front = _directed_front(Y[:, [i, j]], sign[[i, j]])
        ax.plot(front[:, 0], front[:, 1], "o-", c="#c0392b", ms=6, lw=1.6,
                label="Pareto front")
        if highlight is not None:
            H = np.atleast_2d(highlight)
            ax.scatter(H[:, i], H[:, j], marker="*", s=180, c="#1e8449",
                       label="selected", zorder=5)
        ax.set_xlabel(names[i])
        ax.set_ylabel(names[j])
        ax.grid(alpha=0.3)
    axes[0][0].legend(frameon=False)
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(output_file, dpi=_DPI)
    plt.close(fig)
    return output_file


def plot_design(X: np.ndarray, names: Sequence[str],
                output_file: str = "design.png",
                title: str = "Design matrix") -> str:
    """Pairwise scatter matrix of a design, with marginal histograms."""
    X = np.atleast_2d(np.asarray(X, dtype=float))
    d = X.shape[1]
    fig, axes = plt.subplots(d, d, figsize=(2.1 * d, 2.1 * d), squeeze=False)
    for i in range(d):
        for j in range(d):
            ax = axes[i][j]
            if i == j:
                ax.hist(X[:, i], bins=min(12, max(4, len(X) // 3)),
                        color="#5b8db8", edgecolor="white")
            else:
                ax.scatter(X[:, j], X[:, i], s=18, c="#34495e", alpha=0.75,
                           edgecolors="none")
            if i == d - 1:
                ax.set_xlabel(names[j], fontsize=9)
            if j == 0:
                ax.set_ylabel(names[i], fontsize=9)
            ax.tick_params(labelsize=7)
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(output_file, dpi=_DPI)
    plt.close(fig)
    return output_file


def plot_parity(y_true, y_pred, output_file: str = "parity.png",
                title: str = "Surrogate parity", xlabel: str = "Measured",
                ylabel: str = "Predicted") -> str:
    """Parity plot with an R^2 annotation for surrogate validation."""
    y_true = np.asarray(y_true, dtype=float).ravel()
    y_pred = np.asarray(y_pred, dtype=float).ravel()
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    fig, ax = plt.subplots(figsize=(4.8, 4.6))
    ax.scatter(y_true, y_pred, s=30, c="#2e6da4", edgecolors="white")
    lims = [min(y_true.min(), y_pred.min()), max(y_true.max(), y_pred.max())]
    ax.plot(lims, lims, "k--", lw=1)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(f"{title}\n$R^2$ = {r2:.3f}, RMSE = {rmse:.4g}")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_file, dpi=_DPI)
    plt.close(fig)
    return output_file


def plot_ternary_mixture(X: np.ndarray, names: Sequence[str],
                         output_file: str = "ternary.png",
                         values: Optional[np.ndarray] = None,
                         title: str = "Mixture design") -> str:
    """Ternary plot of a 3-component mixture design (or the first 3 of many)."""
    X = np.atleast_2d(np.asarray(X, dtype=float))[:, :3]
    tot = X.sum(axis=1, keepdims=True)
    tot[tot == 0] = 1.0
    P = X / tot
    x = 0.5 * (2 * P[:, 1] + P[:, 2])
    y = (np.sqrt(3) / 2) * P[:, 2]
    fig, ax = plt.subplots(figsize=(5.4, 5.0))
    tri = np.array([[0, 0], [1, 0], [0.5, np.sqrt(3) / 2], [0, 0]])
    ax.plot(tri[:, 0], tri[:, 1], "k-", lw=1)
    sc = ax.scatter(x, y, c=values if values is not None else "#2e6da4",
                    cmap="viridis", s=45, edgecolors="white")
    if values is not None:
        fig.colorbar(sc, ax=ax, shrink=0.8)
    ax.text(-0.03, -0.04, names[0], ha="right")
    ax.text(1.03, -0.04, names[1], ha="left")
    ax.text(0.5, np.sqrt(3) / 2 + 0.03, names[2], ha="center")
    ax.set_axis_off()
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(output_file, dpi=_DPI)
    plt.close(fig)
    return output_file


def plot_benchmark(summary: dict, output_file: str = "benchmark.png",
                   title: str = "Budget to reach target") -> str:
    """Bar chart of evaluations-to-target (or final best) per method."""
    names = list(summary.keys())
    vals = [summary[n] for n in names]
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    bars = ax.bar(names, vals, color=["#2e6da4", "#c0392b", "#f0932b", "#1e8449"][
        : len(names)])
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height(),
                f"{v:.3g}", ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("Evaluations")
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_file, dpi=_DPI)
    plt.close(fig)
    return output_file
