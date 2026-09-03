"""
reverbtrust_utils -- Reverberation-Lag Trust Agent utility library.

A dependency-light (numpy + scipy) consolidation of the validated prototype: independent
lag estimators, the sampling-fact arbiter, verification gates, independent witnesses, and a
TrustState confidence tracker -- plus a small /input -> /output I/O convention so a generated
script can run end-to-end in the tool container.

Design laws (enforced by the API, proven in the prototype):
  * Subtract, never add -- a witness can only LOWER confidence, never certify a lag.
  * Arbitrate with facts, not estimators -- break a tie with the sampling schedule, not more CCFs.
  * Couple to the observable -- a witness helps only if coupled to the LAG itself.
  * Degrade, do not refuse -- confidence tracks which checks COULD run, not a minimum-field gate.

Import pattern:
    from reverbtrust_utils import *                     # everything
    from reverbtrust_utils import iccf, drw_lag, TrustState, quick_setup, quick_finish
"""
from __future__ import annotations

import json
import logging
import os

import numpy as np
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import minimize, minimize_scalar

__all__ = [
    # estimators
    "iccf", "centroid", "frrss",
    "gp_fit", "gp_predict", "drw_lag",
    "javelin_profile", "javelin_lag",
    # trust layer
    "physical_window", "sampling_acf", "pair_count", "arbitrate",
    "simulate_drw", "rednoise_pvalue", "cross_split",
    # channel axis
    "cascade", "coupling_strength", "cascade_ordered", "COUPLING_THRESHOLD",
    "TrustState", "ESTIMATION_FLOOR_CONT", "ESTIMATION_FLOOR_LINE",
    # i/o
    "quick_setup", "save_final_results", "quick_finish", "load_lightcurves",
]

# Below these epoch counts the lag is not estimable -> refuse.
ESTIMATION_FLOOR_CONT = 20
ESTIMATION_FLOOR_LINE = 10

# r_max below this => the channel link is disconnected; its lag is meaningless (do not report it).
COUPLING_THRESHOLD = 0.5


# --------------------------------------------------------------------------------------
# Estimator class 1: interpolated cross-correlation (ICCF; the PyCCF core)
# --------------------------------------------------------------------------------------
def iccf(t1, f1, t2, f2, lags, min_overlap=20):
    """Two-way interpolated CCF: correlation r as a function of trial lag."""
    t1, f1, t2, f2 = map(np.asarray, (t1, f1, t2, f2))
    r = np.full(len(lags), np.nan)
    for k, lag in enumerate(lags):
        m1 = (t1 + lag >= t2.min()) & (t1 + lag <= t2.max())
        r1 = np.nan
        if m1.sum() >= min_overlap:
            f2i = np.interp(t1[m1] + lag, t2, f2)
            if np.std(f1[m1]) > 0 and np.std(f2i) > 0:
                r1 = np.corrcoef(f1[m1], f2i)[0, 1]
        m2 = (t2 - lag >= t1.min()) & (t2 - lag <= t1.max())
        r2 = np.nan
        if m2.sum() >= min_overlap:
            f1i = np.interp(t2[m2] - lag, t1, f1)
            if np.std(f1i) > 0 and np.std(f2[m2]) > 0:
                r2 = np.corrcoef(f1i, f2[m2])[0, 1]
        vals = [v for v in (r1, r2) if not np.isnan(v)]
        if vals:
            r[k] = np.mean(vals)
    return r


def centroid(lags, r, frac=0.8):
    """Peak lag, centroid (over r >= frac * r_max), and r_max of a CCF.

    Returns (nan, nan, rmax) when there is no usable positive peak -- an all-NaN CCF, or
    rmax <= 0 (no positive correlation) -- rather than crashing (nanargmax on all-NaN) or
    returning an inconsistent NaN-centroid paired with a finite peak.
    """
    lags = np.asarray(lags, float)
    r = np.asarray(r, float)
    if np.all(np.isnan(r)):
        return np.nan, np.nan, np.nan
    rmax = np.nanmax(r)
    if not np.isfinite(rmax) or rmax <= 0:
        return np.nan, np.nan, rmax
    peak = lags[np.nanargmax(r)]
    sel = (r >= frac * rmax) & ~np.isnan(r)
    cent = np.sum(lags[sel] * r[sel]) / np.sum(r[sel])
    return cent, peak, rmax


