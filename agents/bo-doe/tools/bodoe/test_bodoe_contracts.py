"""Component-contract tests for the bo-doe library.

These test the *internal contracts* of individual components rather than
end-to-end outcomes. The distinction matters: the original test suite asserted
only invariants (mixtures sum correctly, batches spread out) and outcomes (beats
random on Branin). That net let a real defect through -- SLSQP refinement was
optimizing an acquisition surface that re-randomized on every function
evaluation, so it was maximizing noise. No invariant and no outcome test could
see it.

Contracts verified here:

* ``rank_normalize`` is order-preserving, bounded and composition-safe.
* The acquisition surface is **deterministic** given a frozen ask-context.
* Local refinement never returns a point worse than its start on that surface.
* Refinement respects mixture equality, bounds and batch-diversity constraints.
* Threshold constraints and the success classifier actually steer suggestions.
* ``Objective`` auto-transform detection latches and round-trips.
* Failed experiments are recorded, excluded from regression, and penalized.

Run:  python test_bodoe_contracts.py   (or: python -m pytest test_bodoe_contracts.py)
"""
from __future__ import annotations

import os
import sys
import traceback

import numpy as np

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app")
sys.path.insert(0, APP)

from acquisition import (ACQUISITIONS, acquisition,  # noqa: E402
                         canonical_acquisition, rank_normalize)
from optimize import BayesianOptimizer, Objective  # noqa: E402
from space import make_mixture_space, make_space  # noqa: E402

PASS, FAIL = [], []


def check(name, fn):
    try:
        fn()
        PASS.append(name)
        print(f"  PASS  {name}")
    except Exception as exc:
        FAIL.append((name, exc))
        print(f"  FAIL  {name}: {exc}")
        traceback.print_exc()


# --------------------------------------------------------------------------
# rank_normalize contract
# --------------------------------------------------------------------------
def t_rank_order_preserving():
    rng = np.random.default_rng(0)
    for _ in range(20):
        s = rng.normal(size=50) * rng.choice([1e-8, 1.0, 1e6])
        r = rank_normalize(s)
        assert np.array_equal(np.argsort(np.argsort(s)),
                              np.argsort(np.argsort(r))), "rank order changed"
        assert np.all(r > 0) and np.all(r <= 1.0), "must lie in (0, 1]"


def t_rank_handles_negative_and_nonfinite():
    s = np.array([-1e9, -5.0, np.nan, np.inf, -np.inf, 0.0])
    r = rank_normalize(s)
    assert np.all(np.isfinite(r)) and np.all(r > 0)
    # The largest finite value must outrank every non-finite one.
    assert r[5] > r[2] and r[5] > r[4]


def t_composition_cannot_invert():
    """The original defect: penalties multiplied into a negative acquisition.

    With log-EI values, candidate 0 is by far the best. Applying a diversity
    penalty to the *worse* candidate makes it win under naive multiplication,
    because scaling a negative number down moves it toward zero.
    """
    from acquisition import to_utility
    s = np.array([-1.0, -100.0])          # log-EI: candidate 0 is much better
    pen = np.array([1.0, 0.001])          # penalize the already-worse candidate
    naive = s * pen                       # [-1.0, -0.1]
    assert np.argmax(naive) == 1, "sanity: naive product does invert the ranking"
    safe = to_utility(s, "log") * pen
    assert np.argmax(safe) == 0, "utility composition must keep the best point"
    # A uniform factor must never reorder anything, for any scale.
    for scale, vals in (("log", s), ("nonneg", np.array([0.5, 3.0])),
                        ("unbounded", np.array([-7.0, 2.0]))):
        u = to_utility(vals, scale)
        assert np.array_equal(np.argsort(u * 0.25), np.argsort(u))


def t_utility_preserves_log_magnitude():
    """log-scale utilities must keep ratios, not just order.

    Rank-normalizing log-EI would flatten an astronomically large difference in
    expected improvement into a couple of rank steps, letting a mild feasibility
    penalty overturn it. That is precisely how suggestions ended up in a
    known-failure region during development.
    """
    from acquisition import to_utility
    s = np.array([-690.0, -1.0])
    u = to_utility(s, "log")
    assert u[1] == 1.0 and u[0] < 1e-200, f"magnitude collapsed: {u}"
    # Even a strong probability penalty must not flip this.
    assert np.argmax(u * np.array([1.0, 0.01])) == 1


def t_acquisition_registry():
    for name in ACQUISITIONS:
        assert canonical_acquisition(name) == name
    assert canonical_acquisition("expected_improvement") == "ei"
    assert canonical_acquisition("LCB") == "ucb"
    try:
        canonical_acquisition("does_not_exist")
    except ValueError as e:
        assert "unknown acquisition" in str(e)
    else:
        raise AssertionError("unknown acquisition must raise")
    # Acquisitions needing an incumbent must refuse to run without one.
    for name, meta in ACQUISITIONS.items():
        if meta["needs_best"]:
            try:
                acquisition(name, np.zeros(3), np.ones(3), best=None)
            except ValueError:
                pass
            else:
                raise AssertionError(f"{name} must require 'best'")


