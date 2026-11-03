# BO & DoE Agent

## Overview

Bayesian optimization and design of experiments for expensive, real-world experiments.

This agent answers one question well: **which experiments should I run next?**
It plans campaigns from scratch, generates classical and mixture designs, fits
Gaussian-process surrogates to whatever data you already have, and proposes the
next batch under single- or multi-objective goals with hard specification limits.

---

## Prerequisites

* A Microsoft Discovery workspace and project with a CPU nodepool
  (`Standard_D4s_v6` or `Standard_D8s_v6` recommended; no GPU needed).
* An Azure Container Registry the project can pull from, with the `bodoe` image
  built from [tools/bodoe/Dockerfile](tools/bodoe/Dockerfile) and pushed.
* The `bodoe` tool registered in Discovery and its ID bound to the
  `{{bodoeToolId}}` placeholder in [agent.yaml](agent.yaml).
* For warm-start optimization: measured data (CSV/Excel) uploaded to the
  project storage so it is mounted under `/input`.

## Architecture

A single prompt agent ([agent.yaml](agent.yaml)) writes one Python script per
job and runs it on the `bodoe` Discovery-managed tool. The tool is a CPU
container with BoTorch, GPyTorch, torch (CPU), scikit-learn and SciPy, plus
the `bodoe_utils` package under [tools/bodoe/app](tools/bodoe/app):

| Module | Responsibility |
|---|---|
| `space.py` | Box and mixture/simplex parameter spaces, sampling, repair |
| `doe.py` | Classical, space-filling and mixture designs |
| `models.py` | GP surrogates (BoTorch / scikit-learn) and success classifier |
| `acquisition.py` | Acquisition registry (EI, LogEI, UCB, Thompson, EHVI, ...) |
| `optimize.py` | Ask/tell optimizer, `suggest_next`, library selection |
| `plots.py`, `io_utils.py` | Plots and `/input` / `/output` I/O helpers |

Inputs are read from `/input`; results, plots and `final_results.json` are
written to `/output`.

## Tools

| Tool | Path | Description |
|---|---|---|
| `bodoe` | [tools/bodoe/tool.yaml](tools/bodoe/tool.yaml) | Python code environment for Bayesian optimization and DoE (CPU, 2-8 vCPU, 8-32 GiB RAM). |

## Configuration

| Setting | Where | Notes |
|---|---|---|
| `{{CHAT-MODEL}}` | [agent.yaml](agent.yaml) | Chat model deployment used by the agent. |
| `{{bodoeToolId}}` | [agent.yaml](agent.yaml) | ID of the registered `bodoe` tool. |
| Image | [tools/bodoe/tool.yaml](tools/bodoe/tool.yaml) | `{name}.azurecr.io/bodoe:latest`; replace `{name}` with your registry. |
| Compute | [tools/bodoe/tool.yaml](tools/bodoe/tool.yaml) | CPU-only static pool; adjust `min_resources` / `max_resources` as needed. |

Per-job inputs the agent asks for: factor names and bounds (or mixture total
and component bounds), objectives with directions and optional spec limits,
batch size `q`, and any measured data.

---

## Relationship to BoTorch (read this first)

This is **not a BoTorch replacement.** The tool runs an arbitrary Python script
(`command: python "/{{scriptName}}"`) in a container that has BoTorch, GPyTorch
and torch installed, so the agent can and should call BoTorch directly whenever
BoTorch is the better tool.

Measured on BoTorch's own tutorial problem, BoTorch's gradient-based acquisition
optimization **beats this library** — 96.4% of the maximum hypervolume versus
86.6%. A same-container, same-budget head-to-head reproduces the gap
(55.75 vs 49.42).

So:

| Situation | Use |
|---|---|
| Unconstrained box space, quality matters most | **BoTorch directly** |
| Mixture / simplex constraints | this library — BoTorch has no native mixture support |
| Classical DoE, screening, response surface | this library — BoTorch has none |
| Failed experiments, spec limits, auto transforms | this library |
| "What should I run next?" with a readable report | this library |
| Best of both | this library's design + feasible pool, BoTorch's surrogate + acquisition |

