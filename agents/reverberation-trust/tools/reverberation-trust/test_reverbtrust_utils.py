"""
Tests for reverbtrust_utils. Runnable with `pytest` or directly: `python test_reverbtrust_utils.py`.

Covers: estimator lag recovery on an injected lag (ICCF + DRW), the sampling-fact arbiter's
three outcomes, the red-noise gate, and the TrustState tier ladder (the trust contract).
"""
import numpy as np
import pytest

from reverbtrust_utils import (
    iccf, centroid, drw_lag, arbitrate, sampling_acf, pair_count,
    rednoise_pvalue, cross_split, TrustState, physical_window,
    cascade, coupling_strength, cascade_ordered,
)

TAU_TRUE = 20.0


def _make_curves(seed=42, cadence=2.0, tmax=360.0, err=0.02):
    """Injected-lag DRW continuum + boxcar-smoothed shifted line, sampled with noise."""
    rng = np.random.default_rng(seed)
    td = np.arange(-60, tmax + 60, 0.2)
    # dense DRW continuum (amplitude chosen so signal comfortably exceeds sample noise)
    x = np.zeros(len(td)); x[0] = rng.normal(0, 0.55)
    for i in range(1, len(td)):
        rho = np.exp(-(td[i] - td[i - 1]) / 25.0)
        x[i] = rho * x[i - 1] + rng.normal(0, np.sqrt(0.30 * (1 - rho ** 2)))
    cont_d = 15.0 + x
    line_d = np.interp(td - TAU_TRUE, td, cont_d)
    line_d = np.convolve(line_d, np.ones(21) / 21, mode="same")

    def samp(fd):
        t = np.sort(np.clip(np.arange(0, tmax, cadence) + rng.normal(0, 0.3, int(tmax / cadence)),
                            0, tmax))
        f = np.interp(t, td, fd)
        e = np.full(len(t), err * np.median(f))
        return t, f + rng.normal(0, 1, len(t)) * e, e

    tc, fc, ec = samp(cont_d)
    tl, fl, el = samp(line_d)
    return tc, fc, ec, tl, fl, el


def test_iccf_recovers_injected_lag():
    tc, fc, ec, tl, fl, el = _make_curves()
    lags = np.arange(-30, 71, 1.0)
    r = iccf(tc, fc, tl, fl, lags)
    cent, peak, rmax = centroid(lags, r)
    assert rmax > 0.7
    assert abs(cent - TAU_TRUE) < 6.0


def test_drw_recovers_injected_lag():
    tc, fc, ec, tl, fl, el = _make_curves()
    lags = np.arange(-30, 71, 1.0)
    lag, chi2, gp = drw_lag(tc, fc, ec, tl, fl, el, lags)
    assert abs(lag - TAU_TRUE) < 8.0
    assert gp["tau"] > 0


def test_physical_window_masks_unphysical():
    lags = np.arange(-30, 31, 1.0)
    mask = physical_window(lags, floor=-5.0)
    assert not mask[0]              # -30 excluded
    assert mask[lags == 20.0][0]    # +20 kept


def test_arbitrate_agree_fact_conflict():
    lags = np.arange(0, 80, 1.0)
    A = np.zeros_like(lags); N = np.ones_like(lags)
    # agree: legs within tolerance
    lag, mode, conflict = arbitrate(20.0, 24.0, lags, A, N, agree_tol=8.0)
    assert mode == "agree" and not conflict
    # fact: legs disagree; both facts favor the long leg (60).
    # echo high on the SHORT leg -> distrust 12; support high on 60 -> believe 60.
    A2 = A.copy(); A2[lags == 12.0] = 0.9
    N2 = N.copy(); N2[lags == 60.0] = 50.0
    lag, mode, conflict = arbitrate(12.0, 60.0, lags, A2, N2, agree_tol=8.0)
    assert mode == "fact" and lag == 60.0 and not conflict
    # conflict: facts point opposite ways -> flag raised.
    # echo high on the LONG leg -> distrust 60; support high on 60 -> believe 60.
    A3 = A.copy(); A3[lags == 60.0] = 0.9
    N3 = N.copy(); N3[lags == 60.0] = 50.0
    lag, mode, conflict = arbitrate(12.0, 60.0, lags, A3, N3, agree_tol=8.0)
    assert conflict is True


def test_sampling_facts_shapes():
    tc, fc, ec, tl, fl, el = _make_curves()
    lags = np.arange(0, 70, 1.0)
    A = sampling_acf(tc, lags)
    N = pair_count(tc, tl, lags)
    assert len(A) == len(lags) and len(N) == len(lags)
    assert np.nanmax(N) > 0


def test_rednoise_gate_flags_real_lag_as_significant():
    tc, fc, ec, tl, fl, el = _make_curves()
    lags = np.arange(-30, 71, 1.0)
    r_obs, p_false = rednoise_pvalue(tc, fc, ec, tl, fl, el, lags,
                                     sigma=0.35, tau=25.0, nsim=100)
    assert r_obs > 0.6
    assert p_false < 0.2            # a real injected lag should rarely be faked by red noise


