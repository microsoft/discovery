"""Self-test suite for the bo-doe agent library.

Run:  python scripts/test_bodoe.py
Exercises the parameter spaces, every DoE generator, the GP backends, all
acquisitions, single- and multi-objective BO, and the analytic benchmarks.
"""
from __future__ import annotations

import os
import sys
import traceback

import numpy as np

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app")
sys.path.insert(0, APP)

from bodoe_utils import *  # noqa: E402,F403

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


# ---------------------------------------------------------------- spaces
def t_box_space():
    sp = make_space({"temp": (60, 120), "time": (1, 24), "cat": (0.1, 5.0)})
    X = sp.sample(50, seed=0)
    assert X.shape == (50, 3)
    assert np.all(sp.is_feasible(X))
    assert np.allclose(sp.from_unit(sp.to_unit(X)), X, atol=1e-9)


def t_mixture_space():
    sp = make_mixture_space(["A", "B", "C", "D"], total=10.0)
    X = sp.sample(200, seed=1)
    assert np.allclose(X.sum(axis=1), 10.0, atol=1e-6), X.sum(axis=1)[:5]
    assert np.all(sp.is_feasible(X))


def t_mixture_bounds():
    sp = make_mixture_space(["A", "B", "C"], total=10.0,
                            lower=[2.0, 1.0, 0.0], upper=[6.0, 5.0, 4.0])
    X = sp.sample(300, seed=2)
    assert np.allclose(X.sum(axis=1), 10.0, atol=1e-6)
    assert np.all(sp.is_feasible(X)), "bounded simplex sampling produced infeasible pts"


def t_repair():
    sp = make_mixture_space(["A", "B", "C"], total=1.0, upper=[0.5, 0.5, 0.5])
    bad = np.array([[2.0, -1.0, 0.3], [0.9, 0.9, 0.9]])
    fixed = sp.repair(bad)
    assert np.allclose(fixed.sum(axis=1), 1.0, atol=1e-6)
    assert np.all(sp.is_feasible(fixed))


# ------------------------------------------------------------------ DoE
def t_designs_box():
    sp = make_space([(0, 1)] * 3, names=list("abc"))
    for name, kw in [("full_factorial", {"levels": 3}),
                     ("fractional_factorial", {"resolution_fraction": 1}),
                     ("plackett_burman", {}),
                     ("ccd", {}),
                     ("box_behnken", {}),
                     ("lhs", {"n": 20}),
                     ("sobol", {"n": 16})]:
        X = generate_design(sp, name, **kw)
        assert X.ndim == 2 and X.shape[1] == 3, name
        assert np.all(sp.is_feasible(X)), f"{name} produced out-of-bounds runs"
        d = design_diagnostics(sp, X)
        assert d["n_runs"] == len(X)


def t_designs_mixture():
    sp = make_mixture_space(["A", "B", "C", "D"], total=10.0)
    for name, kw in [("simplex_lattice", {"degree": 3}),
                     ("simplex_centroid", {}),
                     ("extreme_vertices", {}),
                     ("mixture_space_filling", {"n": 24})]:
        X = generate_design(sp, name, **kw)
        assert len(X) > 0, name
        assert np.allclose(X.sum(axis=1), 10.0, atol=1e-6), name
        assert np.all(sp.is_feasible(X)), name


def t_design_guardrails():
    sp = make_mixture_space(["A", "B", "C"], total=1.0)
    try:
        generate_design(sp, "ccd")
    except ValueError as e:
        assert "mixture" in str(e)
    else:
        raise AssertionError("CCD on a mixture space should raise")


# ----------------------------------------------------------------- model
def t_gp_fit():
    rng = np.random.default_rng(0)
    U = rng.random((40, 3))
    y = np.sin(3 * U[:, 0]) + U[:, 1] ** 2 - 0.5 * U[:, 2]
    gp = fit_gp(U, y, seed=0)
    mu, sd = gp.predict(U)
    assert np.allclose(mu, y, atol=0.15), np.abs(mu - y).max()
    assert np.all(sd >= 0)
    assert gp.loo_r2() > 0.9