def frrss(t1, f1, e1, t2, f2, e2, lags, n=500, min_overlap=20, rng=None):
    """Flux-Randomization / Random-Subset-Selection Monte Carlo -> lag distribution.

    Returns (median, p16, p84, samples) of the CCF centroid -- the FR/RSS uncertainty.
    """
    rng = rng or np.random.default_rng(42)
    t1, f1, e1 = map(np.asarray, (t1, f1, e1))
    t2, f2, e2 = map(np.asarray, (t2, f2, e2))
    cents = []
    N1, N2 = len(t1), len(t2)
    for _ in range(n):
        i1 = np.unique(rng.choice(N1, N1, replace=True))
        i2 = np.unique(rng.choice(N2, N2, replace=True))
        ff1 = f1[i1] + rng.normal(0, 1, len(i1)) * e1[i1]
        ff2 = f2[i2] + rng.normal(0, 1, len(i2)) * e2[i2]
        r = iccf(t1[i1], ff1, t2[i2], ff2, lags, min_overlap=min_overlap)
        if np.all(np.isnan(r)):
            continue
        try:
            c, _, rmax = centroid(lags, r)
            if rmax > 0.35 and np.isfinite(c):
                cents.append(c)
        except Exception:
            pass
    cents = np.array(cents)
    if len(cents) < 10:
        return np.nan, np.nan, np.nan, cents
    return np.median(cents), np.percentile(cents, 16), np.percentile(cents, 84), cents


# --------------------------------------------------------------------------------------
# Estimator class 2: DRW forward-model (JAVELIN-lite; treats slow variability as signal)
# --------------------------------------------------------------------------------------
def _K(dt, sigma, tau):
    return sigma ** 2 * np.exp(-np.abs(dt) / tau)


def gp_fit(t, y, yerr):
    """Fit a damped-random-walk GP (sigma, tau) by marginal-likelihood maximization."""
    t, y, yerr = map(np.asarray, (t, y, yerr))
    ym = y - y.mean()
    DT = t[:, None] - t[None, :]
    n = len(t)

    def nll(p):
        sigma, tau = np.exp(p)
        K = _K(DT, sigma, tau) + np.diag(yerr ** 2) + 1e-8 * np.eye(n)
        try:
            c, low = cho_factor(K)
        except Exception:
            return 1e12
        alpha = cho_solve((c, low), ym)
        return 0.5 * ym @ alpha + np.sum(np.log(np.diag(c))) + 0.5 * n * np.log(2 * np.pi)

    s0 = np.log(np.std(ym) + 1e-6)
    best = None
    for tau0 in (20.0, 60.0, 150.0):
        r = minimize(nll, x0=[s0, np.log(tau0)], method="Nelder-Mead",
                     options=dict(maxiter=400, xatol=1e-3, fatol=1e-3))
        if best is None or r.fun < best.fun:
            best = r
    sigma, tau = np.exp(best.x)
    K = _K(DT, sigma, tau) + np.diag(yerr ** 2) + 1e-8 * np.eye(n)
    c, low = cho_factor(K)
    alpha = cho_solve((c, low), ym)
    return dict(sigma=sigma, tau=tau, t=t, ymean=y.mean(), alpha=alpha, chol=(c, low))


def gp_predict(gp, tstar):
    tstar = np.asarray(tstar)
    Ks = _K(tstar[:, None] - gp["t"][None, :], gp["sigma"], gp["tau"])
    return gp["ymean"] + Ks @ gp["alpha"]


def drw_lag(tc, fc, ec, tl, fl, el, lags):
    """Best-fit lag by DRW-predict-and-align chi^2 over the trial lags."""
    tc, fc, ec, tl, fl, el = map(np.asarray, (tc, fc, ec, tl, fl, el))
    gp = gp_fit(tc, fc, ec)
    w = 1.0 / el ** 2
    chi2 = np.full(len(lags), np.nan)
    for k, lag in enumerate(lags):
        p = gp_predict(gp, tl - lag)
        Sw = w.sum(); Sp = (w * p).sum(); Spp = (w * p * p).sum()
        Sy = (w * fl).sum(); Spy = (w * p * fl).sum()
        det = Spp * Sw - Sp * Sp
        if abs(det) < 1e-12:
            continue
        A = (Spy * Sw - Sp * Sy) / det
        b = (Spp * Sy - Sp * Spy) / det
        chi2[k] = (w * (fl - A * p - b) ** 2).sum()
    return lags[np.nanargmin(chi2)], chi2, gp