def t_thompson_reproducible_with_rng():
    mu, sd = np.zeros(20), np.ones(20)
    a = acquisition("thompson", mu, sd, rng=np.random.default_rng(7))
    b = acquisition("thompson", mu, sd, rng=np.random.default_rng(7))
    assert np.allclose(a, b), "seeded Thompson sampling must be reproducible"


# --------------------------------------------------------------------------
# Frozen-context determinism -- the contract that was violated
# --------------------------------------------------------------------------
def _fitted_optimizer(acq="parego", mixture=True, seed=0, n=14):
    if mixture:
        sp = make_mixture_space(["A", "B", "C", "D"], total=10.0)
    else:
        sp = make_space([(0.0, 1.0)] * 3)
    objs = [Objective("f1", "minimize", transform=None),
            Objective("f2", "maximize", transform=None)]
    opt = BayesianOptimizer(sp, objs, acquisition_fn=acq, seed=seed,
                            n_candidates=600)
    X = sp.sample(n, seed=seed + 1)
    Y = np.column_stack([(X[:, 0] - 3) ** 2, X[:, 1] * 2.0])
    opt.tell(X, Y)
    opt.fit()
    return opt, sp


def t_raw_score_is_deterministic():
    """Given a frozen context, the acquisition must be a fixed function.

    This is the exact defect the original suite missed: ParEGO drew fresh
    scalarization weights on every call, so SLSQP was optimizing a moving
    target. The single-row check matters just as much -- local refinement
    evaluates one point at a time, so a candidate's score must not depend on
    which other candidates it was scored alongside.
    """
    for acq in ("parego", "ehvi"):
        opt, sp = _fitted_optimizer(acq=acq)
        ctx = opt._make_context()
        # Keep the pool at or below the EHVI pre-screen limit so that no
        # candidate is pruned; pruning is an explicit batch-level speed-up.
        X = sp.sample(min(40, opt.ehvi_prescreen), seed=99)
        a = opt._raw_score(X, ctx)
        b = opt._raw_score(X, ctx)
        assert np.allclose(a, b, equal_nan=True), \
            f"{acq}: acquisition surface changed between identical calls"
        for i in (0, 3, 17):
            single = opt._raw_score(X[i:i + 1], ctx)[0]
            assert np.isclose(single, a[i], rtol=1e-6, atol=1e-12), \
                f"{acq}: row {i} scored {single} alone but {a[i]} in a batch"


def t_context_weights_vary_between_picks():
    """Successive picks must draw new weights -- that is what spreads a batch."""
    opt, _ = _fitted_optimizer()
    ws = [opt._make_context().weights for _ in range(8)]
    assert not all(np.allclose(ws[0], w) for w in ws[1:]), \
        "ParEGO weights must vary between picks"
    for w in ws:
        assert np.isclose(w.sum(), 1.0), "weights must be a simplex vector"


def t_refine_never_worsens():
    """Local refinement must improve, or return, the frozen objective."""
    for mixture in (True, False):
        opt, sp = _fitted_optimizer(mixture=mixture)
        ctx = opt._make_context()
        X = sp.sample(30, seed=5)
        for x0 in X[:6]:
            before = float(opt._raw_score(np.atleast_2d(x0), ctx)[0])
            xr = opt._local_refine(x0, ctx)
            after = float(opt._raw_score(np.atleast_2d(xr), ctx)[0])
            assert after >= before - 1e-9, \
                f"refinement worsened the acquisition: {before} -> {after}"
            assert sp.is_feasible(xr[None, :])[0], "refined point infeasible"


def t_refine_respects_mixture_and_diversity():
    opt, sp = _fitted_optimizer(mixture=True)
    ctx = opt._make_context()
    pending = [sp.sample(1, seed=11)[0]]
    x0 = sp.sample(1, seed=12)[0]
    xr = opt._local_refine(x0, ctx, pending=pending)
    assert np.isclose(xr.sum(), 10.0, atol=1e-6), "mixture equality violated"
    assert sp.is_feasible(xr[None, :])[0]


# --------------------------------------------------------------------------
# Auto transform contract
# --------------------------------------------------------------------------
def t_auto_transform_detects_wide_range():
    o = Objective("visc", "minimize")            # transform defaults to "auto"
    y = np.array([92.0, 500.0, 5000.0, 42444.0, 1200.0])
    assert o.resolve_transform(y) == "log1p", "wide positive range needs log1p"
    assert o.active_transform == "log1p"
    # Latches: a later call must not flip it back.
    assert o.resolve_transform(np.array([1.0, 1.1, 1.2])) == "log1p"


def t_auto_transform_skips_narrow_and_signed():
    narrow = Objective("yield", "maximize")
    assert narrow.resolve_transform(np.array([70.0, 82.0, 91.0, 88.0])) is None
    signed = Objective("zeta", "maximize")
    assert signed.resolve_transform(np.array([-30.0, 5.0, 40.0])) is None


def t_explicit_transform_not_overridden():
    o = Objective("x", "minimize", transform=None)
    assert o.resolve_transform(np.array([1.0, 1e5, 1e3])) is None
    o2 = Objective("x", "minimize", transform="sqrt")
    assert o2.resolve_transform(np.array([1.0, 1e5])) == "sqrt"


