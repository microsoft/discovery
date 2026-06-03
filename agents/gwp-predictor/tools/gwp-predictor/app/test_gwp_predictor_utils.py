#!/usr/bin/env python3
"""Unit tests for gwp_predictor_utils.py -- run with pytest.

Tests run WITHOUT a trained model (uses mock/stub predictions where needed).
Model-dependent tests are marked with @pytest.mark.model and skipped if
/app/models/manifest.json doesn't exist.
"""

import pytest
import os
import sys
import json
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from gwp_predictor_utils import (
    validate_smiles,
    compute_features,
    compute_applicability,
    FEATURE_NAMES,
    AD_IN_DISTRIBUTION_MIN,
    AD_EDGE_MIN,
)

HAS_MODEL = os.path.exists("/app/models/manifest.json")


# ============= SMILES validation tests =============
class TestValidateSmiles:
    def test_valid_hfc134a(self):
        assert validate_smiles("FC(F)(F)CF") is True

    def test_valid_methane(self):
        assert validate_smiles("C") is True

    def test_valid_sf6(self):
        assert validate_smiles("FS(F)(F)(F)(F)F") is True

    def test_valid_novec649(self):
        assert validate_smiles("CCC(=O)C(F)(F)C(F)(F)C(F)(F)F") is True

    def test_invalid_empty(self):
        assert validate_smiles("") is False

    def test_invalid_garbage(self):
        assert validate_smiles("not_a_smiles_XYZ123") is False

    def test_invalid_none_string(self):
        assert validate_smiles("None") is False

    def test_valid_ethanol(self):
        assert validate_smiles("CCO") is True

    def test_valid_isomeric(self):
        assert validate_smiles("F/C=C\\C(F)(F)F") is True


# ============= Feature computation tests =============
class TestComputeFeatures:
    def test_methane_features(self):
        f = compute_features("C")
        assert f is not None
        assert f["n_C"] == 1
        assert f["n_H"] == 4
        assert f["n_F"] == 0
        assert f["mw"] > 16.0
        assert f["halogen_fraction"] == 0.0

    def test_hfc134a_features(self):
        # CH2FCF3 = 1,1,1,2-tetrafluoroethane
        f = compute_features("FC(F)(F)CF")
        assert f is not None
        assert f["n_F"] == 4
        assert f["n_C"] == 2
        assert f["n_C_F_bonds"] == 4
        assert f["halogen_fraction"] > 0.5

    def test_sf6_features(self):
        f = compute_features("FS(F)(F)(F)(F)F")
        assert f is not None
        assert f["n_F"] == 6
        assert f["n_S"] == 1
        assert f["n_C"] == 0
        assert f["n_C_F_bonds"] == 0  # S-F bonds, not C-F

    def test_siloxane_features(self):
        f = compute_features("C[Si](C)(C)O[Si](C)(C)O[Si](C)(C)C")
        assert f is not None
        assert f["n_Si"] >= 3
        assert f["n_O"] >= 2

    def test_invalid_returns_none(self):
        assert compute_features("garbage") is None

    def test_all_feature_names_present(self):
        f = compute_features("CCO")
        assert f is not None
        for name in FEATURE_NAMES:
            assert name in f, f"Missing feature: {name}"

    def test_feature_values_numeric(self):
        f = compute_features("FC(F)(F)CF")
        for name in FEATURE_NAMES:
            val = f[name]
            assert isinstance(val, (int, float)), f"{name} is {type(val)}, expected numeric"
            assert not np.isnan(val), f"{name} is NaN"
            assert not np.isinf(val), f"{name} is Inf"

    def test_novec649_features(self):
        # Novec 649: CCC(=O)C(F)(F)C(F)(F)C(F)(F)F
        f = compute_features("CCC(=O)C(F)(F)C(F)(F)C(F)(F)F")
        assert f is not None
        assert f["n_F"] == 7  # 7 fluorines
        assert f["n_O"] == 1  # ketone oxygen
        assert f["n_unsaturated_bonds"] >= 1  # C=O