# --------------------------------------------------------------------------------------
# Estimator class 3: full JAVELIN (joint DRW likelihood; posterior exposes aliasing)
# --------------------------------------------------------------------------------------
def _jav_nll(lag, A, tc, dc, ec, tl, dl, el, sigma, tau):
    t = np.concatenate([tc, tl - lag])
    amp = np.concatenate([np.ones(len(tc)), A * np.ones(len(tl))])
    d = np.concatenate([dc, dl])
    K = np.outer(amp, amp) * sigma ** 2 * np.exp(-np.abs(t[:, None] - t[None, :]) / tau)
    K[np.diag_indices_from(K)] += np.concatenate([ec ** 2, el ** 2]) + 1e-8
    try:
        c, low = cho_factor(K)
    except Exception:
        return 1e12
    alpha = cho_solve((c, low), d)
    return 0.5 * d @ alpha + np.sum(np.log(np.diag(c)))


def javelin_profile(tc, fc, ec, tl, fl, el, lags, sigma=None, tau=None):
    """Return (logL(lag), A(lag)); sigma,tau from a continuum-only DRW fit if not given."""
    tc, fc, ec, tl, fl, el = map(np.asarray, (tc, fc, ec, tl, fl, el))
    if sigma is None or tau is None:
        gp = gp_fit(tc, fc, ec); sigma, tau = gp["sigma"], gp["tau"]
    dc = fc - fc.mean(); dl = fl - fl.mean()
    A0 = (dl.std() + 1e-12) / (dc.std() + 1e-12)
    logL = np.full(len(lags), -np.inf); Aopt = np.full(len(lags), np.nan)
    for k, lag in enumerate(lags):
        r = minimize_scalar(lambda A: _jav_nll(lag, A, tc, dc, ec, tl, dl, el, sigma, tau),
                            bounds=(0.05 * A0, 20 * A0), method="bounded",
                            options={"xatol": A0 * 1e-2})
        logL[k] = -r.fun; Aopt[k] = r.x
    return logL, Aopt


def javelin_lag(tc, fc, ec, tl, fl, el, lags, sigma=None, tau=None, maxc=120):
    """Posterior mode, 68% interval, and a multimodality (aliasing) flag."""
    tc, fc, ec = map(np.asarray, (tc, fc, ec))
    if len(tc) > maxc:
        idx = np.linspace(0, len(tc) - 1, maxc).astype(int)
        tc, fc, ec = tc[idx], fc[idx], ec[idx]
    logL, _ = javelin_profile(tc, fc, ec, tl, fl, el, lags, sigma, tau)
    post = np.exp(logL - np.nanmax(logL))
    post = post / np.sum(post)
    mode = lags[int(np.nanargmax(logL))]
    cdf = np.cumsum(post) / np.sum(post)
    lo = lags[np.searchsorted(cdf, 0.16)]
    hi = lags[min(np.searchsorted(cdf, 0.84), len(lags) - 1)]
    peaks = [(lags[i], post[i]) for i in range(1, len(post) - 1)
             if post[i] >= post[i - 1] and post[i] >= post[i + 1]]
    peaks.sort(key=lambda p: -p[1])
    multimodal = any(p[1] > 0.3 * peaks[0][1] and abs(p[0] - peaks[0][0]) > 15
                     for p in peaks[1:]) if peaks else False
    return mode, lo, hi, multimodal, logL


# --------------------------------------------------------------------------------------
# Trust layer: physical window, sampling facts + arbiter, red-noise gate, cross-witness
# --------------------------------------------------------------------------------------
def physical_window(lags, floor=-5.0):
    """Boolean mask keeping only physically allowed (>= floor) lags. Line lags are >= ~0."""
    return np.asarray(lags, float) >= floor


def sampling_acf(t, lags, binw=1.0):
    """Normalized autocorrelation of the observing window (schedule only, no fluxes)."""
    t = np.asarray(t, float)
    t0 = t.min()
    n = int(np.ceil((t.max() - t0) / binw)) + 1
    s = np.zeros(n)
    s[np.clip(((t - t0) / binw).astype(int), 0, n - 1)] = 1.0
    s = s - s.mean()
    denom = np.sum(s * s)
    A = np.full(len(lags), np.nan)
    for k, L in enumerate(lags):
        sh = int(round(abs(L) / binw))
        if sh >= n or denom <= 0:
            continue
        a, b = s[sh:], s[:n - sh]
        if len(a) > 3:
            A[k] = np.sum(a * b) / denom
    return A