What this library adds is the **constraint and workflow layer** around an
optimizer, plus a ~10x cheaper acquisition step. An interoperability demo
showed all three modes — pure BoTorch, this API, and the two combined —
running in a single container job, including BoTorch selecting candidates that
sum to exactly 10.0000 on a mixture simplex.

---

## Cheminformatics: what this agent does and does not do

**RDKit is not installed here, deliberately.** Computing chemical descriptors is
the `mol-toolkit` agent's job (RDKit + Open Babel); duplicating it would bloat
this image and split one capability across two agents.

| Need | Agent |
|---|---|
| SMILES → descriptors, fingerprints, conformers, format conversion | `mol-toolkit` |
| Property prediction from structure | `chemprop`, `chemberta` |
| **Which candidates to make/measure next** | **this agent** |

What this agent provides is the other half: `select_from_library()` runs
Bayesian optimization over a **fixed candidate set** described by feature
vectors. Those features can be RDKit descriptors, fingerprints, learned
embeddings, measured properties — anything numeric, from any source.

```python
from bodoe_utils import Objective, select_diverse_subset, select_from_library

F = df[['MolWt', 'LogP', 'TPSA', 'NumRotatableBonds']].to_numpy(float)

start = select_diverse_subset(F, 12, seed=0, labels=df['smiles'])   # cold start
out   = select_from_library(F, observed_idx, Y,
                            [Objective('pIC50', 'maximize'),
                             Objective('logS', 'maximize')],
                            q=8, labels=df['smiles'])
print(out['selected_labels'], out['predicted_mean'])
```

Features are standardized internally — necessary because descriptor columns span
very different magnitudes (MolWt ~$10^2$, LogP ~$10^0$, TPSA ~$10^1$), and
without it the largest-range column would dominate the GP kernel. A contract
test verifies that a response driven *only* by the smallest-magnitude descriptor
is still found.

An 800-compound demo campaign was run end to end.
It reports the metric each mode actually targets — hypervolume for the
multi-objective run, best-value for the single-objective run:

| Mode | Metric | BO | Random | Library best |
|---|---|---|---|---|
| Multi-objective (potency vs solubility) | hypervolume | **73.34** | 71.47 | — |
| Single objective (potency) | best found | **8.999** | 8.901 | 8.999 |

The single-objective run finds the library optimum in 44 of 800 evaluations.
Note the multi-objective run would look like a *loss* if judged by best-potency
alone (8.773 vs 8.901) — because a multi-objective optimizer deliberately spends
part of its budget on the solubility end of the front. Judge each mode by what
its acquisition targets.

---

## Capabilities

### Design of experiments (no data yet)

| Family | Designs |
|---|---|
| Screening | Full factorial, fractional factorial ($2^{k-p}$), Plackett-Burman |
| Response surface | Central composite (rotatable / orthogonal / face-centred; inscribed, so every run stays within the bounds), Box-Behnken |
| Space filling | Latin hypercube (maximin- or correlation-optimized), scrambled Sobol' |
| Mixture | Scheffe simplex lattice, simplex centroid, extreme vertices, constrained maximin space filling || Candidate library | Maximin diverse subset over feature vectors (`select_diverse_subset`) |
Every design is returned in the user's own units together with quality
diagnostics (maximin distance, maximum absolute factor correlation,
first-order D-efficiency, feasible fraction). Fractional-factorial generators
come from an explicit **minimum-aberration search** over the defining relation,
not a heuristic.

### Bayesian optimization (data in hand)

* Gaussian-process surrogates with an ARD Matern 5/2 kernel.
* Acquisitions: EI, log-EI, PI, UCB, Thompson sampling, pure-uncertainty
  (active learning), probability-of-meeting-spec.
* Multi-objective: ParEGO (augmented-Chebyshev random scalarization) and
  expected hypervolume improvement, with Pareto fronts and hypervolume tracking.
* Batch suggestion with local penalization so a batch spreads out instead of
  collapsing onto one mode.
* Hard specification limits as probabilistic constraints.
* **Automatic output-transform selection** and **failed experiments as data** --
  see below.

### Mixture / formulation support

Components constrained to sum to a constant (fractions, parts-of-ten,
percentages) with per-component bounds are first-class. Candidate generation,
acquisition optimization (SLSQP under the equality constraint), and repair
projection all respect the simplex, so **every suggestion is a valid recipe**.

---