# ============= Applicability domain tests =============
class TestApplicabilityDomain:
    def test_invalid_smiles_returns_flag(self):
        ad = compute_applicability("not_a_smiles")
        assert ad["ad_flag"] == "invalid_smiles"

    def test_no_training_fp_returns_flag(self):
        # Pass empty array
        ad = compute_applicability("C", training_fp=np.zeros((0, 2048), dtype=np.uint8))
        # Should handle gracefully
        assert "ad_flag" in ad

    def test_ad_thresholds(self):
        assert AD_IN_DISTRIBUTION_MIN == 0.5
        assert AD_EDGE_MIN == 0.3


# ============= JSON output contract tests =============
class TestOutputContract:
    """Test that predict_gwp_single returns the expected JSON schema."""

    REQUIRED_KEYS = [
        "smiles", "smiles_valid", "model_status",
    ]

    OK_KEYS = [
        "gwp_100", "gwp_100_low", "gwp_100_high",
        "atmospheric_lifetime_years",
        "atmospheric_lifetime_years_low", "atmospheric_lifetime_years_high",
        "applicability", "tanimoto_nn_mean",
        "lifetime_disagreement", "opera_lifetime_years",
        "model_id", "training_set", "holdout_mae_log10_gwp",
    ]

    def test_invalid_smiles_contract(self):
        from gwp_predictor_utils import predict_gwp_single
        # Without model loaded, this should still return a valid contract
        # with model_status != "ok"
        result = predict_gwp_single("not_a_smiles")
        for key in self.REQUIRED_KEYS:
            assert key in result, f"Missing required key: {key}"
        assert result["smiles_valid"] is False
        assert result["model_status"] != "ok"

    @pytest.mark.skipif(not HAS_MODEL, reason="No model available")
    def test_valid_smiles_full_contract(self):
        from gwp_predictor_utils import predict_gwp_single
        result = predict_gwp_single("C")
        for key in self.REQUIRED_KEYS + self.OK_KEYS:
            assert key in result, f"Missing key: {key}"
        assert result["smiles_valid"] is True
        assert result["model_status"] == "ok"
        assert result["gwp_100"] > 0
        assert result["gwp_100_low"] < result["gwp_100"]
        assert result["gwp_100_high"] > result["gwp_100"]
        assert result["atmospheric_lifetime_years"] > 0
        assert result["applicability"] in ("in-distribution", "edge", "out-of-distribution")
        assert 0 <= result["tanimoto_nn_mean"] <= 1.0

    @pytest.mark.skipif(not HAS_MODEL, reason="No model available")
    def test_novec649_prediction(self):
        from gwp_predictor_utils import predict_gwp_single
        result = predict_gwp_single("CCC(=O)C(F)(F)C(F)(F)C(F)(F)F")
        assert result["model_status"] == "ok"
        # Novec 649 has GWP100 ~ 1; our prediction should be in the ballpark
        assert result["gwp_100"] < 100, f"Novec 649 GWP too high: {result['gwp_100']}"


# ============= Batch prediction tests =============
class TestBatchPrediction:
    def test_empty_list(self):
        from gwp_predictor_utils import predict_gwp_batch
        results = predict_gwp_batch([])
        assert results == []

    def test_single_invalid(self):
        from gwp_predictor_utils import predict_gwp_batch
        results = predict_gwp_batch(["garbage"])
        assert len(results) == 1
        assert results[0]["smiles_valid"] is False

    @pytest.mark.skipif(not HAS_MODEL, reason="No model available")
    def test_batch_of_three(self):
        from gwp_predictor_utils import predict_gwp_batch
        results = predict_gwp_batch(["C", "CCO", "FC(F)(F)CF"])
        assert len(results) == 3
        ok_count = sum(1 for r in results if r.get("model_status") == "ok")
        assert ok_count == 3


# ============= Module-level sanity =============
class TestModuleSanity:
    def test_feature_names_count(self):
        assert len(FEATURE_NAMES) == 27

    def test_feature_names_unique(self):
        assert len(set(FEATURE_NAMES)) == len(FEATURE_NAMES)

    def test_constants(self):
        from gwp_predictor_utils import CI_SCALE_GWP, CI_Z_95
        assert CI_SCALE_GWP > 0
        assert CI_Z_95 == 1.96


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