def pair_count(tc, tl, lags, dt=6.0):
    """Continuum->line epoch pairs per lag bin = the CCF's actual support at each lag."""
    tc, tl = np.asarray(tc, float), np.asarray(tl, float)
    diff = (tl[None, :] - tc[:, None]).ravel()
    return np.array([np.sum((diff >= L - dt / 2) & (diff < L + dt / 2)) for L in lags], float)


def _at(lags, arr, x):
    return arr[int(np.argmin(np.abs(np.asarray(lags) - x)))]


def arbitrate(drw, jav, lags, A, N, agree_tol=8.0):
    """Break a DRW-vs-JAVELIN split with the sampling facts (not more estimators).

    Returns (lag, mode, conflict):
      mode='agree'  -> legs agree within agree_tol; lag = mean
      mode='fact'   -> legs disagree; both facts point the same way; lag = that leg
      conflict=True -> facts POINT OPPOSITE ways -> keep the higher-support leg, raise the flag
    """
    if abs(drw - jav) <= agree_tol:
        return 0.5 * (drw + jav), "agree", False
    a_drw, a_jav = _at(lags, A, drw), _at(lags, A, jav)
    n_drw, n_jav = _at(lags, N, drw), _at(lags, N, jav)
    pick_a = jav if a_drw > a_jav else drw     # believe the leg NOT on the bigger echo
    pick_n = drw if n_drw > n_jav else jav     # believe the leg with more support
    if pick_a == pick_n:
        return pick_a, "fact", False
    return pick_n, "fact", True


def simulate_drw(times, sigma, tau, rng):
    """One damped-random-walk realization on the given (sorted) times."""
    times = np.asarray(times, float)
    n = len(times)
    x = np.zeros(n)
    x[0] = rng.normal(0, sigma / np.sqrt(2))
    for i in range(1, n):
        dt = times[i] - times[i - 1]
        rho = np.exp(-dt / tau)
        var = max((sigma ** 2 / 2) * (1 - rho ** 2), 0.0)
        x[i] = rho * x[i - 1] + rng.normal(0, np.sqrt(var))
    return x


def rednoise_pvalue(tc, fc, ec, tl, fl, el, lags, sigma, tau,
                    min_overlap=20, nsim=300, rng=None):
    """False-alarm probability that the CCF peak is a red-noise coincidence (no real lag).

    Simulates independent DRW pairs with matched sampling/noise and NO imposed lag; p_false
    is the fraction whose peak r matches or beats the observed r_max.
    """
    rng = rng or np.random.default_rng(7)
    ec, el = np.asarray(ec), np.asarray(el)
    r_obs = np.nanmax(iccf(tc, fc, tl, fl, lags, min_overlap=min_overlap))
    if not np.isfinite(r_obs):
        return np.nan, np.nan
    count = 0
    for _ in range(nsim):
        sc = simulate_drw(tc, sigma, tau, rng) + rng.normal(0, 1, len(tc)) * ec
        sl = simulate_drw(tl, sigma, tau, rng) + rng.normal(0, 1, len(tl)) * el  # independent
        rm = np.nanmax(iccf(tc, sc, tl, sl, lags, min_overlap=min_overlap))
        if np.isfinite(rm) and rm >= r_obs:
            count += 1
    return r_obs, count / nsim


def cross_split(lag_primary, lag_witness):
    """Absolute lag split between a primary look and an independent witness (a Look-axis test).

    A LARGE split subtracts confidence (and occasionally hands you the true lag); a SMALL split
    does NOT certify correctness. Directional only -- never used to add confidence.
    """
    return abs(float(lag_primary) - float(lag_witness))