def t_auto_transform_never_silently_raw():
    """An unresolved ``auto`` transform must never score on the raw scale.

    Regression test for a real defect: benchmark scoring code built fresh
    ``Objective`` instances and called ``to_min``/``scalarize`` without ever
    fitting a model, so ``auto`` stayed unresolved and every hypervolume was
    computed on untransformed values. ``forward`` now resolves lazily on first
    use, so every entry point agrees.
    """
    y = np.array([92.0, 5000.0, 42444.0])

    fresh = Objective("visc", "minimize")           # never explicitly resolved
    assert fresh.active_transform == "auto", "should start unresolved"
    got = fresh.to_min(y)
    expected = np.log1p(y)
    assert np.allclose(got, expected), \
        f"unresolved auto scored on the raw scale: {got}"
    assert fresh.active_transform == "log1p", "must latch after lazy resolve"

    # Explicit resolution and lazy resolution must agree exactly.
    eager = Objective("visc", "minimize")
    eager.resolve_transform(y)
    assert np.allclose(eager.to_min(y), got)

    # scalarize() must also see the transformed scale.
    from optimize import scalarize
    objs = [Objective("a", "minimize"), Objective("b", "maximize")]
    Y = np.column_stack([y, y[::-1]])
    s = scalarize(Y, objs)
    assert all(o.active_transform == "log1p" for o in objs), \
        "scalarize left transforms unresolved"
    assert np.all(np.isfinite(s))


def t_narrow_response_lazy_resolves_to_none():
    """Lazy resolution must also correctly decline to transform."""
    o = Objective("yield", "maximize")
    y = np.array([70.0, 82.0, 91.0, 88.0])
    assert np.allclose(o.to_min(y), -y), "narrow range should stay untransformed"
    assert o.active_transform is None


def t_transform_roundtrip():
    for tname in (None, "log", "log1p", "sqrt"):
        o = Objective("y", "minimize", transform=tname)
        y = np.array([0.5, 2.0, 50.0, 1000.0])
        assert np.allclose(o.inverse(o.forward(y)), y, rtol=1e-6), tname
        # Direction handling must round-trip too.
        omax = Objective("y", "maximize", transform=tname)
        assert np.allclose(omax.from_min(omax.to_min(y)), y, rtol=1e-6), tname
    # And for an auto objective, after lazy resolution.
    auto = Objective("y", "maximize")
    ya = np.array([1.0, 100.0, 10000.0])
    assert np.allclose(auto.from_min(auto.to_min(ya)), ya, rtol=1e-6)


def t_predictions_respect_transform_positivity():
    """With log1p, predicted means/bounds must stay non-negative."""
    sp = make_mixture_space(["A", "B", "C"], total=10.0)
    objs = [Objective("visc", "minimize")]       # auto -> log1p
    opt = BayesianOptimizer(sp, objs, seed=0, n_candidates=400)
    X = sp.sample(16, seed=2)
    Y = (10.0 ** (1.0 + X[:, 0] / 3.0)).reshape(-1, 1)   # spans decades
    opt.tell(X, Y)
    opt.fit()
    assert opt.transforms()["visc"] == "log1p"
    mu, sd = opt.predict(sp.sample(50, seed=3))
    assert np.all(mu > 0), "log1p model must not predict negative viscosity"
    assert np.all(np.isfinite(sd))


# --------------------------------------------------------------------------
# Failed experiments
# --------------------------------------------------------------------------
def t_failures_recorded_not_dropped():
    sp = make_space([(0.0, 1.0)] * 2)
    objs = [Objective("y", "minimize", transform=None)]
    opt = BayesianOptimizer(sp, objs, seed=0, n_candidates=500)
    X = sp.sample(20, seed=0)
    Y = (X ** 2).sum(axis=1).reshape(-1, 1)
    Y[X[:, 0] > 0.75] = np.nan                    # a region that always fails
    opt.tell(X, Y)
    n_fail = int(np.sum(X[:, 0] > 0.75))
    assert opt.n_failed == n_fail, "failures must be counted"
    assert opt.n_obs == len(X) - n_fail, "failures excluded from regression"
    assert len(opt.X_all) == len(X), "all attempts retained for the classifier"