# ----------------------------------------------------------- acquisitions
def t_acquisitions():
    mu = np.array([0.0, 1.0, -1.0])
    sd = np.array([0.1, 0.5, 0.5])
    for name in ["ei", "logei", "pi", "ucb", "mean", "std", "thompson"]:
        v = acquisition(name, mu, sd, best=0.0)
        assert v.shape == (3,) and np.all(np.isfinite(v)), name
    assert expected_improvement(mu, sd, best=0.0)[2] > \
        expected_improvement(mu, sd, best=0.0)[1], "EI must prefer the better mean"


def t_pareto_hv():
    Y = np.array([[1.0, 4.0], [2.0, 2.0], [4.0, 1.0], [3.0, 5.0]])
    m = pareto_mask(Y)
    assert m.tolist() == [True, True, True, False]
    hv = hypervolume(Y, [5.0, 6.0])
    assert hv > 0
    # exact 2-D check
    assert abs(hv - ((5 - 1) * (6 - 4) + (5 - 2) * (4 - 2) + (5 - 4) * (2 - 1))) < 1e-9


def t_ehvi():
    Y = np.array([[1.0, 4.0], [2.0, 2.0], [4.0, 1.0]])
    mu = np.array([[1.5, 1.5], [4.5, 5.5]])
    sd = np.array([[0.2, 0.2], [0.2, 0.2]])
    e = expected_hypervolume_improvement(mu, sd, Y, [5.0, 6.0], mc_samples=64)
    assert e[0] > e[1], "EHVI should favour the point improving the front"


# --------------------------------------------------------------------- BO
def _branin(X):
    x1 = X[:, 0]
    x2 = X[:, 1]
    a, b, c = 1.0, 5.1 / (4 * np.pi ** 2), 5 / np.pi
    r, s, t = 6.0, 10.0, 1 / (8 * np.pi)
    return (a * (x2 - b * x1 ** 2 + c * x1 - r) ** 2 +
            s * (1 - t) * np.cos(x1) + s).reshape(-1, 1)


def t_bo_branin():
    sp = make_space([(-5.0, 10.0), (0.0, 15.0)], names=["x1", "x2"])
    objs = [Objective("branin", "minimize")]
    bo = run_bo_campaign(_branin, sp, objs, n_init=8, n_iter=22, seed=0)
    rs = run_random_search(_branin, sp, objs, n_evals=30, seed=0)
    best_bo = bo["best"]["y"]["branin"]
    best_rs = rs["best"]["y"]["branin"]
    print(f"        branin: BO={best_bo:.4f} random={best_rs:.4f} (opt=0.3979)")
    assert best_bo < 1.0, f"BO failed to approach the Branin optimum: {best_bo}"
    assert best_bo < best_rs, "BO must beat random search on Branin"


def t_bo_mixture_constraint():
    sp = make_mixture_space(["A", "B", "C", "D"], total=10.0)
    target = np.array([4.0, 3.0, 2.0, 1.0])

    def f(X):
        return ((X - target) ** 2).sum(axis=1).reshape(-1, 1)

    res = run_bo_campaign(f, sp, [Objective("err", "minimize")],
                          n_init=10, n_iter=30, seed=1)
    X = np.array(res["X"])
    assert np.allclose(X.sum(axis=1), 10.0, atol=1e-5), "BO violated the mixture sum"
    print(f"        mixture recovery err = {res['best']['y']['err']:.4f}")
    assert res["best"]["y"]["err"] < 1.0


def t_bo_batch_and_askell():
    sp = make_mixture_space(["A", "B", "C"], total=1.0)
    objs = [Objective("y", "minimize")]
    opt = BayesianOptimizer(sp, objs, seed=0)
    X = sp.sample(12, seed=3)
    opt.tell(X, ((X[:, :1] - 0.4) ** 2))
    batch = opt.ask(4)
    assert batch.shape == (4, 3)
    assert np.allclose(batch.sum(axis=1), 1.0, atol=1e-6)
    d = np.linalg.norm(batch[:, None] - batch[None], axis=2)
    np.fill_diagonal(d, np.inf)
    assert d.min() > 1e-3, "batch collapsed onto a single point"