# --------------------------------------------------------------------------------------
# Channel axis: reverberation cascade + coupling-strength (X-ray timing done right)
# --------------------------------------------------------------------------------------
def _cascade_centroid(lags, r, frac=0.8):
    """Centroid over the CONTIGUOUS region around the peak >= frac*r_max (robust to aliasing)."""
    lags = np.asarray(lags, float)
    r = np.asarray(r, float)
    if np.all(np.isnan(r)):
        return np.nan, np.nan
    ip = int(np.nanargmax(r)); rmax = r[ip]
    if not np.isfinite(rmax) or rmax <= 0:
        return np.nan, rmax
    thr = frac * rmax
    lo = ip
    while lo - 1 >= 0 and np.isfinite(r[lo - 1]) and r[lo - 1] >= thr:
        lo -= 1
    hi = ip
    while hi + 1 < len(r) and np.isfinite(r[hi + 1]) and r[hi + 1] >= thr:
        hi += 1
    ls, rs = lags[lo:hi + 1], r[lo:hi + 1]
    gg = np.isfinite(rs)
    return float(np.sum(ls[gg] * rs[gg]) / np.sum(rs[gg])), float(rmax)


def coupling_strength(driver_t, driver_f, target_t, target_f, lags, min_overlap=30):
    """Channel-axis link test: lag of target behind driver + the correlation STRENGTH r_max.

    Returns (lag, r_max, coupled). `coupled` is False when r_max < COUPLING_THRESHOLD -> the link
    is disconnected and its lag is meaningless; report the DISCONNECT, not the lag. (This is how
    the framework independently recovers the AGN STORM 2 X-ray/UV disconnect.) `coupled` is None
    when overlap is insufficient (all-NaN CCF) -- 'not enough data' is NOT a physical disconnect.
    """
    r = iccf(driver_t, driver_f, target_t, target_f, lags, min_overlap=min_overlap)
    lag, rmax = _cascade_centroid(lags, r)
    if not np.isfinite(rmax):
        return lag, rmax, None
    coupled = bool(rmax >= COUPLING_THRESHOLD)
    return lag, rmax, coupled


def cascade(ref_t, ref_f, bands, lags, min_overlap=30):
    """Reverberation cascade: lag + r_max of each band behind a reference driver.

    `bands` = ordered iterable of (name, t, f[, wavelength]); redder (longer-wavelength) bands
    should lag more in a clean disk cascade. Returns a list of dicts
    {name, wavelength, lag, r_max, coupled}. Believe a band's lag only where r_max is high.
    """
    out = []
    for entry in bands:
        name, tb, fb = entry[0], entry[1], entry[2]
        wl = entry[3] if len(entry) > 3 else None
        r = iccf(ref_t, ref_f, tb, fb, lags, min_overlap=min_overlap)
        lag, rmax = _cascade_centroid(lags, r)
        out.append({
            "name": name, "wavelength": wl, "lag": lag, "r_max": rmax,
            "coupled": None if not np.isfinite(rmax) else bool(rmax >= COUPLING_THRESHOLD),
        })
    return out


def cascade_ordered(results, tol=0.15):
    """True if the coupled bands' lags increase with wavelength (within tol) -- a clean disk
    cascade, the Channel-axis corroboration. Needs >= 3 coupled, wavelength-tagged bands."""
    pts = sorted((r["wavelength"], r["lag"]) for r in results
                 if r.get("wavelength") and r["coupled"] and np.isfinite(r["lag"]))
    lags = [p[1] for p in pts]
    if len(lags) < 3:
        return False
    inversions = sum(1 for i in range(1, len(lags)) if lags[i] < lags[i - 1] - tol)
    return inversions == 0


