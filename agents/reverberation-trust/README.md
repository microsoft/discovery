# Reverberation-Lag Trust Agent

An AI reviewer that reads an AGN reverberation-mapping (RM) time lag and tells you whether to
trust it — the judgment that today lives only in a handful of experts' heads, applied
consistently at survey scale.

Given a continuum-to-line lag and its light curves, the agent returns a **calibrated trust
verdict**: the lag, a confidence tier, and reviewable reasoning. It does **not** compute lags
better than JAVELIN or PyCCF — it answers the question those codes omit: *should you believe
this number?* Its purpose is triage — auto-certify the trustworthy lags and route the rest to
humans with explained reasons.

## Overview

The agent's one job is **trust triage**: read a reverberation-mapping lag and its light curves and
return a calibrated verdict — the lag, a confidence tier (`refuse` / `low` / `medium` / `high`), and
reviewable reasoning — so a survey-scale flood of automated lags can be sorted: auto-certify the
trustworthy, route the rest to humans. It does **not** compute lags better than JAVELIN or PyCCF; it
answers the question those codes omit.

### One-page brief

| Field | Value |
|---|---|
| **Scientific user** | AGN reverberation-mapping & disk-RM teams (SDSS-RM, OzDES, Swift / AGN STORM), and Rubin/LSST-era AGN RM at scale. |
| **Bottleneck** | Trustworthy lags are vetted by hand, object-by-object, with inconsistent rigor — which does not scale to the Rubin flood of thousands of candidates. |
| **Hypothesis** | A calibrated trust verdict, assembled from independent witnesses, can auto-certify the trustworthy lags and route the rest to humans with explained reasons. |
| **Evidence / tool** | Five estimators (ICCF, DCF, von Neumann, DRW, JAVELIN-style) + a witness/trust layer (sampling-window fact-arbiter, red-noise & aliasing gates, cross-band/line/instrument Look witnesses, the X-ray-timing Channel cascade). |
| **Baseline** | Raw CCF peak / single-method / current manual per-paper vetting. |
| **Result** | Grier 2012: 5/5 Hβ lags at mean \|Δ\| = 1.3 d. SDSS-RM (44 AGN): median \|Δ\| = 5.3 d with confidence flags that **separate accuracy**; RMID 781 false-confidence caught and corrected by an independent witness; RMID 707 floor reported honestly. Channel axis: X-ray→UV→optical cascade on 5 AGN, X-ray coupling graded per object (recovers published disconnects). Two orthogonal witnesses (M–σ, X-ray flux) fail for the predicted reason — the model is validated by its negatives. |
| **Expected value** | Expert-grade, uncertainty-honest trust triage applied consistently at scale and usable below the resident-expert tier. |
| **Evaluation** | Known-answer regression suite (documented same-data reversals), leakage-ablated; executed SDSS-RM scale run (accuracy-separating flags, trust recovery); expert-confirmed novel catch as stretch. |

### The three-axis witness model

Trust is assembled from independent witnesses grouped by *how they fail*:

- **Look** (a mirror — same signal, different path): different band, instrument, epoch, or line
  viewing the same reverberation. **Proven** on SDSS-RM.
- **Channel** (a messenger — a different signal from the same source): X-ray timing, disk
  continuum reverberation. **Proven** via the X-ray→UV→optical cascade on 5 AGN.
- **Interaction** (a causal probe — perturb and watch): transits, TDEs, microlensing. Roadmap.

**Governing law:** a witness must be *independent in failure mode* **and** *coupled to the
observable* you are checking. Confirmed by negatives — M–σ (couples to mass) and X-ray flux
(couples to luminosity) both fail to flag lag errors, exactly as predicted.

## Usage

**Input** — a light-curve bundle (JSON): `object_id`, `redshift`, `continuum`/`line` time series
(`t`/`f`/`e`), an optional second continuum band (enables the Look witness), and an optional
`cascade` block (bands + X-ray driver) that enables the Channel witness. See
[tools/reverberation-trust/example-input-files/](tools/reverberation-trust/example-input-files/).

