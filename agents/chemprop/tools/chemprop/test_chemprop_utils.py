#!/usr/bin/env python3
"""Unit tests for chemprop_utils.py ΓÇö run with pytest.

These tests validate the utility functions without requiring the full
Chemprop/PyTorch stack (mocked where necessary).
"""

import json
import os
import sys
import tempfile
import shutil

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(__file__))
from chemprop_utils import (
    load_csv_data,
    compute_metrics,
    _json_serializer,
    _aggregate_cv_results,
    save_final_results,
    quick_setup,
)


# ============= Test Data =============

SAMPLE_SMILES = [
    "CC", "CCC", "CCCC", "c1ccccc1", "CC(=O)O",
    "CCO", "CC=O", "C1CCCCC1", "c1ccc(O)cc1", "CC(C)O",
]

SAMPLE_TARGETS = [
    -1.0, -2.0, -3.0, -4.5, -1.5,
    -2.5, -3.5, -5.0, -2.0, -1.8,
]


@pytest.fixture
def sample_csv(tmp_path):
    """Create a sample CSV file for testing."""
    df = pd.DataFrame({
        "smiles": SAMPLE_SMILES,
        "logS": SAMPLE_TARGETS,
        "label": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
    })
    path = tmp_path / "test_data.csv"
    df.to_csv(path, index=False)
    return str(path)


@pytest.fixture
def sample_csv_with_issues(tmp_path):
    """Create a CSV with some problematic entries."""
    df = pd.DataFrame({
        "smiles": SAMPLE_SMILES[:5] + ["", None, "   "] + SAMPLE_SMILES[5:8],
        "logS": SAMPLE_TARGETS[:5] + [np.nan, np.nan, np.nan] + SAMPLE_TARGETS[5:8],
    })
    path = tmp_path / "test_data_issues.csv"
    df.to_csv(path, index=False)
    return str(path)


# ============= Test CSV Loading =============

class TestLoadCsvData:
    def test_load_basic(self, sample_csv):
        df = load_csv_data(sample_csv, "smiles", ["logS"])
        assert len(df) == 10
        assert "smiles" in df.columns
        assert "logS" in df.columns

    def test_auto_detect_targets(self, sample_csv):
        df = load_csv_data(sample_csv, "smiles")
        assert len(df) == 10
        # Should auto-detect numeric columns

    def test_max_rows(self, sample_csv):
        df = load_csv_data(sample_csv, "smiles", ["logS"], max_rows=5)
        assert len(df) == 5

    def test_missing_smiles_column(self, sample_csv):
        with pytest.raises(ValueError, match="SMILES column"):
            load_csv_data(sample_csv, "nonexistent_column")

    def test_missing_target_column(self, sample_csv):
        with pytest.raises(ValueError, match="Target columns not found"):
            load_csv_data(sample_csv, "smiles", ["nonexistent_target"])

    def test_handles_empty_smiles(self, sample_csv_with_issues):
        df = load_csv_data(sample_csv_with_issues, "smiles", ["logS"])
        # Should drop rows with empty/null SMILES and all-NaN targets
        assert len(df) < 10
        assert df["smiles"].notna().all()
        assert (df["smiles"].str.strip() != "").all()


# ============= Test Metrics =============

class TestComputeMetrics:
    def test_regression_metrics(self):
        y_true = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        y_pred = np.array([1.1, 2.2, 2.8, 4.1, 5.3])
        metrics = compute_metrics(y_true, y_pred, "regression")
        assert "rmse" in metrics
        assert "mae" in metrics
        assert "r2" in metrics
        assert "mse" in metrics
        assert metrics["rmse"] > 0
        assert metrics["mae"] > 0
        assert metrics["r2"] > 0.9  # Should be high for good predictions

    def test_perfect_regression(self):
        y = np.array([1.0, 2.0, 3.0])
        metrics = compute_metrics(y, y, "regression")
        assert metrics["rmse"] == pytest.approx(0.0, abs=1e-10)
        assert metrics["r2"] == pytest.approx(1.0, abs=1e-10)

    def test_classification_metrics(self):
        y_true = np.array([0, 1, 1, 0, 1])
        y_pred = np.array([0.1, 0.9, 0.8, 0.2, 0.7])
        metrics = compute_metrics(y_true, y_pred, "binary_classification")
        assert "auroc" in metrics
        assert "accuracy" in metrics
        assert metrics["auroc"] > 0.5

    def test_handles_nan(self):
        y_true = np.array([1.0, np.nan, 3.0])
        y_pred = np.array([1.1, 2.0, 2.9])
        metrics = compute_metrics(y_true, y_pred, "regression")
        assert "rmse" in metrics

    def test_empty_input(self):
        y_true = np.array([np.nan])
        y_pred = np.array([np.nan])
        metrics = compute_metrics(y_true, y_pred, "regression")
        assert metrics == {}


# ============= Test JSON Serializer =============

class TestJsonSerializer:
    def test_numpy_int(self):
        assert _json_serializer(np.int64(42)) == 42

    def test_numpy_float(self):
        assert _json_serializer(np.float64(3.14)) == pytest.approx(3.14)

    def test_numpy_array(self):
        arr = np.array([1, 2, 3])
        result = _json_serializer(arr)
        assert result == [1, 2, 3]


# ============= Test CV Aggregation =============

class TestAggregateCV:
    def test_basic_aggregation(self):
        fold_results = [
            {"fold": 1, "rmse": 0.5, "r2": 0.9},
            {"fold": 2, "rmse": 0.6, "r2": 0.85},
            {"fold": 3, "rmse": 0.55, "r2": 0.88},
        ]
        agg = _aggregate_cv_results(fold_results)
        assert "rmse" in agg
        assert "r2" in agg
        assert agg["rmse"]["mean"] == pytest.approx(0.55, abs=0.01)
        assert agg["rmse"]["std"] > 0


# ============= Test Save Final Results =============

class TestSaveFinalResults:
    def test_basic_save(self, tmp_path):
        import chemprop_utils
        orig_output = chemprop_utils.OUTPUT_DIR
        chemprop_utils.OUTPUT_DIR = str(tmp_path)

        save_final_results(
            {"rmse": 0.5, "r2": 0.9},
            {"model": "model.pt"},
            {"model": "Trained MPNN model"},
        )

        path = tmp_path / "final_results.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["status"] == "completed"
        assert data["summary"]["rmse"] == 0.5

        chemprop_utils.OUTPUT_DIR = orig_output


# ============= Test Quick Setup =============

class TestQuickSetup:
    def test_setup_creates_dirs(self, tmp_path):
        work = str(tmp_path / "work")
        out = str(tmp_path / "output")
        inp = str(tmp_path / "input")
        os.makedirs(inp, exist_ok=True)

        quick_setup(input_dir=inp, output_dir=out, work_dir=work)
        assert os.path.isdir(work)
        assert os.path.isdir(out)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
