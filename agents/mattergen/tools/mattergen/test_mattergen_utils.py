#!/usr/bin/env python3
"""Unit tests for mattergen_utils.py -- run with pytest.

Tests that can run WITHOUT MatterGen or GPU installed (pure logic tests).
Container-level integration tests require the full Docker image.
"""
import pytest
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from mattergen_utils import (
    PRETRAINED_MODELS,
    MODEL_PROPERTIES,
    PROPERTY_DESCRIPTIONS,
    select_model_for_property,
    validate_model_name,
    list_models,
    save_final_results,
    structures_to_summary,
    analyze_composition_diversity,
)


class TestModelRegistry:
    """Test the model name registry and property mappings."""

    def test_all_models_listed(self):
        assert len(PRETRAINED_MODELS) == 9

    def test_base_models_have_no_properties(self):
        assert MODEL_PROPERTIES["mattergen_base"] == []
        assert MODEL_PROPERTIES["mp_20_base"] == []

    def test_conditioned_models_have_properties(self):
        assert "dft_band_gap" in MODEL_PROPERTIES["dft_band_gap"]
        assert "dft_mag_density" in MODEL_PROPERTIES["dft_mag_density"]
        assert "chemical_system" in MODEL_PROPERTIES["chemical_system"]

    def test_multi_property_models(self):
        props = MODEL_PROPERTIES["chemical_system_energy_above_hull"]
        assert "chemical_system" in props
        assert "energy_above_hull" in props

        props2 = MODEL_PROPERTIES["dft_mag_density_hhi_score"]
        assert "dft_mag_density" in props2
        assert "hhi_score" in props2

    def test_all_properties_have_descriptions(self):
        all_props = set()
        for props in MODEL_PROPERTIES.values():
            all_props.update(props)
        for prop in all_props:
            assert prop in PROPERTY_DESCRIPTIONS, f"Missing description for {prop}"


class TestModelSelection:
    """Test the model selection logic."""

    def test_select_band_gap_model(self):
        model = select_model_for_property("dft_band_gap")
        assert model == "dft_band_gap"

    def test_select_mag_density_model(self):
        model = select_model_for_property("dft_mag_density")
        assert model == "dft_mag_density"

    def test_select_bulk_modulus_model(self):
        model = select_model_for_property("ml_bulk_modulus")
        assert model == "ml_bulk_modulus"

    def test_select_space_group_model(self):
        model = select_model_for_property("space_group")
        assert model == "space_group"

    def test_select_unknown_property_raises(self):
        with pytest.raises(ValueError, match="No model supports"):
            select_model_for_property("nonexistent_property")


class TestValidation:
    """Test validation functions."""

    def test_valid_model_name(self):
        assert validate_model_name("mattergen_base") is True

    def test_invalid_model_name(self):
        with pytest.raises(ValueError, match="Unknown model"):
            validate_model_name("fake_model")


class TestListModels:
    """Test listing functions."""

    def test_list_models_returns_all(self):
        models = list_models()
        assert len(models) == 9

    def test_list_models_structure(self):
        models = list_models()
        for m in models:
            assert "model_name" in m
            assert "conditioning_properties" in m
            assert "is_base_model" in m

    def test_base_models_flagged(self):
        models = list_models()
        base_models = [m for m in models if m["is_base_model"]]
        assert len(base_models) == 2


class TestSaveFinalResults:
    """Test output saving."""

    def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import mattergen_utils
            orig = mattergen_utils.OUTPUT_DIR
            mattergen_utils.OUTPUT_DIR = tmpdir
            try:
                save_final_results(
                    {"num_structures": 5},
                    output_files={"cif": "/output/structures.zip"},
                    file_descriptions={"cif": "Generated CIF files"},
                )
                fpath = os.path.join(tmpdir, "final_results.json")
                assert os.path.exists(fpath)
                with open(fpath) as f:
                    data = json.load(f)
                assert data["status"] == "completed"
                assert data["summary"]["num_structures"] == 5
            finally:
                mattergen_utils.OUTPUT_DIR = orig


class TestStructureSummary:
    """Test structure summary with mock pymatgen objects."""

    def test_summary_empty_list(self):
        result = structures_to_summary([])
        assert result == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
