"""Bayesian optimization engine: ask/tell, batch suggestion, and closed loops.

The main entry points are:

* :class:`BayesianOptimizer` -- stateful ask/tell optimizer. Feed it whatever
  data you already have (``tell``) and ask for the next experiments (``ask``).
  This is the API to use for a human-in-the-loop lab campaign.
* :func:`suggest_next` -- one-shot convenience wrapper around the above.
* :func:`run_bo_campaign` -- fully closed loop against a callable objective
  (a simulator or a fitted surrogate), used for benchmarking and for in-silico
  screening.
* :func:`run_random_search` and :func:`run_de_baseline` -- baselines for honest
  benchmarking of the BO policy.

Objectives are declared with :class:`Objective`, which records the direction
(minimize/maximize), an optional hard specification threshold, and a scalarizing
weight. Internally everything is converted to minimization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

import numpy as np

from acquisition import (ACQUISITIONS, acquisition, canonical_acquisition,
                         chebyshev_scalarization,
                         expected_hypervolume_improvement, hypervolume,
                         pareto_front, probability_below_threshold,
                         random_weights, rank_normalize, to_utility)
from models import GPSurrogate, resolve_backend
from space import ParameterSpace, make_space

__all__ = [
    "Objective",
    "BayesianOptimizer",
    "suggest_next",
    "select_from_library",
    "select_diverse_subset",
    "scalarize",
    "run_bo_campaign",
    "run_random_search",
    "run_de_baseline",
]


@dataclass
class Objective:
    """Declaration of a single response to optimize.

    Args:
        name: Response name (must match a column of the observation matrix).
        direction: ``"minimize"`` or ``"maximize"``.
        threshold: Optional hard specification. For ``minimize`` the target is
            ``y <= threshold``; for ``maximize`` it is ``y >= threshold``.
            Thresholded objectives are used as probabilistic constraints and
            also reported in the feasibility summary.
        weight: Relative importance used by scalarizing strategies.
        transform: Output transform applied before GP modelling. Defaults to
            ``"auto"``, which inspects the data at ``tell()`` time and selects
            ``"log1p"`` for strictly non-negative responses spanning more than
            one order of magnitude, and ``None`` otherwise.

            This is deliberately **not** opt-in. Modelling a response like
            viscosity (92-42 444 cP) on a raw scale makes the GP place
            probability mass on negative viscosities, which corrupts the
            acquisition and wastes the campaign. Because it was the single
            highest-impact setting in validation, the agent detects it rather
            than relying on the user to remember. Pass an explicit value
            (``None``, ``"log"``, ``"log1p"``, ``"sqrt"``) to override.

            Pareto dominance is invariant under monotone transforms, so
            multi-objective results are unaffected.
    """

    name: str
    direction: str = "minimize"
    threshold: Optional[float] = None
    weight: float = 1.0
    transform: Optional[str] = "auto"

    _FWD = {
        None: (lambda y: y, lambda z: z),
        "none": (lambda y: y, lambda z: z),
        "log": (lambda y: np.log(np.maximum(y, 1e-12)), np.exp),
        "log1p": (lambda y: np.log1p(np.maximum(y, -1 + 1e-12)), np.expm1),
        "sqrt": (lambda y: np.sqrt(np.maximum(y, 0.0)), lambda z: np.maximum(z, 0) ** 2),
    }

    def __post_init__(self):
        if self.direction not in ("minimize", "maximize"):
            raise ValueError("direction must be 'minimize' or 'maximize'")
        if self.transform != "auto" and self.transform not in self._FWD:
            raise ValueError(f"unknown transform '{self.transform}'; options: "
                             f"'auto', None, {sorted(k for k in self._FWD if k)}")
        object.__setattr__(self, "_resolved", None if self.transform == "auto"
                           else self.transform)
        object.__setattr__(self, "_auto", self.transform == "auto")

    # ------------------------------------------------------------- transform
    @property
    def active_transform(self) -> Optional[str]:
        """The transform actually in use, or ``"auto"`` if not yet resolved.

        Use :meth:`forward` / :meth:`to_min` rather than reading this to decide
        how to scale data -- they resolve automatically.
        """
        if getattr(self, "_auto", False):
            return "auto"
        return getattr(self, "_resolved", self.transform)

    def resolve_transform(self, y: np.ndarray) -> Optional[str]:
        """Auto-detect and latch the output transform from observed values.

        Chooses ``log1p`` when the response is non-negative and its dynamic
        range spans more than a decade -- the regime where an untransformed GP
        predicts physically impossible negative values.

        Args:
            y: Observed values for this objective, in native units.

        Returns:
            The transform name now in force (possibly ``None``).
        """
        if not getattr(self, "_auto", False):
            return self._active()
        vals = np.asarray(y, dtype=float)
        vals = vals[np.isfinite(vals)]
        chosen = None
        if len(vals) >= 3 and np.all(vals >= 0):
            pos = vals[vals > 0]
            if len(pos) >= 3 and pos.max() / max(pos.min(), 1e-12) >= 10.0:
                chosen = "log1p"
        object.__setattr__(self, "_resolved", chosen)
        object.__setattr__(self, "_auto", False)      # latch: stay consistent
        return chosen

    def _active(self) -> Optional[str]:
        """Resolved transform key for indexing ``_FWD``."""
        return getattr(self, "_resolved", self.transform)

    @property
    def sign(self) -> float:
        """+1 if already a minimization objective, -1 if it must be flipped."""
        return 1.0 if self.direction == "minimize" else -1.0

    def forward(self, y: np.ndarray) -> np.ndarray:
        """Apply the output transform (native units -> modelling units).

        If the transform is still ``"auto"`` it is resolved from ``y`` here.
        Resolving lazily on first use -- rather than only inside
        ``BayesianOptimizer.fit`` -- means no code path can silently score on
        the raw scale. An earlier revision had exactly that defect: benchmark
        scoring built fresh ``Objective`` instances and never fitted a model,
        so every hypervolume was computed untransformed.
        """
        y = np.asarray(y, dtype=float)
        if getattr(self, "_auto", False):
            self.resolve_transform(y)
        return self._FWD[self._active()][0](y)

    def inverse(self, z: np.ndarray) -> np.ndarray:
        """Undo the output transform (modelling units -> native units)."""
        return self._FWD[self._active()][1](np.asarray(z, dtype=float))

    def to_min(self, y: np.ndarray) -> np.ndarray:
        """Convert observations to the internal (transformed, minimized) scale."""
        return self.sign * self.forward(y)

    def from_min(self, z: np.ndarray) -> np.ndarray:
        """Convert internal values back to native units."""
        return self.inverse(self.sign * np.asarray(z, dtype=float))

    def internal_threshold(self) -> Optional[float]:
        if self.threshold is None:
            return None
        return float(self.sign * self._FWD[self._active()][0](
            np.asarray(self.threshold, dtype=float)))


@dataclass(frozen=True)
class _AskContext:
    """Everything stochastic about scoring one candidate, frozen up front.

    Creating this object once per pick -- rather than letting the scoring code
    redraw weights and Monte-Carlo seeds on every call -- is what makes the
    acquisition surface a fixed function that SLSQP can legitimately optimize.

    Attributes:
        weights: Scalarization weights (ParEGO draws these randomly per pick).
        seed: Seed for any Monte-Carlo estimate (EHVI) or stochastic acquisition.
        Yi: Observations in the internal minimization orientation.
        Yi_model: Posterior means at the observed designs, same orientation.
            Hypervolume-based acquisitions use this rather than ``Yi`` so that
            measurement noise does not inflate the reference front.
        y_min: Per-objective minimum used to normalize the scalarization.
        y_max: Per-objective maximum used to normalize the scalarization.
    """

    weights: np.ndarray
    seed: int
    Yi: np.ndarray
    Yi_model: np.ndarray
    y_min: np.ndarray
    y_max: np.ndarray


class BayesianOptimizer:
    """GP-based Bayesian optimizer with mixture-aware candidate generation.

    Args:
        space: The design space (box or mixture).
        objectives: One or more :class:`Objective` declarations. With a single
            objective the optimizer uses EI/LogEI/UCB; with several it uses
            ParEGO scalarization (default) or EHVI.
        acquisition_fn: ``"auto"``, ``"ei"``, ``"logei"``, ``"pi"``, ``"ucb"``,
            ``"thompson"``, ``"parego"`` or ``"ehvi"``.
        backend: GP backend (``"auto"``, ``"botorch"``, ``"sklearn"``).
        seed: RNG seed for reproducible suggestions.
        n_candidates: Size of the candidate pool used to optimize the
            acquisition before local refinement.
        refine: Run a gradient-free local polish (SLSQP) on the best candidates.
        beta: Exploration coefficient for UCB.
        xi: Exploration margin for EI/PI.
        ref_point: Reference point (native units) for hypervolume-based
            acquisitions and reporting. Inferred from the data when omitted.
        ehvi_prescreen: Number of candidates kept for exact EHVI evaluation
            after a cheap ParEGO pre-screen (EHVI is far more expensive).
        ehvi_mc_samples: Posterior samples per candidate for EHVI.

    Example:
        >>> from space import make_mixture_space
        >>> sp = make_mixture_space(["A", "B", "C"], total=10.0)
        >>> opt = BayesianOptimizer(sp, [Objective("y", "minimize")], seed=0)
        >>> X = sp.sample(8, seed=1); Y = (X[:, :1] - 3.0) ** 2
        >>> opt.tell(X, Y)                      # doctest: +ELLIPSIS
        <optimize.BayesianOptimizer object at ...>
        >>> opt.ask(2).shape
        (2, 3)
    """

    def __init__(self, space: ParameterSpace, objectives: Sequence[Objective],
                 acquisition_fn: str = "auto", backend: str = "auto",
                 seed: Optional[int] = None, n_candidates: int = 4096,
                 refine: bool = True, beta: float = 2.0, xi: float = 0.01,
                 ref_point: Optional[Sequence[float]] = None,
                 ehvi_prescreen: int = 128, ehvi_mc_samples: int = 32,
                 min_success_prob: float = 0.5):
        self.space = space
        self.objectives = list(objectives)
        if not self.objectives:
            raise ValueError("at least one Objective is required")
        self.backend = resolve_backend(backend)
        if acquisition_fn != "auto":
            acquisition_fn = canonical_acquisition(acquisition_fn)
            if (acquisition_fn in ("parego", "ehvi")
                    and len(self.objectives) < 2):
                raise ValueError(f"acquisition '{acquisition_fn}' needs two or "
                                 "more objectives")
        self.acquisition_fn = acquisition_fn
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.n_candidates = int(n_candidates)
        self.refine = refine
        self.beta = beta
        self.xi = xi
        self.ehvi_prescreen = int(ehvi_prescreen)
        self.ehvi_mc_samples = int(ehvi_mc_samples)
        self.min_success_prob = float(min_success_prob)
        self.ref_point = None if ref_point is None else np.asarray(ref_point, float)
        self.X = np.empty((0, space.dim))
        self.Y = np.empty((0, len(self.objectives)))
        self.X_all = np.empty((0, space.dim))
        self.success_all = np.empty(0, dtype=bool)
        self._models: list[GPSurrogate] = []
        self._success_clf = None
        self._scale = 1.0
        self._dirty = True

    # -------------------------------------------------------------- data I/O
    @property
    def n_obs(self) -> int:
        return len(self.X)

    @property
    def multi_objective(self) -> bool:
        return len(self.objectives) > 1

    def tell(self, X: np.ndarray, Y: np.ndarray) -> "BayesianOptimizer":
        """Add observations. ``Y`` is ``(n, n_objectives)`` in native units.

        Rows containing ``NaN`` responses are treated as **failed experiments**,
        not as missing data. A formulation that would not cure, a reaction that
        did not go, a synthesis that gave no product -- these are strong signals
        about a region of the design space. They are recorded and used to fit a
        success classifier whose predicted probability multiplies the
        acquisition, steering suggestions away from regions likely to fail,
        while still being excluded from the GP regression (which has no valid
        response value to learn from).

        Args:
            X: ``(n, d)`` inputs in native units.
            Y: ``(n, n_objectives)`` responses; ``NaN`` marks a failure.
        """
        X = np.atleast_2d(np.asarray(X, dtype=float))
        Y = np.asarray(Y, dtype=float)
        if Y.ndim == 1:
            Y = Y.reshape(-1, 1)
        if Y.shape[1] != len(self.objectives):
            raise ValueError(
                f"Y has {Y.shape[1]} columns but {len(self.objectives)} objectives "
                "were declared")
        if len(X) != len(Y):
            raise ValueError("X and Y must have the same number of rows")
        valid_x = np.all(np.isfinite(X), axis=1)
        success = np.all(np.isfinite(Y), axis=1) & valid_x
        self.X_all = np.vstack([self.X_all, X[valid_x]])
        self.success_all = np.concatenate([self.success_all, success[valid_x]])
        self.X = np.vstack([self.X, X[success]])
        self.Y = np.vstack([self.Y, Y[success]])
        self._dirty = True
        return self

    @property
    def n_failed(self) -> int:
        """Number of recorded failed experiments."""
        return int(np.sum(~self.success_all))

    def _fit_success_classifier(self):
        """Fit P(success | x) when failures exist, else return ``None``."""
        n_fail = self.n_failed
        if n_fail == 0 or len(self.X_all) < 4:
            return None
        try:
            from sklearn.gaussian_process import GaussianProcessClassifier
            from sklearn.gaussian_process.kernels import ConstantKernel, Matern
            import warnings
            U = self.space.to_unit(self.X_all)
            # Let the length scale and amplitude be fitted: a fixed, wide kernel
            # produces an under-confident classifier that cannot express a sharp
            # feasibility boundary, which in turn fails to steer suggestions.
            kernel = (ConstantKernel(5.0, (1e-1, 1e3))
                      * Matern(length_scale=np.full(U.shape[1], 0.2),
                               length_scale_bounds=(1e-2, 1e1), nu=2.5))
            clf = GaussianProcessClassifier(kernel=kernel, random_state=self.seed,
                                            n_restarts_optimizer=2)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                clf.fit(U, self.success_all.astype(int))
            return clf
        except Exception:
            return None

    def _Y_internal(self) -> np.ndarray:
        return np.column_stack([o.to_min(self.Y[:, i])
                                for i, o in enumerate(self.objectives)])

    # ------------------------------------------------------------- modelling
    def fit(self) -> "BayesianOptimizer":
        """Refit one GP per objective (and the success classifier) on current data.

        Output transforms declared as ``"auto"`` are resolved here, from the
        data, before the first GP is built.
        """
        if self.n_obs < 3:
            raise RuntimeError("need at least 3 observations before fitting")
        for j, o in enumerate(self.objectives):
            o.resolve_transform(self.Y[:, j])
        U = self.space.to_unit(self.X)
        Yi = self._Y_internal()
        self._models = [
            GPSurrogate(backend=self.backend, seed=self.seed).fit(U, Yi[:, j])
            for j in range(Yi.shape[1])]
        self._success_clf = self._fit_success_classifier()
        self._scale = float(max(np.std(Yi[:, 0]), 1e-9))
        self._dirty = False
        return self

    def transforms(self) -> dict:
        """Report the output transform in force for each objective."""
        self._ensure_fit()
        return {o.name: o.active_transform for o in self.objectives}

    def _ensure_fit(self) -> None:
        if self._dirty or not self._models:
            self.fit()

    def predict(self, X: np.ndarray):
        """Posterior prediction per objective in **native** units.

        Returns:
            ``(mean, std)`` each of shape ``(n, n_objectives)``. When an output
            transform is in use ``mean`` is the back-transformed posterior
            median and ``std`` is the half-width of the back-transformed
            one-sigma interval, so both stay in physically meaningful units.
        """
        self._ensure_fit()
        U = self.space.to_unit(X)
        mus, sds = [], []
        for o, m in zip(self.objectives, self._models):
            mu, sd = m.predict(U)
            native = o.from_min(mu)
            hi = o.from_min(mu + sd)
            lo = o.from_min(mu - sd)
            mus.append(native)
            sds.append(np.abs(hi - lo) / 2.0)
        return np.column_stack(mus), np.column_stack(sds)

    def model_quality(self) -> dict:
        """Leave-one-out :math:`R^2` per objective (see ``GPSurrogate.loo_r2``).

        Computed in the modelling space (after the output transform), where the
        GP is actually fitted.
        """
        self._ensure_fit()
        return {o.name: float(m.loo_r2())
                for o, m in zip(self.objectives, self._models)}

    # ----------------------------------------------------------- suggestion
    def ask(self, q: int = 1) -> np.ndarray:
        """Suggest ``q`` new experiments in native units.

        Each of the ``q`` picks is made under a **frozen acquisition context**
        (see :class:`_AskContext`): the ParEGO scalarization weights, the
        Monte-Carlo seed and the incumbent are drawn once and then held fixed
        while the candidate pool is ranked and the winner is locally refined.
        Without this the refinement would be optimizing a function that
        re-randomizes on every evaluation.

        Successive picks draw *new* weights, which is what makes ParEGO spread a
        batch across the Pareto front (matching the reference implementation).

        Falls back to space-filling sampling while there is too little data to
        fit a GP.
        """
        if self.n_obs < max(3, self.space.dim):
            return self._initial_points(q)
        self._ensure_fit()
        picks: list[np.ndarray] = []
        for _ in range(q):
            ctx = self._make_context()
            cand = self._candidate_pool()
            scores = self._ranked_score(cand, ctx, pending=picks)
            best = cand[int(np.argmax(scores))]
            if self.refine:
                best = self._local_refine(best, ctx, pending=picks)
            picks.append(best)
        return np.array(picks)
    def _make_context(self) -> "_AskContext":
        """Freeze all stochastic elements needed to score one candidate."""
        Yi = self._Y_internal()
        n_obj = len(self.objectives)
        base_w = np.array([o.weight for o in self.objectives], dtype=float)
        if n_obj > 1:
            w = random_weights(n_obj, self.rng) * base_w
            w = w / max(w.sum(), 1e-12)
        else:
            w = base_w / base_w.sum()
        return _AskContext(
            weights=w,
            seed=int(self.rng.integers(1 << 31)),
            Yi=Yi,
            Yi_model=self._posterior_internal(self.X)[0],
            y_min=Yi.min(axis=0),
            y_max=Yi.max(axis=0),
        )

    def _initial_points(self, q: int) -> np.ndarray:
        from doe import doe_latin_hypercube, doe_mixture_space_filling
        seed = int(self.rng.integers(1 << 31))
        n = max(q, 1)
        if self.space.mixture:
            pts = doe_mixture_space_filling(self.space, n, seed=seed)
        else:
            pts = doe_latin_hypercube(self.space, n, seed=seed)
        return pts[:q]

    def _candidate_pool(self) -> np.ndarray:
        """Global samples plus local perturbations around the best points."""
        seed = int(self.rng.integers(1 << 31))
        n_global = int(self.n_candidates * 0.7)
        glob = self.space.sample(n_global, seed=seed)
        n_local = self.n_candidates - n_global
        anchors = self._elite_points()
        if len(anchors) == 0 or n_local <= 0:
            return glob
        idx = self.rng.integers(0, len(anchors), size=n_local)
        scale = 0.10 * (self.space.bounds[1] - self.space.bounds[0])
        loc = anchors[idx] + self.rng.normal(0.0, scale, size=(n_local, self.space.dim))
        loc = self.space.snap(self.space.repair(loc))
        pool = np.vstack([glob, loc])
        pool = pool[self.space.is_feasible(pool)]
        return self._filter_likely_failures(pool)

    def _success_cutoff(self) -> Optional[float]:
        """Self-calibrating success-probability floor, or ``None`` if inactive.

        Expressed as a fraction of the median probability the classifier assigns
        to runs that actually succeeded, so it stays meaningful whatever the
        calibration of the underlying classifier.
        """
        if self._success_clf is None or self.min_success_prob <= 0:
            return None
        successes = self.X_all[self.success_all]
        if len(successes) < 3:
            return None
        ref = float(np.median(self._success_prob(successes)))
        return self.min_success_prob * ref

    def _likely_to_fail(self, X: np.ndarray) -> np.ndarray:
        """Boolean mask of candidates the classifier considers hopeless."""
        cutoff = self._success_cutoff()
        X = np.atleast_2d(X)
        if cutoff is None:
            return np.zeros(len(X), dtype=bool)
        return self._success_prob(X) < cutoff

    def _filter_likely_failures(self, pool: np.ndarray) -> np.ndarray:
        """Drop pool candidates the success classifier considers hopeless.

        Never removes every candidate; if it would, the filter is skipped and
        the multiplicative penalty alone governs the choice.
        """
        if len(pool) == 0:
            return pool
        keep = ~self._likely_to_fail(pool)
        return pool[keep] if keep.sum() >= max(10, 0.01 * len(pool)) else pool

    def _elite_points(self, frac: float = 0.25) -> np.ndarray:
        """Top observations by the internal scalarized objective."""
        if self.n_obs == 0:
            return np.empty((0, self.space.dim))
        Yi = self._Y_internal()
        if self.multi_objective:
            w = np.array([o.weight for o in self.objectives], dtype=float)
            w = w / w.sum()
            score = chebyshev_scalarization(Yi, w)
        else:
            score = Yi[:, 0]
        k = max(1, int(np.ceil(frac * self.n_obs)))
        return self.X[np.argsort(score)[:k]]

    # ---------------------------------------------------------------- scoring
    def _posterior_internal(self, X: np.ndarray):
        U = self.space.to_unit(X)
        mus, sds = [], []
        for m in self._models:
            mu, sd = m.predict(U)
            mus.append(mu)
            sds.append(sd)
        return np.column_stack(mus), np.column_stack(sds)

    def _raw_score(self, X: np.ndarray, ctx: "_AskContext") -> np.ndarray:
        """Raw acquisition value (larger is better), deterministic given ``ctx``.

        No feasibility or diversity terms are applied here: this is the smooth,
        reproducible surface that the local refinement optimizes.
        """
        mu, sd = self._posterior_internal(X)
        if self.multi_objective:
            return self._raw_score_multi(mu, sd, ctx)
        name = "logei" if self.acquisition_fn == "auto" else self.acquisition_fn
        return acquisition(name, mu[:, 0], sd[:, 0],
                           best=float(ctx.Yi[:, 0].min()), beta=self.beta,
                           xi=self.xi, rng=np.random.default_rng(ctx.seed))

    def _raw_score_multi(self, mu: np.ndarray, sd: np.ndarray,
                         ctx: "_AskContext") -> np.ndarray:
        name = self.acquisition_fn
        if name in ("auto", "parego"):
            return self._parego(mu, sd, ctx)
        if name == "ehvi":
            # Build the reference front from the GP posterior mean at the
            # observed designs, not from the raw observations. Under
            # measurement noise a front built from raw values is optimistically
            # biased -- it enshrines lucky measurements -- which makes the
            # hypervolume improvement of genuinely good candidates look small.
            # This mirrors qEHVI's plug-in treatment of in-sample designs.
            front_Y = ctx.Yi_model
            ref = self._reference_point(front_Y)
            n_obj = front_Y.shape[1]
            # EHVI costs a hypervolume computation per posterior sample per
            # candidate, so pre-screen the pool with cheap ParEGO and evaluate
            # EHVI only on the most promising candidates.
            keep = min(len(mu), self.ehvi_prescreen)
            out = np.full(len(mu), -np.inf)
            if keep < len(mu):
                cheap = self._parego(mu, sd, ctx)
                idx = np.argpartition(-cheap, keep - 1)[:keep]
            else:
                idx = np.arange(len(mu))
            mc = self.ehvi_mc_samples if n_obj <= 2 else max(8, self.ehvi_mc_samples // 4)
            ehvi = expected_hypervolume_improvement(
                mu[idx], sd[idx], front_Y, ref, mc_samples=mc, seed=ctx.seed)
            out[idx] = np.log(np.maximum(ehvi, 1e-300))
            return out
        # Any other acquisition, applied to the weighted scalarization.
        scal, scal_sd, best = self._scalarized_posterior(mu, sd, ctx)
        return acquisition(name, scal, scal_sd, best=best, beta=self.beta,
                           xi=self.xi, rng=np.random.default_rng(ctx.seed))

    def _scalarized_posterior(self, mu: np.ndarray, sd: np.ndarray,
                              ctx: "_AskContext"):
        """Augmented-Chebyshev scalarization of the posterior (first-order sd)."""
        w = ctx.weights
        obs = chebyshev_scalarization(ctx.Yi, w, y_min=ctx.y_min, y_max=ctx.y_max)
        cand = chebyshev_scalarization(mu, w, y_min=ctx.y_min, y_max=ctx.y_max)
        span = np.where(ctx.y_max - ctx.y_min > 1e-12, ctx.y_max - ctx.y_min, 1.0)
        cand_sd = np.sqrt(((w * sd / span) ** 2).sum(axis=1))
        return cand, cand_sd, float(obs.min())

    def _parego(self, mu: np.ndarray, sd: np.ndarray,
                ctx: "_AskContext") -> np.ndarray:
        """ParEGO: log-EI on the frozen randomly weighted Chebyshev scalarization."""
        cand, cand_sd, best = self._scalarized_posterior(mu, sd, ctx)
        return acquisition("logei", cand, cand_sd, best=best, xi=self.xi)

    def _acq_name(self) -> str:
        """Canonical acquisition key actually in force."""
        if self.acquisition_fn == "auto":
            return "parego" if self.multi_objective else "logei"
        return self.acquisition_fn

    def _ranked_score(self, X: np.ndarray, ctx: "_AskContext",
                      pending: Sequence[np.ndarray] = ()) -> np.ndarray:
        """Composed score used to pick the winner from the candidate pool.

        The raw acquisition is converted to a non-negative **utility** (see
        :func:`acquisition.to_utility`) before the feasibility probability, the
        experiment-success probability and the batch-diversity factor are
        multiplied in. For the EI family this yields the standard constrained
        expected-improvement form, ``EI(x) * P(feasible | x)``, with magnitudes
        preserved; for unbounded acquisitions it falls back to rank composition.
        """
        mu, sd = self._posterior_internal(X)
        scale = ACQUISITIONS[self._acq_name()]["scale"]
        util = to_utility(self._raw_score(X, ctx), scale)
        return (util * self._feasibility(mu, sd) * self._success_prob(X)
                * self._pending_penalty(X, pending))

    def _success_prob(self, X: np.ndarray) -> np.ndarray:
        """Predicted probability that an experiment at ``X`` succeeds at all."""
        if self._success_clf is None:
            return np.ones(len(np.atleast_2d(X)))
        try:
            p = self._success_clf.predict_proba(self.space.to_unit(X))[:, 1]
            return np.clip(p, 1e-6, 1.0)
        except Exception:
            return np.ones(len(np.atleast_2d(X)))

    def _reference_point(self, Yi: np.ndarray) -> np.ndarray:
        if self.ref_point is not None:
            return np.array([float(o.to_min(r)) for o, r in
                             zip(self.objectives, self.ref_point)])
        nadir = Yi.max(axis=0)
        span = np.maximum(nadir - Yi.min(axis=0), 1e-9)
        return nadir + 0.1 * span

    def _feasibility(self, mu: np.ndarray, sd: np.ndarray) -> np.ndarray:
        """Probability that a candidate meets every hard threshold.

        Combines the per-objective specification limits with the success
        classifier (if any failed experiments have been recorded).
        """
        p = np.ones(len(mu))
        for j, o in enumerate(self.objectives):
            t = o.internal_threshold()
            if t is not None:
                p = p * probability_below_threshold(mu[:, j], sd[:, j], t)
        return np.maximum(p, 1e-12)

    def _pending_penalty(self, X: np.ndarray, pending: Sequence[np.ndarray]
                         ) -> np.ndarray:
        """Local penalization so a batch spreads out instead of collapsing."""
        if not len(pending):
            return np.ones(len(X))
        d = self._pending_distance(X, pending)
        return np.clip(d / self._diversity_radius(), 0.0, 1.0) ** 2

    def _diversity_radius(self) -> float:
        return 0.15 / max(1.0, self.space.dim ** 0.5)

    def _pending_distance(self, X: np.ndarray,
                          pending: Sequence[np.ndarray]) -> np.ndarray:
        U = self.space.to_unit(X)
        P = self.space.to_unit(np.array(pending))
        return np.linalg.norm(U[:, None, :] - P[None, :, :], axis=2).min(axis=1)

    def _local_refine(self, x0: np.ndarray, ctx: "_AskContext",
                      pending: Sequence[np.ndarray] = ()) -> np.ndarray:
        """Polish a candidate with SLSQP on the **frozen** acquisition surface.

        Batch diversity enters as an explicit inequality constraint rather than
        a score penalty, so the objective SLSQP sees is exactly the acquisition
        it is supposed to maximize. The refined point is accepted only if it is
        feasible and genuinely improves that same frozen objective.
        """
        from scipy.optimize import minimize
        lo, hi = self.space.bounds
        bounds = list(zip(lo, hi))
        cons: list[dict] = []
        if self.space.mixture:
            cons.append({"type": "eq",
                         "fun": lambda z: float(np.sum(z) - self.space.total)})
        if len(pending):
            radius = self._diversity_radius()
            cons.append({
                "type": "ineq",
                "fun": lambda z: float(
                    self._pending_distance(np.atleast_2d(z), pending)[0] - radius),
            })

        def neg(z: np.ndarray) -> float:
            v = float(self._raw_score(np.atleast_2d(z), ctx)[0])
            return -v if np.isfinite(v) else 1e30

        start = neg(x0)
        try:
            res = minimize(neg, x0, method="SLSQP", bounds=bounds,
                           constraints=cons, options={"maxiter": 60, "ftol": 1e-9})
            raw = self.space.repair(np.atleast_2d(res.x))[0]
            cand = self.space.snap(raw[None, :])[0]
            if not self.space.is_feasible(cand[None, :])[0]:
                return x0
            if neg(cand) >= start:
                return x0
            # Snapping integer factors can undo SLSQP's diversity constraint.
            if (len(pending) and not np.allclose(cand, raw)
                    and (self._pending_distance(cand[None, :], pending)[0]
                         < self._diversity_radius())):
                return x0
            # Never let refinement violate a threshold the start point met, or
            # wander into a region the success classifier has ruled out.
            mu_n, sd_n = self._posterior_internal(np.atleast_2d(cand))
            mu_0, sd_0 = self._posterior_internal(np.atleast_2d(x0))
            if self._feasibility(mu_n, sd_n)[0] < 0.5 * self._feasibility(mu_0, sd_0)[0]:
                return x0
            if self._likely_to_fail(cand[None, :])[0]:
                return x0
            return cand
        except Exception:
            return x0

    # ---------------------------------------------------------------- results
    def best(self) -> dict:
        """Best observation so far (scalarized for multi-objective problems)."""
        if self.n_obs == 0:
            return {}
        Yi = self._Y_internal()
        if self.multi_objective:
            w = np.array([o.weight for o in self.objectives], dtype=float)
            score = chebyshev_scalarization(Yi, w / w.sum())
            i = int(np.argmin(score))
        else:
            i = int(np.argmin(Yi[:, 0]))
        return {
            "index": i,
            "x": self.X[i].tolist(),
            "parameters": self.space.decode(self.X[i][None, :])[0],
            "y": {o.name: float(self.Y[i, j]) for j, o in enumerate(self.objectives)},
        }

    def pareto(self) -> dict:
        """Current Pareto front in native units."""
        Yi = self._Y_internal()
        Yp, Xp = pareto_front(Yi, self.X)
        native = np.column_stack([o.from_min(Yp[:, j])
                                  for j, o in enumerate(self.objectives)])
        return {
            "n_pareto": int(len(Xp)),
            "X": Xp.tolist(),
            "Y": native.tolist(),
            "parameters": self.space.decode(Xp),
            "objective_names": [o.name for o in self.objectives],
        }

    def hypervolume(self, ref_point: Optional[Sequence[float]] = None) -> float:
        """Dominated hypervolume of the current observations."""
        Yi = self._Y_internal()
        ref = (self._reference_point(Yi) if ref_point is None
               else np.array([float(o.to_min(r))
                              for o, r in zip(self.objectives, ref_point)]))
        return hypervolume(Yi, ref)

    def feasible_mask(self) -> np.ndarray:
        """Rows of the observation set that satisfy every declared threshold."""
        ok = np.ones(self.n_obs, dtype=bool)
        for j, o in enumerate(self.objectives):
            if o.threshold is None:
                continue
            ok &= (self.Y[:, j] <= o.threshold if o.direction == "minimize"
                   else self.Y[:, j] >= o.threshold)
        return ok


# --------------------------------------------------------------------------
# Convenience wrappers
# --------------------------------------------------------------------------
def suggest_next(X: np.ndarray, Y: np.ndarray, space: ParameterSpace,
                 objectives: Sequence[Objective], q: int = 1,
                 acquisition_fn: str = "auto", backend: str = "auto",
                 seed: Optional[int] = None, **kwargs) -> dict:
    """Suggest the next ``q`` experiments given existing data.

    This is the workhorse for human-in-the-loop campaigns: pass the
    formulations already run and their measured responses, get back the batch
    to run next together with the model's prediction for each suggestion.

    Returns:
        dict with ``suggestions`` (list of parameter dicts), ``X`` (array),
        ``predicted_mean``, ``predicted_std``, ``model_r2`` and ``best_so_far``.
    """
    opt = BayesianOptimizer(space, objectives, acquisition_fn=acquisition_fn,
                            backend=backend, seed=seed, **kwargs)
    opt.tell(X, Y)
    Xn = opt.ask(q)
    out = {
        "X": Xn.tolist(),
        "suggestions": space.decode(Xn),
        "best_so_far": opt.best(),
        "n_observations": opt.n_obs,
        "backend": opt.backend,
    }
    if opt.n_obs >= max(3, space.dim):
        mu, sd = opt.predict(Xn)
        names = [o.name for o in objectives]
        out["predicted_mean"] = [dict(zip(names, row)) for row in mu.tolist()]
        out["predicted_std"] = [dict(zip(names, row)) for row in sd.tolist()]
        out["model_r2"] = opt.model_quality()
    return out


def select_from_library(features: np.ndarray, observed_idx: Sequence[int],
                        Y: np.ndarray, objectives: Sequence[Objective],
                        q: int = 1, acquisition_fn: str = "auto",
                        backend: str = "auto", seed: Optional[int] = None,
                        labels: Optional[Sequence] = None,
                        feature_names: Optional[Sequence[str]] = None,
                        diversity: float = 0.5, **kwargs) -> dict:
    """Choose the next ``q`` items to test from a **fixed candidate library**.

    This is the pattern for molecular and materials campaigns: you are not
    tuning continuous amounts, you are selecting *which* of a finite set of
    candidates to make and measure. Each candidate is represented by a feature
    vector -- RDKit/Mordred descriptors, fingerprints, learned embeddings,
    measured properties, or anything else numeric.

    The features can come from anywhere. This container deliberately does not
    ship RDKit: computing descriptors is the ``mol-toolkit`` agent's job, and
    duplicating it here would bloat the image and split responsibility. Hand a
    descriptor table from that agent (or a CSV, or ChEMBL) straight into this
    function.

    Features are standardized internally, which matters: raw descriptors span
    wildly different scales (molecular weight ~10^2, LogP ~10^0, TPSA ~10^1),
    and an unstandardized GP would let whichever descriptor has the largest
    numeric range dominate the kernel.

    Args:
        features: ``(n_library, n_features)`` matrix describing every candidate.
        observed_idx: Row indices of candidates already measured.
        Y: ``(len(observed_idx), n_objectives)`` responses, in the same order as
            ``observed_idx``. ``NaN`` marks a failed experiment.
        objectives: Objective declarations.
        q: How many candidates to select.
        acquisition_fn: As for :class:`BayesianOptimizer`.
        backend: GP backend.
        seed: RNG seed.
        labels: Optional identifiers for the library rows (SMILES, IDs, names).
        feature_names: Optional feature column names, used only in reporting.
        diversity: In ``[0, 1]``. After each pick, candidates within this
            fraction of the median nearest-neighbour distance are suppressed,
            so a batch does not consist of near-duplicate analogues. ``0``
            disables it and selects the top-``q`` by acquisition alone.
        **kwargs: Forwarded to :class:`BayesianOptimizer`.

    Returns:
        dict with ``selected_idx``, ``selected_labels``, ``predicted_mean``,
        ``predicted_std``, ``acquisition``, ``model_r2``, ``transforms``,
        ``n_observed``, ``n_failed`` and ``n_library``.

    Example:
        >>> # descriptors from any source; here a toy 2-feature library
        >>> F = np.random.default_rng(0).random((200, 2))
        >>> obs = list(range(10))
        >>> Yobs = (F[obs, :1] - 0.4) ** 2
        >>> out = select_from_library(F, obs, Yobs,
        ...                           [Objective("y", "minimize")], q=3, seed=0)
        >>> len(out["selected_idx"])
        3
    """
    features = np.atleast_2d(np.asarray(features, dtype=float))
    observed_idx = [int(i) for i in observed_idx]
    Y = np.asarray(Y, dtype=float)
    if Y.ndim == 1:
        Y = Y.reshape(-1, 1)
    if len(observed_idx) != len(Y):
        raise ValueError("observed_idx and Y must have the same length")
    if labels is not None and len(labels) != len(features):
        raise ValueError("labels must have one entry per library row")
    n_lib = len(features)
    if not observed_idx:
        raise ValueError("need at least one observed candidate; for a cold "
                         "start pick a diverse subset with "
                         "select_diverse_subset()")

    # Standardize features so no single descriptor dominates the kernel.
    mu_f = features.mean(axis=0)
    sd_f = features.std(axis=0)
    sd_f[sd_f < 1e-12] = 1.0
    Z = (features - mu_f) / sd_f

    # A unit-cube box space over the standardized features lets the existing
    # optimizer machinery (GPs, acquisitions, thresholds, failure handling) work
    # unchanged; we then restrict every choice to actual library rows.
    lo, hi = Z.min(axis=0), Z.max(axis=0)
    span = np.where(hi - lo > 1e-12, hi - lo, 1.0)
    space = make_space(list(zip(lo, lo + span)),
                       names=list(feature_names) if feature_names is not None
                       else [f"f{i}" for i in range(Z.shape[1])])

    opt = BayesianOptimizer(space, objectives, acquisition_fn=acquisition_fn,
                            backend=backend, seed=seed, refine=False, **kwargs)
    opt.tell(Z[observed_idx], Y)
    if opt.n_obs < 3:
        raise ValueError(f"need at least 3 successful observations to model; "
                         f"got {opt.n_obs}")
    opt.fit()

    remaining = np.setdiff1d(np.arange(n_lib), np.asarray(observed_idx))
    if len(remaining) == 0:
        raise ValueError("every library candidate has already been measured")

    # Diversity radius from the library's own geometry, so it is scale free.
    radius = 0.0
    if diversity > 0 and len(remaining) > 2:
        sample = Z[remaining[:2000]]
        d = np.linalg.norm(sample[:, None, :] - sample[None, :, :], axis=2)
        np.fill_diagonal(d, np.inf)
        radius = float(diversity * np.median(d.min(axis=1)))

    picks: list[int] = []
    acq_values: list[float] = []
    available = remaining.copy()
    for _ in range(min(q, len(remaining))):
        if len(available) == 0:
            available = np.setdiff1d(remaining, np.asarray(picks, dtype=int))
            if len(available) == 0:
                break
        ctx = opt._make_context()
        scores = opt._ranked_score(Z[available], ctx, pending=[])
        best_local = int(np.argmax(scores))
        chosen = int(available[best_local])
        picks.append(chosen)
        acq_values.append(float(scores[best_local]))
        if radius > 0:
            far = np.linalg.norm(Z[available] - Z[chosen], axis=1) > radius
            available = available[far]
        else:
            available = available[np.arange(len(available)) != best_local]

    sel = np.array(picks, dtype=int)
    mu, sd = opt.predict(Z[sel])
    names = [o.name for o in objectives]
    out = {
        "selected_idx": sel.tolist(),
        "predicted_mean": [dict(zip(names, row)) for row in mu.tolist()],
        "predicted_std": [dict(zip(names, row)) for row in sd.tolist()],
        "acquisition": acq_values,
        "model_r2": opt.model_quality(),
        "transforms": opt.transforms(),
        "n_observed": int(len(observed_idx)),
        "n_failed": int(opt.n_failed),
        "n_library": int(n_lib),
        "n_remaining": int(len(remaining)),
        "backend": opt.backend,
        "diversity_radius": radius,
    }
    if labels is not None:
        out["selected_labels"] = [labels[i] for i in sel]
    return out


def select_diverse_subset(features: np.ndarray, n: int,
                          seed: Optional[int] = None,
                          labels: Optional[Sequence] = None) -> dict:
    """Pick a maximally spread-out starting set from a candidate library.

    Use this for the **cold start** of a library campaign, before any response
    has been measured: greedy maximin selection in standardized feature space
    gives the surrogate the widest possible initial view of the library.

    Args:
        features: ``(n_library, n_features)`` descriptor matrix.
        n: Number of candidates to select.
        seed: RNG seed for the starting point.
        labels: Optional identifiers for the library rows.

    Returns:
        dict with ``selected_idx`` and, if given, ``selected_labels``.
    """
    F = np.atleast_2d(np.asarray(features, dtype=float))
    sd = F.std(axis=0)
    sd[sd < 1e-12] = 1.0
    Z = (F - F.mean(axis=0)) / sd
    rng = np.random.default_rng(seed)
    n = min(int(n), len(Z))
    idx = [int(rng.integers(len(Z)))]
    d2 = ((Z - Z[idx[0]]) ** 2).sum(axis=1)
    for _ in range(n - 1):
        nxt = int(np.argmax(d2))
        idx.append(nxt)
        d2 = np.minimum(d2, ((Z - Z[nxt]) ** 2).sum(axis=1))
    out = {"selected_idx": idx, "n_library": int(len(Z))}
    if labels is not None:
        out["selected_labels"] = [labels[i] for i in idx]
    return out


def run_bo_campaign(objective_fn: Callable[[np.ndarray], np.ndarray],
                    space: ParameterSpace, objectives: Sequence[Objective],
                    n_init: int = 8, n_iter: int = 30, batch_size: int = 1,
                    acquisition_fn: str = "auto", backend: str = "auto",
                    seed: Optional[int] = None, X_init: Optional[np.ndarray] = None,
                    Y_init: Optional[np.ndarray] = None, verbose: bool = False,
                    **kwargs) -> dict:
    """Run a closed-loop BO campaign against a callable objective.

    Args:
        objective_fn: Maps ``(n, d)`` native-unit inputs to ``(n, n_obj)``
            responses in native units.
        space: Design space.
        objectives: Objective declarations.
        n_init: Number of initial space-filling runs (ignored if ``X_init`` given).
        n_iter: Number of BO iterations after initialization.
        batch_size: Experiments suggested per iteration.
        X_init / Y_init: Optional warm-start data (e.g. a historical dataset).
        verbose: Print per-iteration progress.

    Returns:
        dict with the full trace: ``X``, ``Y``, ``best_trace`` (best scalarized
        value after each evaluation), ``hv_trace``, ``pareto`` and ``best``.
    """
    opt = BayesianOptimizer(space, objectives, acquisition_fn=acquisition_fn,
                            backend=backend, seed=seed, **kwargs)
    if X_init is not None:
        Y0 = objective_fn(X_init) if Y_init is None else Y_init
        opt.tell(X_init, Y0)
    if opt.n_obs < n_init:
        rng = np.random.default_rng(seed)
        from doe import doe_latin_hypercube, doe_mixture_space_filling
        need = n_init - opt.n_obs
        s = int(rng.integers(1 << 31))
        X0 = (doe_mixture_space_filling(space, need, seed=s) if space.mixture
              else doe_latin_hypercube(space, need, seed=s))
        opt.tell(X0, objective_fn(X0))

    ref = kwargs.get("ref_point")
    n_warm = opt.n_obs
    for it in range(n_iter):
        Xn = opt.ask(batch_size)
        Yn = objective_fn(Xn)
        opt.tell(Xn, Yn)
        if verbose:
            print(f"[bo] iter {it + 1}/{n_iter} n={opt.n_obs} "
                  f"best={_scalar_best(opt):.5g}", flush=True)

    trace = _trace_from_batch(opt.X, opt.Y, objectives, space, ref)
    return {
        "X": opt.X.tolist(),
        "Y": opt.Y.tolist(),
        "best": opt.best(),
        "best_trace": trace["best_trace"],
        "hv_trace": trace["hv_trace"],
        "n_warm_start": int(n_warm),
        "pareto": opt.pareto() if opt.multi_objective else None,
        "n_evaluations": int(opt.n_obs),
        "backend": opt.backend,
        "objective_names": [o.name for o in objectives],
    }


def _scalar_best(opt: BayesianOptimizer) -> float:
    Yi = opt._Y_internal()
    if opt.multi_objective:
        w = np.array([o.weight for o in opt.objectives], dtype=float)
        return float(chebyshev_scalarization(Yi, w / w.sum()).min())
    return float(Yi[:, 0].min())


def scalarize(Y: np.ndarray, objectives: Sequence[Objective],
              y_min: Optional[np.ndarray] = None,
              y_max: Optional[np.ndarray] = None, rho: float = 0.05) -> np.ndarray:
    """Weighted augmented-Chebyshev scalarization of native-unit responses.

    Use a **fixed** ``y_min``/``y_max`` (e.g. the range of a reference dataset)
    when comparing different optimizers, otherwise each run is normalized
    against itself and the comparison is meaningless.

    Args:
        Y: ``(n, n_obj)`` responses in native units.
        objectives: Objective declarations (direction + weight).
        y_min / y_max: Normalization bounds in the internal (minimization)
            orientation. Defaults to the range of ``Y``.
        rho: Augmentation coefficient.

    Returns:
        ``(n,)`` scalar cost -- lower is better.
    """
    Y = np.atleast_2d(np.asarray(Y, dtype=float))
    Yi = np.column_stack([o.to_min(Y[:, j]) for j, o in enumerate(objectives)])
    w = np.array([o.weight for o in objectives], dtype=float)
    return chebyshev_scalarization(Yi, w / w.sum(), rho=rho,
                                   y_min=y_min, y_max=y_max)


def run_random_search(objective_fn, space: ParameterSpace,
                      objectives: Sequence[Objective], n_evals: int = 38,
                      seed: Optional[int] = None,
                      ref_point: Optional[Sequence[float]] = None) -> dict:
    """Uniform random-search baseline with the same evaluation budget as BO."""
    X = space.sample(n_evals, seed=seed)
    Y = objective_fn(X)
    return _trace_from_batch(X, Y, objectives, space, ref_point)


def run_de_baseline(objective_fn, space: ParameterSpace,
                    objectives: Sequence[Objective], n_evals: int = 38,
                    seed: Optional[int] = None, popsize: int = 8,
                    ref_point: Optional[Sequence[float]] = None) -> dict:
    """Differential-evolution baseline on the weighted-Chebyshev scalarization.

    Mirrors the classic "fit a surrogate then run DE on it" workflow so that BO
    can be compared against it under an identical evaluation budget.
    """
    from scipy.optimize import differential_evolution
    w = np.array([o.weight for o in objectives], dtype=float)
    w = w / w.sum()
    hist_X, hist_Y = [], []

    def scalar(z):
        z = space.repair(np.atleast_2d(z))
        y = np.atleast_2d(objective_fn(z))
        hist_X.append(z[0])
        hist_Y.append(y[0])
        yi = np.column_stack([o.to_min(y[:, j]) for j, o in enumerate(objectives)])
        return float(chebyshev_scalarization(yi, w, y_min=np.zeros(len(objectives)),
                                             y_max=np.ones(len(objectives)))[0])

    lo, hi = space.bounds
    maxiter = max(1, int(np.ceil(n_evals / max(popsize * space.dim, 1))))
    try:
        differential_evolution(scalar, list(zip(lo, hi)), seed=seed, popsize=popsize,
                               maxiter=maxiter, polish=False, init="sobol",
                               tol=1e-12)
    except Exception:
        pass
    X = np.array(hist_X[:n_evals])
    Y = np.array(hist_Y[:n_evals])
    return _trace_from_batch(X, Y, objectives, space, ref_point)


def _trace_from_batch(X, Y, objectives, space, ref_point) -> dict:
    Yi = np.column_stack([o.to_min(np.asarray(Y)[:, j])
                          for j, o in enumerate(objectives)])
    w = np.array([o.weight for o in objectives], dtype=float)
    w = w / w.sum()
    if len(objectives) > 1:
        scal = chebyshev_scalarization(Yi, w)
    else:
        scal = Yi[:, 0]
    best_trace = np.minimum.accumulate(scal).tolist()
    hv_trace = []
    if len(objectives) > 1:
        ref = (np.array([float(o.to_min(r)) for o, r in zip(objectives, ref_point)])
               if ref_point is not None
               else Yi.max(axis=0) + 0.1 * np.maximum(
                   Yi.max(axis=0) - Yi.min(axis=0), 1e-9))
        for i in range(1, len(Yi) + 1):
            hv_trace.append(hypervolume(Yi[:i], ref))
    i = int(np.argmin(scal))
    return {
        "X": np.asarray(X).tolist(),
        "Y": np.asarray(Y).tolist(),
        "best_trace": best_trace,
        "hv_trace": hv_trace,
        "n_evaluations": int(len(X)),
        "best": {"x": np.asarray(X)[i].tolist(),
                 "parameters": space.decode(np.asarray(X)[i][None, :])[0],
                 "y": {o.name: float(np.asarray(Y)[i, j])
                       for j, o in enumerate(objectives)}},
    }