# --------------------------------------------------------------------------------------
# TrustState -- the confidence tracker that assembles the verdict
# --------------------------------------------------------------------------------------
class TrustState:
    """Accumulates estimator agreement, verification gates, and independent witnesses into
    one calibrated verdict. Enforces the tier ladder: refuse < low < medium < high.

    A witness may only LOWER the ceiling. `high` requires an available witness that corroborates.
    """

    SPLIT_FLAG_DAYS = 10.0  # a cross-witness split beyond this subtracts confidence

    def __init__(self, object_id, redshift=None, n_cont=None, n_line=None):
        self.object_id = str(object_id)
        self.redshift = redshift
        self.n_cont = n_cont
        self.n_line = n_line
        self.lag = None
        self.estimators = {}      # name -> lag
        self.agreement = None     # 'agree' | 'fact' | 'conflict' | None
        self.verifications = []   # {name, passed, detail}
        self.witnesses = []       # {name, axis, available, corroborates, split, detail}
        self.notes = []

    # ---- inputs -------------------------------------------------------------
    def set_lag(self, lag, estimators=None, agreement=None):
        self.lag = None if lag is None else float(lag)
        if estimators:
            self.estimators.update({k: (None if v is None else float(v))
                                    for k, v in estimators.items()})
        if agreement:
            self.agreement = agreement
        return self

    def add_verification(self, name, passed, detail=""):
        self.verifications.append({"name": name, "passed": bool(passed), "detail": detail})
        return self

    def add_witness(self, name, axis, available, corroborates=None, split=None, detail=""):
        """Record an independent witness. axis in {'look','channel','interaction','internal'}.
        `available` False means the witness structurally could not run (lowers the ceiling only).
        """
        self.witnesses.append({
            "name": name, "axis": axis, "available": bool(available),
            "corroborates": corroborates, "split": None if split is None else float(split),
            "detail": detail,
        })
        return self

    def note(self, text):
        self.notes.append(text)
        return self

    # ---- derived ------------------------------------------------------------
    def below_floor(self):
        if self.n_cont is not None and self.n_cont < ESTIMATION_FLOOR_CONT:
            return True
        if self.n_line is not None and self.n_line < ESTIMATION_FLOOR_LINE:
            return True
        return False

    def _verification_failed(self):
        return any(not v["passed"] for v in self.verifications)

    def _split_flag(self):
        return any(w["split"] is not None and w["split"] > self.SPLIT_FLAG_DAYS
                   for w in self.witnesses)

    def _has_corroborating_witness(self):
        return any(w["available"] and w["corroborates"] is True for w in self.witnesses)

    def tier(self):
        """refuse | low | medium | high -- confidence tracks available checks."""
        if self.below_floor() or self.lag is None:
            return "refuse"
        if self._verification_failed() or self.agreement == "conflict" or self._split_flag():
            return "low"
        if self._has_corroborating_witness():
            return "high"
        return "medium"

    def verdict(self):
        return {
            "object_id": self.object_id,
            "redshift": self.redshift,
            "lag": self.lag,
            "tier": self.tier(),
            "estimators": self.estimators,
            "agreement": self.agreement,
            "verifications": self.verifications,
            "witnesses": self.witnesses,
            "notes": self.notes,
        }

    def to_json(self, **kw):
        return json.dumps(self.verdict(), default=float, **kw)


# --------------------------------------------------------------------------------------
# I/O convention: /input -> /output (mirrors the tool-container contract)
# --------------------------------------------------------------------------------------
def quick_setup(input_dir="/input", output_dir="/output", work_dir="/workdir"):
    """Ensure I/O dirs exist and configure logging. Returns (input_dir, output_dir, work_dir)."""
    for d in (output_dir, work_dir):
        os.makedirs(d, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return input_dir, output_dir, work_dir


def load_lightcurves(path):
    """Load a light-curve bundle. Expected JSON:
        {
          "object_id": "RMID-767", "redshift": 0.52,
          "continuum": {"t": [...], "f": [...], "e": [...]},
          "line":      {"t": [...], "f": [...], "e": [...]},
          "continuum2": {...},                 # optional 2nd band -> Look witness
          "cascade": {                          # optional Channel-axis bundle
            "reference": "UVW2",
            "bands": [{"name": "UVW2", "wavelength": 1928, "t": [...], "f": [...]}, ...],
            "xray_driver": {"name": "soft", "t": [...], "f": [...]}
          }
        }
    Returns the parsed dict with numpy arrays for each series.
    """
    with open(path) as fh:
        d = json.load(fh)
    for key in ("continuum", "line", "continuum2", "line2"):
        s = d.get(key)
        if s:
            for c in ("t", "f", "e"):
                if c in s:
                    s[c] = np.asarray(s[c], float)
    casc = d.get("cascade")
    if casc:
        for bnd in casc.get("bands", []):
            for c in ("t", "f"):
                if c in bnd:
                    bnd[c] = np.asarray(bnd[c], float)
        xd = casc.get("xray_driver")
        if xd:
            for c in ("t", "f"):
                if c in xd:
                    xd[c] = np.asarray(xd[c], float)
    return d


def save_final_results(results, output_files=None, output_dir="/output"):
    """Write the machine-readable verdict(s) and register any produced files."""
    os.makedirs(output_dir, exist_ok=True)
    payload = {"results": results, "output_files": output_files or {}}
    with open(os.path.join(output_dir, "results.json"), "w") as fh:
        json.dump(payload, fh, indent=2, default=float)
    return payload


def quick_finish():
    logging.info("reverberation-trust run complete.")