def t_failures_steer_suggestions():
    """Failures must pull suggestions back toward the feasible region.

    The objective is minimized at ``x0 = 1``, but every attempt with
    ``x0 > 0.7`` fails. The controlled comparison is against an identical
    optimizer that simply never saw the failed runs (the old drop-the-row
    behaviour): that one should chase the unconstrained optimum, while the
    failure-aware one should stay near the feasible boundary.

    Note that suggesting points *at* the boundary is correct -- in a constrained
    problem the optimum lies on the constraint -- so the assertion is about
    distance from the unconstrained optimum, not about avoiding the boundary.
    """
    sp = make_space([(0.0, 1.0)] * 2)
    rng = np.random.default_rng(0)
    X = rng.random((40, 2))
    Y_true = -(X[:, :1] ** 2)                     # minimized: pushes x0 -> 1
    Y_fail = np.where(X[:, :1] > 0.7, np.nan, Y_true)
    ok = X[:, 0] <= 0.7

    aware = BayesianOptimizer(sp, [Objective("y", "minimize", transform=None)],
                              seed=0, n_candidates=1500)
    aware.tell(X, Y_fail)
    aware.fit()
    assert aware._success_clf is not None, "classifier should have been fitted"
    assert aware._success_cutoff() is not None, "filter should be active"

    # Control: the same data with failures simply discarded.
    naive = BayesianOptimizer(sp, [Objective("y", "minimize", transform=None)],
                              seed=0, n_candidates=1500)
    naive.tell(X[ok], Y_true[ok])
    naive.fit()

    a = float(np.mean(aware.ask(5)[:, 0]))
    n = float(np.mean(naive.ask(5)[:, 0]))
    assert a < n - 0.05, \
        f"failure-aware BO ({a:.3f}) should stay below the naive one ({n:.3f})"
    assert a < 0.85, f"suggestions drifted deep into the failure region: {a:.3f}"
    # And the pool itself must be largely cleared of hopeless candidates.
    frac_bad = float(np.mean(aware._candidate_pool()[:, 0] > 0.7))
    assert frac_bad < 0.15, f"{frac_bad:.0%} of the pool is in the failure region"


def t_success_filter_is_self_calibrating():
    """The cutoff scales with the classifier's own confidence on successes."""
    sp = make_space([(0.0, 1.0)] * 2)
    rng = np.random.default_rng(3)
    X = rng.random((30, 2))
    Y = np.where(X[:, :1] > 0.8, np.nan, X[:, :1])
    opt = BayesianOptimizer(sp, [Objective("y", "minimize", transform=None)],
                            seed=0, min_success_prob=0.5)
    opt.tell(X, Y)
    opt.fit()
    ref = float(np.median(opt._success_prob(opt.X_all[opt.success_all])))
    assert np.isclose(opt._success_cutoff(), 0.5 * ref)
    # Disabling the filter must switch it off entirely.
    off = BayesianOptimizer(sp, [Objective("y", "minimize", transform=None)],
                            seed=0, min_success_prob=0.0)
    off.tell(X, Y)
    off.fit()
    assert off._success_cutoff() is None
    assert not np.any(off._likely_to_fail(sp.sample(20, seed=1)))


def t_no_failures_means_no_filtering():
    """With no failed runs the classifier and filter stay out of the way."""
    sp = make_space([(0.0, 1.0)] * 2)
    opt = BayesianOptimizer(sp, [Objective("y", "minimize", transform=None)],
                            seed=0, n_candidates=400)
    X = sp.sample(15, seed=0)
    opt.tell(X, (X ** 2).sum(axis=1))
    opt.fit()
    assert opt.n_failed == 0
    assert opt._success_clf is None and opt._success_cutoff() is None
    assert np.allclose(opt._success_prob(sp.sample(10, seed=1)), 1.0)


def t_all_failures_is_graceful():
    sp = make_space([(0.0, 1.0)] * 2)
    opt = BayesianOptimizer(sp, [Objective("y", "minimize")], seed=0)
    X = sp.sample(6, seed=0)
    opt.tell(X, np.full((6, 1), np.nan))
    assert opt.n_obs == 0 and opt.n_failed == 6
    assert opt.ask(2).shape == (2, 2), "must still fall back to space filling"


# --------------------------------------------------------------------------
# Threshold constraint contract
# --------------------------------------------------------------------------
def t_threshold_steers_suggestions():
    sp = make_space([(0.0, 1.0)] * 2)
    objs = [Objective("cost", "minimize", transform=None),
            Objective("purity", "maximize", threshold=0.8, transform=None)]
    opt = BayesianOptimizer(sp, objs, seed=0, n_candidates=1500)
    rng = np.random.default_rng(1)
    X = rng.random((36, 2))
    # Cost is minimized at x0 = 1, but purity only meets spec when x0 < 0.5.
    Y = np.column_stack([-X[:, 0], 1.0 - X[:, 0]])
    opt.tell(X, Y)
    sug = opt.ask(5)
    assert np.mean(sug[:, 0] < 0.6) >= 0.6, \
        "threshold constraint failed to steer suggestions toward feasibility"
    mask = opt.feasible_mask()
    assert mask.shape == (36,) and mask.dtype == bool


def t_batch_is_diverse_for_every_acquisition():
    sp = make_mixture_space(["A", "B", "C", "D"], total=10.0)
    for acq in ("parego", "ehvi", "ucb"):
        objs = [Objective("f1", "minimize", transform=None),
                Objective("f2", "maximize", transform=None)]
        opt = BayesianOptimizer(sp, objs, acquisition_fn=acq, seed=0,
                                n_candidates=800)
        X = sp.sample(14, seed=4)
        opt.tell(X, np.column_stack([(X[:, 0] - 3) ** 2, X[:, 1]]))
        b = opt.ask(4)
        assert np.allclose(b.sum(axis=1), 10.0, atol=1e-6), acq
        d = np.linalg.norm(b[:, None] - b[None], axis=2)
        np.fill_diagonal(d, np.inf)
        assert d.min() > 1e-3, f"{acq}: batch collapsed (min dist {d.min():.2e})"


