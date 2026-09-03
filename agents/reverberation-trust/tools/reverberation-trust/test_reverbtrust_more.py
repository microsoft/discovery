"""
Coverage + regression tests for reverbtrust_utils (pytest-native; t123-migrate 2026-09-02).

Covers the public surface the base suite left untested (centroid, frrss, javelin_lag, simulate_drw,
cross_split, the I/O convention) and locks in the fixes for three defects the adversarial review
found. One intentional design slack is left as a non-strict xfail -- a different kind of signal
(a documented, benign quirk, not a scheduled fix).

Pytest-collectable and dual-runnable: `pytest` collects the test_* functions; `python
test_reverbtrust_more.py` re-invokes pytest on this file.
"""
import json
import os
import tempfile

import numpy as np
import pytest

import reverbtrust_utils as R
from test_reverbtrust_utils import _make_curves, TAU_TRUE


# ---------------------------------------------------------------------------
# Functional / boundary / negative coverage for the untested surface
# ---------------------------------------------------------------------------
def test_centroid_functional_peaks_at_signal():
    lags = np.arange(-10, 11, 1.0)
    r = np.exp(-(lags - 3.0) ** 2 / 8.0)          # clean Gaussian CCF peaked at +3
    cent, peak, rmax = R.centroid(lags, r)
    assert abs(peak - 3.0) < 1e-9
    assert abs(cent - 3.0) < 1.0
    assert 0.99 < rmax <= 1.0


def test_frrss_recovers_injected_lag():
    tc, fc, ec, tl, fl, el = _make_curves()
    lags = np.arange(-30, 71, 1.0)
    med, lo, hi, samples = R.frrss(tc, fc, ec, tl, fl, el, lags, n=120)
    assert lo <= med <= hi
    assert abs(med - TAU_TRUE) < 8.0
    assert len(samples) > 10


def test_javelin_lag_recovers_injected_lag():
    tc, fc, ec, tl, fl, el = _make_curves()
    lags = np.arange(-30, 71, 1.0)
    mode, lo, hi, multimodal, logL = R.javelin_lag(tc, fc, ec, tl, fl, el, lags)
    assert abs(mode - TAU_TRUE) < 10.0
    assert lo <= mode <= hi
    assert len(logL) == len(lags)


def test_simulate_drw_shape_and_boundary():
    rng = np.random.default_rng(0)
    x = R.simulate_drw(np.arange(50.0), 0.5, 20.0, rng)
    assert len(x) == 50 and np.all(np.isfinite(x))
    assert np.std(x) > 0                          # not a flat line
    x1 = R.simulate_drw(np.array([0.0]), 0.5, 20.0, rng)   # single-epoch boundary
    assert len(x1) == 1 and np.isfinite(x1[0])


def test_cross_split_is_symmetric_nonnegative():
    assert R.cross_split(10.0, 25.0) == 15.0
    assert R.cross_split(25.0, 10.0) == 15.0      # symmetry
    assert R.cross_split(5.0, 5.0) == 0.0


def test_io_roundtrip_functional():
    with tempfile.TemporaryDirectory() as d:
        R.quick_setup(input_dir=d, output_dir=d, work_dir=os.path.join(d, "w"))
        bundle = {"object_id": "X1", "redshift": 0.3,
                  "continuum": {"t": [0, 1, 2], "f": [1, 2, 3], "e": [0.1, 0.1, 0.1]},
                  "line": {"t": [1, 2, 3], "f": [1, 2, 3], "e": [0.1, 0.1, 0.1]}}
        p = os.path.join(d, "lc.json")
        with open(p, "w") as fh:
            json.dump(bundle, fh)
        loaded = R.load_lightcurves(p)
        assert isinstance(loaded["continuum"]["t"], np.ndarray)   # arrays parsed
        assert loaded["object_id"] == "X1"
        R.save_final_results({"tier": "medium"}, output_dir=d)
        with open(os.path.join(d, "results.json")) as fh:
            back = json.load(fh)
        assert back["results"]["tier"] == "medium"
        R.quick_finish()


def test_load_lightcurves_missing_file_raises():
    # Negative: the external-input boundary should fail cleanly, not silently return junk.
    raised = False
    try:
        R.load_lightcurves(os.path.join(tempfile.gettempdir(), "definitely_not_here_9x.json"))
    except (FileNotFoundError, OSError):
        raised = True
    assert raised


def test_hostile_object_id_is_inert_string():
    # Theme 4: the only user-controlled value reaching output is object_id (an identifier
    # passthrough, not rendered HTML). Assert it is stored as an inert string, never executed.
    hostile = "<script>alert(1)</script>'; DROP TABLE lags; --"
    st = R.TrustState(hostile, n_cont=40, n_line=30).set_lag(5.0, agreement="agree")
    v = st.verdict()
    assert isinstance(v["object_id"], str)
    assert v["object_id"] == hostile              # stored verbatim as data, not interpreted


# ---------------------------------------------------------------------------
# Regression tests - lock in the fixes for the three defects the review found
# ---------------------------------------------------------------------------
def test_centroid_all_nan_returns_nan_gracefully():
    # FIXED: was ValueError (nanargmax on all-NaN); now returns nan like _cascade_centroid.
    lags = np.arange(0, 10, 1.0)
    cent, peak, rmax = R.centroid(lags, np.full(len(lags), np.nan))
    assert np.isnan(cent) and np.isnan(peak) and np.isnan(rmax)


def test_coupling_insufficient_overlap_returns_none_not_false():
    # FIXED: overlap < min_overlap now reports coupled=None ('cannot judge'), not a false disconnect.
    t = np.arange(10.0)
    f = np.sin(t)
    lag, r, coupled = R.coupling_strength(t, f, t, f, np.arange(-3, 3, 0.5))
    assert coupled is None


def test_centroid_no_positive_peak_is_consistent():
    # FIXED: rmax<=0 now yields a coherent no-peak signal (nan cent AND nan peak), not (nan, finite).
    lags = np.arange(0, 10, 1.0)
    cent, peak, rmax = R.centroid(lags, np.linspace(-0.9, -0.1, len(lags)))
    assert rmax <= 0
    assert np.isnan(cent) and np.isnan(peak)


# ---------------------------------------------------------------------------
# A different kind of signal: an intentional design slack left as a non-strict xfail
# ---------------------------------------------------------------------------
@pytest.mark.xfail(strict=False, reason=(
    "KNOWN/BENIGN: physical_window default floor is -5 d -- it tolerates small negative lags from "
    "measurement scatter rather than enforcing a strict 0. Emission-line lags are physically >= 0, "
    "so a purist expects negatives rejected; the -5 d slack is intentional and documented. This "
    "cannot xpass without changing the default floor, which we deliberately keep."))
def test_physical_window_rejects_all_negative_lags():
    lags = np.array([-3.0, -1.0, 0.0, 5.0])
    mask = R.physical_window(lags)                 # default floor -5.0 admits -3 and -1
    assert not mask[0] and not mask[1]


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