def _make_cascade(seed=7):
    """A driver DRW + wavelength-ordered lagged bands (coupled) + one disconnected band."""
    rng = np.random.default_rng(seed)
    td = np.arange(-40, 200, 0.2)
    x = np.zeros(len(td)); x[0] = rng.normal(0, 0.6)
    for i in range(1, len(td)):
        rho = np.exp(-(td[i] - td[i - 1]) / 20.0)
        x[i] = rho * x[i - 1] + rng.normal(0, np.sqrt(0.35 * (1 - rho ** 2)))
    drv = 1.0 + x

    def samp(fd, lag):
        shifted = np.interp(td - lag, td, fd)
        shifted = np.convolve(shifted, np.ones(9) / 9, mode="same")
        t = np.arange(0, 150, 1.0)
        f = np.interp(t, td, shifted)
        return t, f + rng.normal(0, 0.02, len(t))

    ref_t, ref_f = samp(drv, 0.0)
    bands = [("UVW2", ref_t, ref_f, 1928)]
    for name, wl, lag in [("UVM2", 2246, 0.4), ("UVW1", 2600, 0.8),
                          ("U", 3465, 1.4), ("V", 5468, 2.2)]:
        tb, fb = samp(drv, lag)
        bands.append((name, tb, fb, wl))
    # a disconnected band: an INDEPENDENT DRW (no coupling to the driver)
    y = np.zeros(len(td)); y[0] = rng.normal(0, 0.6)
    for i in range(1, len(td)):
        rho = np.exp(-(td[i] - td[i - 1]) / 20.0)
        y[i] = rho * y[i - 1] + rng.normal(0, np.sqrt(0.35 * (1 - rho ** 2)))
    dt = np.arange(0, 150, 1.0)
    disc_f = np.interp(dt, td, 1.0 + y) + rng.normal(0, 0.02, len(dt))
    return bands, (dt, disc_f)


def test_cascade_is_wavelength_ordered():
    bands, _ = _make_cascade()
    lags = np.arange(-10.0, 10.01, 0.1)
    res = cascade(bands[0][1], bands[0][2], bands, lags)
    coupled = [r for r in res if r["coupled"]]
    assert len(coupled) >= 4                       # the disk bands are all coupled
    assert cascade_ordered(res) is True            # lags increase with wavelength


def test_coupling_strength_flags_disconnect():
    bands, (dt, disc_f) = _make_cascade()
    ref_t, ref_f = bands[0][1], bands[0][2]
    lags = np.arange(-10.0, 10.01, 0.1)
    # a genuinely lagged, coupled band reads as coupled
    lag, r, coupled = coupling_strength(ref_t, ref_f, bands[2][1], bands[2][2], lags)
    assert coupled is True and r > 0.5
    # an independent band reads as disconnected (the X-ray/UV disconnect pattern)
    lag_d, r_d, coupled_d = coupling_strength(ref_t, ref_f, dt, disc_f, lags)
    assert coupled_d is False and r_d < 0.5


def test_channel_witness_raises_tier():
    s = TrustState("E", n_cont=40, n_line=30).set_lag(
        3.0, estimators={"drw": 3.0, "javelin": 3.2}, agreement="agree")
    s.add_verification("red_noise", passed=True)
    s.add_verification("aliasing", passed=True)
    s.add_witness("disk_cascade", axis="channel", available=True, corroborates=True,
                  detail="wavelength-ordered=True")
    assert s.tier() == "high"


def test_truststate_tier_ladder():
    # refuse: below the estimation floor
    s = TrustState("A", n_cont=5, n_line=3).set_lag(20.0)
    assert s.tier() == "refuse"

    # medium: estimators agree, no independent witness available
    s = TrustState("B", n_cont=40, n_line=30).set_lag(
        20.0, estimators={"drw": 20.0, "javelin": 21.0}, agreement="agree")
    s.add_verification("red_noise", passed=True, detail="p_false=0.01")
    s.add_witness("i_band", axis="look", available=False, detail="single band")
    assert s.tier() == "medium"

    # high: an available witness corroborates
    s.add_witness("halpha", axis="look", available=True, corroborates=True,
                  split=2.0, detail="Ha lag agrees")
    assert s.tier() == "high"

    # low: verification fails
    s2 = TrustState("C", n_cont=40, n_line=30).set_lag(
        20.0, estimators={"drw": 20.0}, agreement="agree")
    s2.add_verification("red_noise", passed=False, detail="p_false=0.4")
    assert s2.tier() == "low"

    # low: a large cross-witness split subtracts confidence
    s3 = TrustState("D", n_cont=40, n_line=30).set_lag(
        12.0, estimators={"drw": 12.0}, agreement="agree")
    s3.add_verification("red_noise", passed=True)
    s3.add_witness("i_band", axis="look", available=True, corroborates=False,
                   split=cross_split(12.0, 60.0), detail="band systematic")
    assert s3.tier() == "low"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