def t_mixture_sampling_uniformity():
    """Quantify the bounded-simplex sampling distortion, don't just assume it.

    ``ParameterSpace.sample`` uses rejection sampling on the simplex and only
    falls back to repair-projection when the bounds are too tight for rejection
    to work. Repair pushes points onto bound faces, so the fallback is *not*
    uniform. This test measures how much mass ends up on the boundary and fails
    if the primary (rejection) path silently degrades into it.
    """
    # Loose bounds: rejection should succeed, so almost nothing sits on a face.
    loose = make_mixture_space(["A", "B", "C", "D"], total=10.0)
    X = loose.sample(4000, seed=0)
    assert np.allclose(X.sum(axis=1), 10.0, atol=1e-6)
    lo, hi = loose.bounds
    on_face = np.mean(np.any((X <= lo + 1e-9) | (X >= hi - 1e-9), axis=1))
    assert on_face < 0.05, \
        f"unbounded simplex sampling put {on_face:.1%} of points on a face"

    # Marginals of a uniform Dirichlet sample should be close to total/d in mean.
    assert np.allclose(X.mean(axis=0), 10.0 / 4, atol=0.25), X.mean(axis=0)

    # Tight bounds: the repair fallback engages. Feasibility must still hold,
    # and we record (rather than assume) the boundary concentration.
    tight = make_mixture_space(["A", "B", "C", "D"], total=10.0,
                               lower=[2.4, 2.4, 2.4, 2.4],
                               upper=[2.6, 2.6, 2.6, 2.6])
    Xt = tight.sample(1000, seed=0)
    assert np.allclose(Xt.sum(axis=1), 10.0, atol=1e-6)
    assert np.all(tight.is_feasible(Xt)), "tight-bound sampling produced infeasible"


def t_mixture_pool_covers_the_region():
    """The candidate pool must reach the whole feasible region, not one corner.

    If the pool systematically missed part of the simplex the optimizer could
    never suggest anything there, regardless of how good the acquisition is.
    """
    sp = make_mixture_space(["A", "B", "C", "D"], total=10.0,
                            lower=[1.0, 0.0, 0.0, 0.0],
                            upper=[7.0, 6.0, 6.0, 6.0])
    objs = [Objective("y", "minimize", transform=None)]
    opt = BayesianOptimizer(sp, objs, seed=0, n_candidates=4000)
    X = sp.sample(20, seed=1)
    opt.tell(X, (X[:, :1] - 3.0) ** 2)
    opt.fit()
    pool = opt._candidate_pool()
    assert np.all(sp.is_feasible(pool))
    # Each component's sampled range should cover most of its attainable range.
    lo, hi = sp.bounds
    for j in range(sp.dim):
        attainable_hi = min(hi[j], sp.total - lo.sum() + lo[j])
        span = pool[:, j].max() - pool[:, j].min()
        assert span > 0.5 * (attainable_hi - lo[j]), \
            f"component {j}: pool spans only {span:.2f} of {attainable_hi - lo[j]:.2f}"


def t_library_selection_basics():
    """Selecting from a fixed candidate library must return valid, novel rows."""
    from optimize import select_from_library
    rng = np.random.default_rng(0)
    F = rng.random((300, 4))
    obs = list(range(12))
    Y = ((F[obs, 0] - 0.3) ** 2).reshape(-1, 1)
    out = select_from_library(F, obs, Y, [Objective("y", "minimize")], q=5,
                              seed=0, labels=[f"mol{i}" for i in range(300)])
    sel = out["selected_idx"]
    assert len(sel) == 5
    assert len(set(sel)) == 5, "must not select the same candidate twice"
    assert not (set(sel) & set(obs)), "must not re-select measured candidates"
    assert all(0 <= i < 300 for i in sel)
    assert out["selected_labels"] == [f"mol{i}" for i in sel]
    assert out["n_library"] == 300 and out["n_observed"] == 12
    assert len(out["predicted_mean"]) == 5


def t_library_selection_finds_good_candidates():
    """Selection must beat random picking from the same library."""
    from optimize import select_from_library
    rng = np.random.default_rng(1)
    F = rng.random((400, 3))
    truth = (F[:, 0] - 0.25) ** 2 + 0.3 * (F[:, 1] - 0.75) ** 2
    obs = list(rng.choice(400, 20, replace=False))
    Y = truth[obs].reshape(-1, 1)
    out = select_from_library(F, obs, Y, [Objective("y", "minimize")], q=8,
                              seed=0, diversity=0.0)
    picked = truth[out["selected_idx"]].mean()
    remaining = np.setdiff1d(np.arange(400), obs)
    random_mean = truth[remaining].mean()
    assert picked < 0.5 * random_mean, \
        f"selection ({picked:.4f}) no better than random ({random_mean:.4f})"