## Two behaviours worth knowing about

### Output transforms are detected, not requested

`Objective(..., transform="auto")` is the default. At `tell()` time the
optimizer inspects each response and applies `log1p` to non-negative data
spanning more than a decade.

This is not a convenience. Modelling viscosity (92-42 444 cP in the validation
dataset) on a raw scale makes the GP put probability mass on negative
viscosities, which corrupts the acquisition. It was the single highest-impact
setting found during validation -- enabling it moved a warm-start result from
*worse* than random to 50% better. Making it opt-in would have meant documenting
a footgun rather than removing it. Inspect the choice with `opt.transforms()`.

### Failed experiments are recorded, not dropped

A run that produced no usable measurement is passed as `NaN`:

```python
Y[bad_row] = np.nan
opt.tell(X, Y)
```

A formulation that would not cure is not missing data -- it is a strong signal
about a region of the design space. Such rows are excluded from the GP
regression (there is no response to learn from) but retained to fit a success
classifier. The predicted $P(\text{success})$ both multiplies the acquisition
and removes hopeless candidates from the pool via a self-calibrating cutoff.
`opt.n_failed` reports the count.

---

## GP backends

| Backend | When used | Notes |
|---|---|---|
| `botorch` | Default when `torch` is installed | BoTorch `SingleTaskGP` + GPyTorch |
| `sklearn` | Fallback | `GaussianProcessRegressor`, Matern 5/2 + white noise, no torch dependency |

`available_backends()` reports what is present; `backend='auto'` picks the most
capable one. **Both backends are exercised by the test suites** -- the contract
tests run inside the container, where `botorch` is the default, as well as on
the host, where only `sklearn` is available.

---

## Usage

Example prompts:

* "Design a 12-run screening experiment for temperature, pH, catalyst loading
  and residence time."
* "Here are 45 measured formulations; suggest the next 8 to minimize viscosity
  while keeping elongation above 150%."
* "Pick 12 diverse starting compounds from this descriptor table."

### Quick start

```python
from bodoe_utils import *

quick_setup(input_dir='/input', output_dir='/output', work_dir='/workdir')

# 1. Define the space -- mixture components summing to 10 parts
space = make_mixture_space(['PUDA', 'IBOA', 'EHMA', 'MAA'], total=10.0,
                           lower=[2.0, 0.0, 0.0, 0.0],
                           upper=[8.5, 6.0, 6.0, 6.0])

# 2. Declare the objectives (transforms are auto-detected from the data)
objs = [Objective('viscosity',     'minimize'),
        Objective('reactiontime2', 'minimize'),
        Objective('elongation',    'maximize'),
        Objective('modulus',       'maximize')]

# 3. Feed in what you have measured, ask for the next batch
out = suggest_next(X_measured, Y_measured, space, objs, q=8, seed=0)
for row in out['suggestions']:
    print(row)

save_final_results(out, {})
quick_finish()
```

---

## Validation

Two test suites ship beside the tool in [tools/bodoe](tools/bodoe) and run on
the host (scikit-learn backend) or in the container (BoTorch backend):

```bash
cd agents/bo-doe/tools/bodoe

# Host (scikit-learn backend)
python -u test_bodoe.py
python -u test_bodoe_contracts.py

# Container (BoTorch backend)
docker build -t bodoe:latest .
docker run --rm -v "${PWD}:/t:ro" bodoe:latest python -u /t/test_bodoe.py
docker run --rm -v "${PWD}:/t:ro" bodoe:latest python -u /t/test_bodoe_contracts.py
```