**Output** — a JSON verdict: the adopted lag, the tier, per-estimator lags, the arbitration outcome,
the verification gates (red-noise, aliasing), the witnesses that ran (and their splits), and a
plain-language rationale.

**Invocation.** The agent is **per-object** and works two ways in Discovery:
- **Conversational** — `@reverberation-trust` in chat for a single lag; immediate.
- **Discovery Engine** — a batch objective ("trust-check these N lags") is decomposed by cognition
  into **N per-object trust-tasks fanned out in parallel**. The platform owns scale; the agent does
  not loop a batch.

**Triage at scale = the tier is the validation gate.** A Discovery task carries *validation
requirements* cognition uses to decide pass / retry / escalate. Map the trust tier onto them:
auto-certify `high`, route `< medium` to a human. That is the flood-triage story in the platform's
own vocabulary.

## Prerequisites

- **Discovery app** (Windows x64) or Microsoft Discovery (cloud) with an active **GitHub Copilot**
  subscription — Discovery drives Copilot for its agent capabilities.
- **Bundled tool runtime:** Python 3.12 with `numpy` + `scipy` only (see the tool `Dockerfile`).
  No network, GPU, or heavy dependencies at run time.
- **Development / CI:** `pytest` to run the tool's test suite (the tests are also standalone-runnable).

## Architecture

Per object the agent runs a reasoning loop: ingest & characterize → apply the physical-lag window →
estimate with independent classes (ICCF, DCF, von Neumann, DRW forward-model, a JAVELIN-style likelihood) → read the
tells → **arbitrate disagreement with a sampling fact, not more estimators** → verify (red-noise,
aliasing) → corroborate with available Look/Channel witnesses → report the lag, tier, and reasoning.
Confidence tiers track *which checks could run*, not a minimum-field gate: missing data lowers the
ceiling, it does not break the estimate.

| Path | Purpose |
|---|---|
| `metadata.yaml` | Catalog manifest (name, version, tags, publisher). |
| `agent.yaml` | Prompt-agent definition — model, the reasoning-loop instructions, tool wiring, and the required-script template. |
| `tools/reverberation-trust/tool.yaml` | Discovery-managed tool definition (container + Python env). |
| `tools/reverberation-trust/Dockerfile` | Tool container (`python:3.12-slim` + numpy/scipy). |
| `tools/reverberation-trust/reverbtrust_utils.py` | Estimator + trust library: estimators, the sampling-fact arbiter, red-noise gate, cross-witness, the Channel cascade, and the `TrustState` confidence tracker. |
| `tools/reverberation-trust/test_reverbtrust_utils.py`, `test_reverbtrust_more.py` | Pytest-collectable, dual-runnable suite (22 tests). |

## Tools

| Tool | What it does |
|---|---|
| `reverberation-trust` | The estimator + trust compute tool. Over a light-curve bundle it runs the independent lag estimators (ICCF, DCF, von Neumann, DRW forward-model, a JAVELIN-style likelihood), arbitrates their disagreement with sampling facts, applies the red-noise and aliasing gates, and corroborates with the cross-band/line and Channel-timing witnesses — returning the calibrated verdict (lag, confidence tier, estimator agreement, verification results, and witness splits). Containerized Python (numpy + scipy), reading `/input` and writing `/output`. |

## Configuration

- **Model:** `{{CHAT-MODEL}}` at `temperature: 0`, `topP: 0` (deterministic verdicts).
- **Tool wiring:** `agent.yaml`'s `discoveryExtensions.tools` references the bundled tool by id.
- **Trust thresholds** (in `reverbtrust_utils.py`): `ESTIMATION_FLOOR_CONT` = 20 /
  `ESTIMATION_FLOOR_LINE` = 10 (below → `refuse`); `COUPLING_THRESHOLD` = 0.5 (Channel r_max cutoff);
  `TrustState.SPLIT_FLAG_DAYS` = 10 (cross-witness split that subtracts confidence).