def t_library_handles_descriptor_scales():
    """Wildly different descriptor scales must not dominate the kernel.

    Real descriptor tables mix molecular weight (~10^2), LogP (~10^0) and TPSA
    (~10^1). Without internal standardization the largest-range column would
    dominate the GP kernel and selection would effectively ignore the others.
    """
    from optimize import select_from_library
    rng = np.random.default_rng(2)
    n = 300
    mw = rng.uniform(150, 600, n)            # ~10^2
    logp = rng.uniform(-1, 6, n)             # ~10^0
    tpsa = rng.uniform(10, 150, n)           # ~10^1
    F = np.column_stack([mw, logp, tpsa])
    # The response depends ONLY on logp, the smallest-magnitude descriptor.
    truth = (logp - 2.0) ** 2
    obs = list(rng.choice(n, 25, replace=False))
    out = select_from_library(F, obs, truth[obs].reshape(-1, 1),
                              [Objective("y", "minimize")], q=6, seed=0,
                              feature_names=["MW", "LogP", "TPSA"],
                              diversity=0.0)
    sel_logp = logp[out["selected_idx"]]
    assert np.mean(np.abs(sel_logp - 2.0)) < 1.0, \
        f"failed to find the LogP optimum; selected LogP {sel_logp}"


def t_library_batch_is_diverse():
    """Diversity control must prevent a batch of near-duplicate analogues."""
    from optimize import select_from_library
    rng = np.random.default_rng(3)
    # A tight cluster of near-identical candidates plus a spread-out remainder.
    cluster = np.tile([0.2, 0.2], (60, 1)) + rng.normal(0, 1e-3, (60, 2))
    spread = rng.random((240, 2))
    F = np.vstack([cluster, spread])
    truth = ((F[:, 0] - 0.2) ** 2 + (F[:, 1] - 0.2) ** 2)   # optimum in cluster
    obs = list(rng.choice(np.arange(60, 300), 20, replace=False))
    out = select_from_library(F, obs, truth[obs].reshape(-1, 1),
                              [Objective("y", "minimize")], q=6, seed=0,
                              diversity=0.5)
    sel = np.array(out["selected_idx"])
    n_cluster = int(np.sum(sel < 60))
    assert n_cluster <= 3, \
        f"{n_cluster}/6 picks came from one near-duplicate cluster"


def t_library_multiobjective_and_failures():
    """Library selection must support several objectives and failed rows."""
    from optimize import select_from_library
    rng = np.random.default_rng(4)
    F = rng.random((250, 3))
    obs = list(range(30))
    Y = np.column_stack([F[obs, 0], -F[obs, 1]])
    Y[::7, 0] = np.nan                        # some syntheses failed
    out = select_from_library(F, obs, Y,
                              [Objective("a", "minimize"),
                               Objective("b", "maximize")], q=4, seed=0)
    assert len(out["selected_idx"]) == 4
    assert out["n_failed"] > 0, "failed rows should be counted"
    assert out["n_observed"] == 30
    assert set(out["predicted_mean"][0]) == {"a", "b"}