def t_multi_objective():
    sp = make_space([(0.0, 1.0)] * 2, names=["x1", "x2"])

    def zdt1(X):
        f1 = X[:, 0]
        g = 1 + 9 * X[:, 1]
        f2 = g * (1 - np.sqrt(f1 / g))
        return np.column_stack([f1, f2])

    objs = [Objective("f1", "minimize"), Objective("f2", "minimize")]
    res = run_bo_campaign(zdt1, sp, objs, n_init=8, n_iter=24, seed=0,
                          ref_point=[1.2, 12.0])
    assert res["pareto"]["n_pareto"] >= 3
    hv_bo = res["hv_trace"][-1]
    rs = run_random_search(zdt1, sp, objs, n_evals=32, seed=0, ref_point=[1.2, 12.0])
    print(f"        ZDT1 hypervolume: BO={hv_bo:.4f} random={rs['hv_trace'][-1]:.4f}")
    assert hv_bo >= rs["hv_trace"][-1] * 0.98


def t_thresholds():
    sp = make_space([(0.0, 1.0)] * 2, names=["x1", "x2"])
    objs = [Objective("y", "minimize", threshold=0.2)]
    opt = BayesianOptimizer(sp, objs, seed=0)
    X = sp.sample(12, seed=0)
    opt.tell(X, (X ** 2).sum(axis=1))
    assert opt.feasible_mask().shape == (12,)
    assert opt.ask(2).shape == (2, 2)


def t_suggest_next_api():
    sp = make_mixture_space(["A", "B", "C", "D"], total=10.0)
    objs = [Objective("visc", "minimize"), Objective("mod", "maximize")]
    X = sp.sample(16, seed=5)
    Y = np.column_stack([X[:, 0] * 2 + 1, X[:, 1] * 3])
    out = suggest_next(X, Y, sp, objs, q=3, seed=0)
    assert len(out["suggestions"]) == 3
    assert set(out["suggestions"][0]) == {"A", "B", "C", "D"}
    assert "predicted_mean" in out and "model_r2" in out
    assert np.allclose(np.array(out["X"]).sum(axis=1), 10.0, atol=1e-6)


def t_scalarize():
    objs = [Objective("a", "minimize", weight=1.0),
            Objective("b", "maximize", weight=2.0)]
    Y = np.array([[1.0, 10.0], [2.0, 1.0]])
    s = scalarize(Y, objs)
    assert s[0] < s[1], "low-a/high-b must score better"


# ------------------------------------------------------------------ plots
def t_plots():
    # Use a temp directory so the suite runs from a read-only checkout
    # (e.g. mounted into the container).
    import tempfile
    tmp = tempfile.mkdtemp(prefix="bodoe_plots_")
    rng = np.random.default_rng(0)
    Y = rng.random((30, 2))
    X = rng.random((30, 3))
    plot_convergence({"bo": np.minimum.accumulate(rng.random((5, 20)), axis=1)},
                     os.path.join(tmp, "conv.png"))
    plot_pareto(Y, ["f1", "f2"], os.path.join(tmp, "pareto.png"))
    plot_design(X, list("abc"), os.path.join(tmp, "design.png"))
    plot_parity(Y[:, 0], Y[:, 0] + 0.05, os.path.join(tmp, "parity.png"))
    plot_ternary_mixture(X, list("abc"), os.path.join(tmp, "tern.png"))
    plot_benchmark({"BO": 12, "Random": 30}, os.path.join(tmp, "bench.png"))
    for f in ["conv.png", "pareto.png", "design.png", "parity.png", "tern.png",
              "bench.png"]:
        assert os.path.getsize(os.path.join(tmp, f)) > 1000, f


def main():
    print(f"GP backends available: {available_backends()}\n")
    tests = [
        ("space/box", t_box_space),
        ("space/mixture", t_mixture_space),
        ("space/mixture-bounded", t_mixture_bounds),
        ("space/repair", t_repair),
        ("doe/box designs", t_designs_box),
        ("doe/mixture designs", t_designs_mixture),
        ("doe/guardrails", t_design_guardrails),
        ("model/gp fit", t_gp_fit),
        ("acq/single-objective", t_acquisitions),
        ("acq/pareto+hypervolume", t_pareto_hv),
        ("acq/ehvi", t_ehvi),
        ("bo/branin vs random", t_bo_branin),
        ("bo/mixture constraint", t_bo_mixture_constraint),
        ("bo/batch diversity", t_bo_batch_and_askell),
        ("bo/multi-objective ZDT1", t_multi_objective),
        ("bo/threshold constraints", t_thresholds),
        ("api/suggest_next", t_suggest_next_api),
        ("api/scalarize", t_scalarize),
        ("plots", t_plots),
    ]
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