The DoE property checks, benchmarks and demos summarized below were run with
separate development scripts that are not part of this catalog entry. The
formulation benchmark uses a published third-party dataset that is not
redistributed here; see [Data attribution](#data-attribution). Their results are
reported here for transparency.

### 1. External benchmark: BoTorch's own tutorial

The validation run replicates
[BoTorch's multi-objective tutorial](https://botorch.org/docs/tutorials/multi_objective_bo)
exactly: `BraninCurrin(negate=True)`, per-objective noise SE `[15.19, 0.63]`,
6 Sobol initial points, 20 batches of 4 (86 evaluations), scored by dominated
hypervolume against `problem.ref_point`.

This is the honest check — a reference implementation, a problem we did not
design, a noise level we did not pick, and a metric we did not choose. The
script asserts that our transcription of the test function matches BoTorch's
(max abs error $3.6\times10^{-15}$), that the reference point and `max_hv`
agree, and that our hypervolume matches BoTorch's `DominatedPartitioning`
**exactly** (0.0e+00) — then runs BoTorch's own qNEHVI loop side by side.

**Result — 86 evaluations, 3 trials, max attainable HV = 59.36:**

| Method | median HV | % of max | Time / trial |
|---|---|---|---|
| **botorch-qNEHVI** (live reference) | **57.20** | 96.4% | 361 s |
| bodoe-ehvi (this agent) | 51.38 | 86.6% | 31 s |
| bodoe-parego (this agent) | 50.42 | 84.9% | 47 s |
| Sobol baseline | 21.65 | 36.5% | <1 s |

**5 of 6 acceptance checks pass. The failure is reported, not re-tuned:**
`within_10pct_of_live_botorch` — this agent reaches **89.8%** of BoTorch's
hypervolume against a pre-registered 90% bar. Moving the bar to 85% after
seeing 89.8% would be exactly the goalpost-shifting this revision exists to
eliminate, so it stays red.

The honest summary: **BoTorch wins on solution quality.** It optimizes its
acquisition with exact gradients and multi-start L-BFGS-B; this agent ranks a
candidate pool and polishes with SLSQP. What this agent offers instead is ~90%
of that hypervolume at roughly **10× less compute**, plus native mixture
constraints, classical DoE, and failure handling, which BoTorch does not
provide out of the box. If you have an unconstrained box problem and compute to
spare, use BoTorch directly.

One caveat on the baseline: our Sobol row (21.65) is far stronger than the
tutorial's published random baseline (8.75), because we draw one low-discrepancy
sequence across the whole budget rather than fresh random points per batch.
Comparisons above are therefore made against our own stronger baseline.

### 2. DoE mathematics verified from first principles

DoE property checks — **14/14 pass**. Plackett-Burman
designs are confirmed balanced and column-orthogonal ($D^\top D = nI$);
fractional-factorial resolutions are computed from the actual defining relation
by searching for the shortest defining word.

This caught a **false claim** in the original code. The docstring asserted that
aliasing each added factor with the highest-order interaction "maximises
resolution". For $2^{6-2}$ that heuristic gives `E=ABCD, F=ABC`, whose defining
relation contains the three-letter word `DEF` — resolution III, when the
classical `E=ABC, F=BCD` achieves resolution IV. It is now a genuine
minimum-aberration search, and `fractional_factorial_resolution()` is exposed so
users can check any design themselves.

### 3. Component-contract tests

[test_bodoe_contracts.py](tools/bodoe/test_bodoe_contracts.py) — **42/42 pass, on both backends**. These test
*internal contracts* rather than end-to-end outcomes, which is the main
engineering lesson of this project: the original suite tested only invariants
(mixtures sum correctly, batches spread out) and outcomes (beats random on
Branin), and that net let real defects through.

Contracts covered: acquisition composition cannot invert a ranking; log-scale
utilities preserve magnitude; the acquisition surface is deterministic given a
frozen ask-context; a candidate scores identically alone and in a batch; local
refinement never worsens its own objective and respects mixture, bound and
diversity constraints; transform auto-detection latches and round-trips; failed
experiments are recorded, steer suggestions, and the filter is self-calibrating;
seeded runs are reproducible. Regression tests for the review findings below
cover leave-one-out $R^2$ (checked against brute-force refitting), acquisition
names, Pareto directions in plots, strict-JSON results, orthogonal CCDs, EHVI
beyond the ideal point and integer factors. Both suites also run under
`python -m pytest`.

### 4. Formulation benchmark on the resin data

This benchmark uses 45 measured DLP-printable elastomer (UV-curable resin)
formulations published by Song *et al.* (2026), using the authors' original
`train_data`, `val_data` and `ext_val_data` splits. The dataset is not
redistributed with this agent; download it from Zenodo,
[doi:10.5281/zenodo.19389221](https://doi.org/10.5281/zenodo.19389221)
(full citation under [Data attribution](#data-attribution)).

Four RBF-SVR models on `log1p` targets act as the oracle; fitted on the
33-point training set they achieve held-out $R^2$ of 0.71–0.89 and Spearman
$\rho$ of 0.83–0.97.

> **Caveat, stated up front.** The oracle is a smooth RBF model and the
> optimizer is a smooth RBF (Matérn) GP, over the same 4-D simplex. This
> landscape is inherently friendly to the method under test. Read the result as
> an upper bound on a favourable problem; the BoTorch tutorial above is the
> independent check.

Methodology fixes over the first revision:

* **Measurement noise.** 5% relative log-space noise on every oracle call, with
  scoring done on the noiseless values so a lucky measurement cannot be
  mistaken for a good formulation. A noise-free benchmark flatters BO.
* **A fair DE baseline.** The notebook's actual workflow is *fit a surrogate,
  then run DE on the surrogate* with thousands of free virtual evaluations.
  That is now implemented as `de_surrogate`. The earlier revision ran DE as a
  sequential experimental policy and mislabelled it as the notebook's method —
  a strawman. It is still reported, as `de_direct`, but labelled as weak.
* **Pre-registered thresholds** in the `ACCEPTANCE` dict, fixed before any run.
* **Paired statistics.** Wilcoxon signed-rank tests across shared seeds (every
  method sees the same seeds *and* the same noise draws) with bootstrap CIs on
  the paired differences, instead of eyeballing medians.
* **One fixed scoring scale.** Output transforms for scoring are resolved once
  against the reference sample and shared by all methods, with an assertion that
  they cannot change between calls.

**Result — 40 evaluations, 12 seeds, 5% noise:**

| Method | cost (median) | cost IQR | hypervolume | evals→target | solve rate |
|---|---|---|---|---|---|
| bo_ehvi | 0.1635 | [0.1596, 0.1694] | **10 070** | 26 | 75% |
| bo_parego | 0.1666 | [0.1616, 0.1695] | 9 857 | 25 | 75% |
| de_surrogate | **0.1596** | [0.1565, 0.1683] | 8 828 | **16** | 75% |
| de_direct | 0.1637 | [0.1582, 0.1692] | 7 022 | 14 | 92% |
| random | 0.1699 | [0.1683, 0.1723] | 7 615 | 35 | 50% |

**3 of 5 pre-registered checks pass. Both failures are real and are reported:**

| Check | Verdict |
|---|---|
| `bo_beats_random_hv` | **PASS** — +2 360 HV, p = 0.0002, wins 12/12 |
| `bo_beats_de_surrogate_hv` | **PASS** — +760 HV, p = 0.0005, wins 11/12 |
| `warm_start_beats_random` | **PASS** — beats 92% of random 8-run draws |
| `bo_beats_random_cost` | **FAIL** — p = 0.15, wins 8/12 |
| `bo_budget_advantage` | **FAIL** — 25 evaluations, bar was ≤ 24 |

The honest reading: **on hypervolume, BO wins decisively and unanimously** —
every seed, against every baseline, at p ≤ 0.0005. On the *scalarized cost* it
does not: `de_surrogate` achieves a slightly better median (0.1596 vs 0.1666)
and reaches the target in fewer runs.

That split is exactly what the two metrics measure. Scalarized cost rewards one
excellent compromise point, and spending the entire budget on a space-filling
design then globally optimizing a surrogate is a strong way to find one.
Hypervolume rewards covering the whole trade-off surface, which is what a
multi-objective acquisition targets and what a formulator actually needs when
the weights are not known in advance. **If you already know your exact
weighting, surrogate-DE is a reasonable and cheaper choice.** If you want the
Pareto front, use this agent.

Note also that BO's advantage here is smaller than the first revision reported
(which claimed a 2.4× budget speed-up). That earlier figure came from a
noise-free oracle, a strawman DE baseline, and — as it turned out — an
inconsistent scoring scale. This table is what survives correcting all three.

---

## Defects found and fixed during validation

| # | Defect | How it was caught |
|---|---|---|
| 1 | Feasibility/diversity penalties multiplied into log-EI. Because log-EI is negative, scaling by a factor in $(0,1)$ *increases* it, inverting the ranking and collapsing every batch onto one point. | Batch-diversity outcome test (by luck) |
| 2 | Viscosity modelled on a raw scale → negative predicted viscosities and reaction times. | Warm-start result was worse than random |
| 3 | SLSQP refinement optimized a ParEGO surface that redrew its scalarization weights on every function evaluation — it was maximizing noise. | Contract test: determinism under a frozen ask-context |
| 4 | EHVI's Monte-Carlo integration region depended on the candidate batch, so a point scored differently depending on what it was evaluated alongside. | Contract test: single-row vs batch agreement |
| 5 | $2^{6-2}$ fractional factorial was resolution III, not the claimed IV. | First-principles defining-relation search |
| 6 | Two-objective EHVI called full hypervolume once per posterior sample per candidate — unusably slow. Replaced with the exact closed-form increment, vectorized (verified equal to brute force to $7\times10^{-15}$, ~$10^3\times$ faster). | Tutorial benchmark did not finish |
| 7 | EHVI built its Pareto front from noisy observations, so lucky measurements were enshrined in the reference front. Now uses GP posterior means at observed designs, as qEHVI does. | BoTorch tutorial: EHVI scored well below ParEGO |
| 8 | Container entrypoint sourced `conda.sh`, absent from the runtime stage; matplotlib and fontconfig failed against a read-only home. | First actual container run |
| 9 | `Objective.to_min()` silently used the **raw scale** whenever an `"auto"` transform had not been resolved. Benchmark scoring built fresh objectives and never fitted a model, so every hypervolume was computed untransformed. `forward()` now resolves lazily on first use. | Warm-start check failed implausibly |
| 10 | Fixing #9 exposed a latent harness flaw: each scoring call resolved transforms from *that method's own data*, so a method sampling a wide range was scored on a log scale while another was scored linearly. Scoring transforms are now resolved once against the reference sample and shared, with an assertion that they cannot change. | Benchmark inverted — BO appeared to lose by two orders of magnitude |
| 11 | `loo_r2()` / `model_quality()` reported **in-sample** $R^2$, which an interpolating GP pushes to ~1 even on pure noise, so the "warn if $R^2 < 0.5$" rule could never fire. Now the exact closed-form leave-one-out $R^2$. | PR review |
| 12 | `plot_pareto()` assumed every objective was minimized and drew the wrong front for maximize objectives. It now takes the `Objective` list (or `directions=`). | PR review |
| 13 | `acquisition()` silently returned the posterior SD for multi-objective or unrecognized names, so `acquisition_fn="EHVI"` or `"qparego"` became pure exploration. Names are now canonicalized and validated. | PR review |
| 14 | `final_results.json` could contain bare `NaN`; mixture `design_diagnostics` returned a `NaN` D-efficiency; prompt examples used `pd` without it being exported. | PR review |
| 15 | `alpha="orthogonal"` CCD used $\alpha^2$ instead of $\alpha$; the `face` options were mislabelled and `"inscribed"` was clipped. | PR review |
| 16 | 3+-objective EHVI ignored improvement beyond the front's ideal point; integer factors were scored and returned at fractional values. | PR review |

Defects 1 and 2 were found only because an outcome test happened to notice.
Defects 3 and 4 were invisible to every invariant and outcome test and needed
contract tests to surface — which is why those now exist. Defect 7 was invisible
to every internal test and needed an *external* benchmark. Defects 9 and 10 were
in the **measurement apparatus itself**, and were caught only because a result
came out implausible and was investigated rather than published.

That last category is the one worth dwelling on: a benchmark is code, it can be
wrong, and a surprising number that flatters you is far less likely to be
investigated than one that does not. Both were found by chasing results that
looked *too bad* to be true.

---

## Library reference

| Module | Contents |
|---|---|
| `space.py` | `Parameter`, `ParameterSpace`, `make_space`, `make_mixture_space` |
| `doe.py` | Design generators, `generate_design`, `design_diagnostics`, `fractional_factorial_resolution` |
| `models.py` | `GPSurrogate`, `fit_gp`, backend resolution |
| `acquisition.py` | Acquisitions, `ACQUISITIONS` registry, `to_utility`, Pareto and hypervolume utilities |
| `optimize.py` | `Objective`, `BayesianOptimizer`, `suggest_next`, campaign runners, baselines |
| `plots.py` | Convergence, Pareto, design matrix, parity, ternary, benchmark plots |
| `io_utils.py` | `quick_setup`, `quick_finish`, `save_final_results`, table I/O |
| `bodoe_utils.py` | Single import surface re-exporting everything above |

### Composing acquisitions safely

`to_utility(values, scale)` converts any acquisition into a non-negative utility
*before* probability factors are applied. Each acquisition declares its scale in
the `ACQUISITIONS` registry:

* `"nonneg"` — clipped at zero; magnitude preserved exactly.
* `"log"` — `exp(v - max(v))`, so *ratios* survive. Rank-normalizing log-EI
  instead would flatten a $10^{300}$ difference in expected improvement into a
  few rank steps, letting a mild penalty overturn it.
* `"unbounded"` — rank-normalized, the only safe option without a natural zero.

Adding a new acquisition means adding a registry entry, so there is no way to
compose one unsafely by forgetting to handle it in the right place.

---

## Compute

CPU only. Bayesian optimization on experimental-scale data (tens to a few
thousand points) is bound by the GP fit, not by linear-algebra throughput.
Recommended SKUs: `Standard_D4s_v6`, `Standard_D8s_v6`.

---

## Pitfalls the agent actively checks for

* **Mixture data modelled as a box space** — check `X.sum(axis=1)` first.
* **The auto transform overridden on a wide-range positive response** — the GP
  will predict negative viscosities and the acquisition will chase noise.
* **Fewer observations than factors** — the optimizer falls back to space
  filling; those points are not "optimized".
* **All data clustered in one corner** — the GP extrapolates badly; augment with
  a space-filling design first.
* **Failed runs recorded as 0 or deleted** rather than `NaN` — a zero viscosity
  is not a measurement, and deleting the row discards the strongest signal.
* **Near-perfectly correlated objectives** — the trade-off is illusory.

## Known Limitations

Stated explicitly rather than left for a user to discover:

* No per-input replicate/noise modelling, no batch or block effects, no
  cost-asymmetric components, no discrete mixture components.
* `ParameterSpace.sample` falls back to repair-projection when component bounds
  are too tight for rejection sampling, which concentrates points on bound
  faces. The contract tests assert the primary path stays uniform (<5% of points
  on a face) and that the candidate pool covers the feasible region, but the
  distortion of the tight-bound fallback is not corrected — only bounded.
* The success classifier needs several failures before it is informative; with
  one or two it stays out of the way by design.
* `model_quality()` holds the GP hyperparameters fixed at their full-data fit
  when computing leave-one-out $R^2$, so it is somewhat optimistic on very small
  datasets. Treat it as a screen, not a validation.
* The formulation benchmark's oracle shares its inductive bias (smooth RBF) with
  the optimizer. The BoTorch tutorial replication is the independent check.
* On a **known, fixed weighting** of objectives, a surrogate-plus-DE workflow
  matches or beats this agent on scalarized cost at lower compute. This agent's
  advantage is on hypervolume, i.e. when the weighting is not known in advance.
* Solution quality is below BoTorch's qNEHVI (89.8% of its hypervolume on the
  tutorial problem). The trade is roughly 10x less compute plus mixture,
  DoE and failure-handling support.

## Data attribution

The formulation benchmark in [Validation](#validation) uses data and model
hyperparameters from the following work. We thank the authors for making them
publicly available.

* **Paper:** Song, Y., Park, B., Jeon, S. *et al.* Machine learning guided
  formulation design of digital light processing printable elastomers beyond
  viscosity stretchability tradeoff. *Nat. Commun.* **17**, 7167 (2026).
  [https://doi.org/10.1038/s41467-026-73735-4](https://doi.org/10.1038/s41467-026-73735-4)
* **Dataset and code:** Song, Y., Park, B., Jeon, S., Kweon, H., Lee, S. & Na, J.
  *bspark1102/Resin_ML: final_manuscript* (Version final_manuscript). Zenodo
  (2026). [https://doi.org/10.5281/zenodo.19389221](https://doi.org/10.5281/zenodo.19389221)
  — released under the MIT License.

The data is not included in this repository. Benchmark results reported here
are our own and are not endorsed by the original authors. If you use this
dataset, please cite the paper and the Zenodo record above.

## Contributing

See [CONTRIBUTING.md](../../CONTRIBUTING.md).

## License

MIT