def t_diverse_subset_cold_start():
    """The cold-start selector must spread out and never repeat."""
    from optimize import select_diverse_subset
    rng = np.random.default_rng(5)
    F = np.vstack([rng.normal(0, 0.01, (100, 2)),        # tight blob
                   rng.normal(5, 0.01, (100, 2)),        # distant blob
                   rng.normal(-5, 0.01, (100, 2))])      # third blob
    out = select_diverse_subset(F, 6, seed=0)
    idx = out["selected_idx"]
    assert len(idx) == len(set(idx)) == 6
    # With three well-separated blobs, a maximin pick must touch all three.
    blobs = {i // 100 for i in idx}
    assert blobs == {0, 1, 2}, f"cold start missed blobs, hit {blobs}"


def t_library_guards():
    """Malformed library input must fail loudly, not silently mis-select."""
    from optimize import select_from_library
    F = np.random.default_rng(6).random((50, 2))
    objs = [Objective("y", "minimize")]
    for bad, msg in [
        (dict(observed_idx=[0, 1, 2], Y=np.zeros((2, 1))), "same length"),
        (dict(observed_idx=[], Y=np.zeros((0, 1))), "at least one"),
        (dict(observed_idx=[0, 1], Y=np.zeros((2, 1))), "at least 3"),
    ]:
        try:
            select_from_library(F, objectives=objs, q=1, **bad)
        except ValueError as e:
            assert msg in str(e), f"expected {msg!r}, got {e}"
        else:
            raise AssertionError(f"expected ValueError mentioning {msg!r}")


def t_reproducibility():
    """Same seed, same suggestions."""
    def run():
        sp = make_mixture_space(["A", "B", "C"], total=1.0)
        opt = BayesianOptimizer(sp, [Objective("y", "minimize", transform=None)],
                                seed=42, n_candidates=500)
        X = sp.sample(12, seed=3)
        opt.tell(X, ((X[:, :1] - 0.4) ** 2))
        return opt.ask(3)
    assert np.allclose(run(), run()), "identical seeds must give identical batches"


# --------------------------------------------------------------------------
# Regression tests for review findings on PR #290
# --------------------------------------------------------------------------
def t_loo_r2_is_out_of_sample():
    """In-sample R^2 of an interpolating GP is ~1 even on pure noise."""
    from models import fit_gp
    rng = np.random.default_rng(0)
    U = rng.random((20, 3))
    noise = fit_gp(U, rng.normal(size=20), seed=0).loo_r2()
    assert noise < 0.3, f"pure noise must not look predictive (loo_r2={noise:.3f})"
    U = rng.random((30, 2))
    smooth = fit_gp(U, np.sin(3 * U[:, 0]) + U[:, 1] ** 2, seed=0).loo_r2()
    assert smooth > 0.8, f"smooth response should be predictive (loo_r2={smooth:.3f})"


def t_loo_r2_matches_brute_force():
    """Closed form equals refitting n times with the hyperparameters fixed."""
    from sklearn.gaussian_process import GaussianProcessRegressor
    from models import fit_gp
    rng = np.random.default_rng(1)
    U = rng.random((15, 2))
    y = np.sin(4 * U[:, 0]) + 0.1 * rng.normal(size=15)
    gp = fit_gp(U, y, backend="sklearn", seed=0)
    z = (y - gp._mu) / gp._sd
    pred = np.empty(15)
    for i in range(15):
        m = np.arange(15) != i
        g = GaussianProcessRegressor(kernel=gp._model.kernel_, optimizer=None,
                                     alpha=gp._model.alpha, normalize_y=False)
        g.fit(U[m], z[m])
        pred[i] = g.predict(U[i:i + 1])[0] * gp._sd + gp._mu
    brute = 1 - np.sum((y - pred) ** 2) / np.sum((y - y.mean()) ** 2)
    assert abs(gp.loo_r2() - brute) < 1e-6, (gp.loo_r2(), brute)


def t_acquisition_names_never_fall_back():
    """Multi-objective or misspelt names must not silently become 'std'."""
    for name in ("parego", "ehvi", "qparego", "EHVI"):
        try:
            acquisition(name, np.zeros(3), np.ones(3), best=0.0)
        except ValueError:
            pass
        else:
            raise AssertionError(f"acquisition('{name}') must raise")
    sp = make_space({"a": (0, 1), "b": (0, 1)})
    rng = np.random.default_rng(0)
    X = rng.random((12, 2))
    Y = np.column_stack([(X[:, 0] - .3) ** 2, X[:, 1]])
    P = sp.sample(200, seed=1)

    def raw(acq):
        o = BayesianOptimizer(sp, [Objective("f1", "minimize", transform=None),
                                   Objective("f2", "maximize", transform=None)],
                              acquisition_fn=acq, seed=0, n_candidates=200)
        o.tell(X, Y)
        o.fit()
        return o._raw_score(P, o._make_context())
    assert np.allclose(raw("EHVI"), raw("ehvi"))
    assert np.allclose(raw("qNEHVI"), raw("ehvi"))
    assert np.allclose(raw("qparego"), raw("parego"))
    for bad, objs in (("nope", [Objective("y")]), ("ehvi", [Objective("y")])):
        try:
            BayesianOptimizer(sp, objs, acquisition_fn=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"acquisition_fn='{bad}' must raise")


def t_pareto_plot_respects_directions():
    from plots import _directed_front, plot_pareto
    import tempfile
    Y = np.array([[1.0, 10.0], [2.0, 20.0], [3.0, 5.0]])   # min f1, max f2
    front = _directed_front(Y, np.array([1.0, -1.0]))
    assert sorted(map(tuple, front.tolist())) == [(1.0, 10.0), (2.0, 20.0)]
    objs = [Objective("f1", "minimize"), Objective("f2", "maximize")]
    path = os.path.join(tempfile.mkdtemp(), "p.png")
    assert os.path.exists(plot_pareto(Y, objs, path))


def t_final_results_is_strict_json():
    import json
    import tempfile
    import io_utils
    tmp = tempfile.mkdtemp()
    io_utils.quick_setup(tmp, os.path.join(tmp, "o"), os.path.join(tmp, "w"))
    path = io_utils.save_final_results(
        {"r2": float("nan"), "x": np.float64("inf"), "arr": np.array([1.0, np.nan])})

    def reject(c):
        raise ValueError(f"non-standard JSON constant {c}")
    data = json.loads(open(path, encoding="utf-8").read(), parse_constant=reject)
    assert data["results"] == {"r2": None, "x": None, "arr": [1.0, None]}
    # Non-float64 NumPy floats go through the encoder itself.
    assert json.dumps([np.float32("nan")], cls=io_utils.JSONSafeEncoder) == "[null]"


def t_ccd_orthogonal_and_inside_bounds():
    from doe import design_diagnostics, doe_central_composite
    for k, n0 in ((2, 4), (3, 4), (4, 6)):
        sp = make_space([(-1.0, 1.0)] * k)
        D = doe_central_composite(sp, alpha="orthogonal", center_points=n0)
        Q = D ** 2 - (D ** 2).mean(axis=0)
        assert abs(Q[:, 0] @ Q[:, 1]) < 1e-9, f"k={k}: quadratic terms not orthogonal"
        assert np.all(sp.is_feasible(D))
        assert np.isclose(np.abs(D).max(), 1.0), "axial points should sit on the bounds"
    try:
        doe_central_composite(make_space([(0, 1)] * 2), face="circumscribed")
    except ValueError:
        pass
    else:
        raise AssertionError("circumscribed CCD would leave the bounds; must raise")
    mx = make_mixture_space(["A", "B", "C"], total=10.0)
    d_eff = design_diagnostics(mx, mx.sample(12, seed=0))["d_efficiency_first_order"]
    assert np.isfinite(d_eff) and d_eff > 0, d_eff


def t_ehvi_counts_improvement_beyond_ideal():
    from acquisition import expected_hypervolume_improvement
    front = np.zeros((1, 3))
    ref = np.ones(3)
    e = expected_hypervolume_improvement(np.full((1, 3), -1.0), np.full((1, 3), 1e-9),
                                         front, ref)
    assert abs(e[0] - 7.0) < 1e-6, e
    # A point inside the region the front already dominates gains nothing.
    e = expected_hypervolume_improvement(np.full((1, 3), 0.5), np.full((1, 3), 1e-9),
                                         front, ref)
    assert abs(e[0]) < 1e-9, e
    # A user reference point that no observation meets yet: the front
    # dominates nothing, so the improvement is the whole box [s, ref].
    e = expected_hypervolume_improvement(np.array([[0.5, 0.5, 0.0]]),
                                         np.full((1, 3), 1e-9),
                                         np.array([[0.0, 0.0, 2.0]]), ref)
    assert abs(e[0] - 0.25) < 1e-6, e


def t_integer_factors_are_suggested_as_integers():
    from optimize import suggest_next
    sp = make_space({"n": (1, 10), "t": (0, 1)}, kinds=["integer", "continuous"])
    rng = np.random.default_rng(0)
    X = np.column_stack([rng.integers(1, 11, 10), rng.random(10)]).astype(float)
    out = suggest_next(X, (X[:, 0] - 6.3) ** 2 + X[:, 1], sp,
                       [Objective("y", "minimize")], q=3, seed=0)
    Xn = np.asarray(out["X"])
    assert np.allclose(Xn[:, 0], np.round(Xn[:, 0])), Xn
    assert [s["n"] for s in out["suggestions"]] == Xn[:, 0].astype(int).tolist()


def main():
    tests = [
        ("rank/order preserving", t_rank_order_preserving),
        ("rank/non-finite handling", t_rank_handles_negative_and_nonfinite),
        ("utility/composition cannot invert", t_composition_cannot_invert),
        ("utility/log magnitude preserved", t_utility_preserves_log_magnitude),
        ("acq/registry + validation", t_acquisition_registry),
        ("acq/thompson reproducible", t_thompson_reproducible_with_rng),
        ("ctx/raw score deterministic", t_raw_score_is_deterministic),
        ("ctx/weights vary per pick", t_context_weights_vary_between_picks),
        ("refine/never worsens", t_refine_never_worsens),
        ("refine/respects constraints", t_refine_respects_mixture_and_diversity),
        ("transform/auto detects wide range", t_auto_transform_detects_wide_range),
        ("transform/auto skips narrow", t_auto_transform_skips_narrow_and_signed),
        ("transform/never silently raw", t_auto_transform_never_silently_raw),
        ("transform/lazy resolves to none", t_narrow_response_lazy_resolves_to_none),
        ("transform/explicit wins", t_explicit_transform_not_overridden),
        ("transform/roundtrip", t_transform_roundtrip),
        ("transform/positivity preserved", t_predictions_respect_transform_positivity),
        ("fail/recorded not dropped", t_failures_recorded_not_dropped),
        ("fail/steers suggestions", t_failures_steer_suggestions),
        ("fail/filter self-calibrating", t_success_filter_is_self_calibrating),
        ("fail/inactive without failures", t_no_failures_means_no_filtering),
        ("fail/all-failed graceful", t_all_failures_is_graceful),
        ("threshold/steers suggestions", t_threshold_steers_suggestions),
        ("batch/diverse for all acqs", t_batch_is_diverse_for_every_acquisition),
        ("sampling/mixture uniformity", t_mixture_sampling_uniformity),
        ("sampling/pool covers region", t_mixture_pool_covers_the_region),
        ("library/selection basics", t_library_selection_basics),
        ("library/beats random picking", t_library_selection_finds_good_candidates),
        ("library/descriptor scales", t_library_handles_descriptor_scales),
        ("library/batch diversity", t_library_batch_is_diverse),
        ("library/multi-obj + failures", t_library_multiobjective_and_failures),
        ("library/cold start spread", t_diverse_subset_cold_start),
        ("library/input guards", t_library_guards),
        ("repro/deterministic given seed", t_reproducibility),
        ("model/loo r2 is out of sample", t_loo_r2_is_out_of_sample),
        ("model/loo r2 matches brute force", t_loo_r2_matches_brute_force),
        ("acq/names never fall back", t_acquisition_names_never_fall_back),
        ("plot/pareto respects directions", t_pareto_plot_respects_directions),
        ("io/final results strict json", t_final_results_is_strict_json),
        ("doe/ccd orthogonal + in bounds", t_ccd_orthogonal_and_inside_bounds),
        ("acq/ehvi beyond ideal point", t_ehvi_counts_improvement_beyond_ideal),
        ("space/integer suggestions", t_integer_factors_are_suggested_as_integers),
    ]
    print("Component-contract tests\n")
    for name, fn in tests:
        check(name, fn)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
else:
    # Make every t_* check collectable by pytest as test_*.
    for _name, _fn in list(globals().items()):
        if _name.startswith("t_") and callable(_fn):
            globals()["test_" + _name[2:]] = _fn