## Known Limitations

- The verdict is a **triage aid, not a certification** — it can only subtract confidence, never add
  it. A `high` tier means "no available witness contradicted this," not "guaranteed correct."
- The agent reports its **floor honestly**: where an object is genuinely undetectable (high-z, no
  orthogonal line, both bands share the failure), it says so rather than manufacturing a flag.
- **Insufficient data ≠ disconnect:** the Channel coupling check returns "cannot judge" when overlap
  is too thin, rather than a false disconnect.
- The physical-lag window admits small negative lags (−5 d slack) to tolerate measurement scatter —
  an intentional, documented choice, not a strict ≥ 0 gate.
- Novel-defect candidates are **candidates, not confirmed catches** — a domain expert is the arbiter
  of novel vs. already-known.
- The DRW and JAVELIN-style estimators are independent **facsimiles** of the published methods
  (numpy + scipy) — correct on the reference data, but not performance-optimized. A maintained,
  compiled JAVELIN (e.g., a Rust-accelerated port) is the intended production replacement at survey scale.

## Contributing

The trust framework grows by **adding witnesses**, not estimators. A new witness must be *independent
in failure mode* and *coupled to the lag* (the governing law); wire it in as a
`TrustState.add_witness(...)` that can only subtract confidence. The per-class physics of new
Interaction-axis probes (transits, TDEs, microlensing) needs domain partners.

**Data sources** (all public, via `astroquery`/VizieR): SDSS-RM — Grier 2017 Hβ (`J/ApJ/851/21`),
Grier 2019 C IV (`J/ApJ/887/38`), Homayouni 2019 continuum (`J/ApJ/880/126`), Homayouni 2020 Mg II
(`J/ApJ/901/55`); Grier 2012 LAMP (`J/ApJ/755/60`); Channel-axis multi-wavelength — Mrk 817 / AGN
STORM 2 (`J/ApJ/958/195`), Edelson 2019 Swift AGN (`J/ApJ/870/123`); 4XMM-DR13 X-ray flux
(`IX/69`, used to validate the couple-to-the-observable law).

## References — the shoulders we stand on

This tool **implements and cross-checks established reverberation-mapping methods; it does not invent
new estimators.** The prior work it stands on:

**The RM method**
- Blandford & McKee (1982) — the reverberation-mapping concept.
- Peterson (1993); Peterson et al. (2004) — RM methodology and the AGN RM database.

**Estimators**
- Interpolated cross-correlation (ICCF) + centroid: Gaskell & Sparke (1986); Gaskell & Peterson (1987);
  White & Peterson (1994).
- FR/RSS uncertainty estimation: Peterson et al. (1998, 2004).
- Discrete correlation function (DCF): Edelson & Krolik (1988).
- von Neumann / regularity (interpolation-free) estimator: Chelouche, Pozo-Nuñez & Zucker (2017).
- Damped-random-walk (DRW) variability model: Kelly, Bechtold & Siemiginowska (2009); MacLeod et al. (2010).
- JAVELIN joint-DRW-likelihood method: Zu, Kochanek & Peterson (2011); Zu et al. (2013).
- Reference CCF implementation emulated here: PyCCF — Sun, Grier & Peterson (2018).

**Red-noise significance**
- Red-noise light-curve simulation for false-alarm probabilities: Timmer & König (1995);
  Emmanoulopoulos, McHardy & Papadakis (2013).

**Data** — see *Contributing* above for the public SDSS-RM, LAMP, AGN STORM 2, Swift, and 4XMM catalogs
(via `astroquery`/VizieR).

> The estimators here are independent re-implementations of these published methods (numpy + scipy), used
> as cross-checking witnesses — not the original authors' software. Credit for the methods belongs to the
> works above.
