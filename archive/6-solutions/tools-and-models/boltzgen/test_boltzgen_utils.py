#!/usr/bin/env python3
"""Unit tests for boltzgen_utils.py — run with pytest.

Tests are designed to work WITHOUT the boltzgen CLI or GPU installed,
so they validate YAML handling, command building, metric parsing, and
serialization helpers using fixtures and mocks.
"""
import pytest
import os
import sys
import json
import tempfile
import shutil
from unittest.mock import patch, MagicMock

# Insert path so we can import boltzgen_utils
sys.path.insert(0, os.path.dirname(__file__))
import boltzgen_utils as utils


# ============= FIXTURES =============

@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    d = tempfile.mkdtemp(prefix='boltzgen_test_')
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def sample_metrics_csv(temp_dir):
    """Create a sample metrics CSV file matching BoltzGen output format."""
    import pandas as pd

    data = {
        'design_id': [f'design_{i}' for i in range(10)],
        'filter_rmsd_design': [1.5, 2.0, 0.8, 3.1, 1.2, 2.5, 0.9, 1.8, 2.2, 1.1],
        'iptm_refolded': [0.7, 0.5, 0.9, 0.3, 0.8, 0.4, 0.85, 0.6, 0.45, 0.75],
        'plddt_refolded': [75, 60, 90, 45, 82, 55, 88, 68, 50, 80],
        'delta_sasa_refolded': [800, 600, 1200, 400, 950, 500, 1100, 700, 450, 900],
        'plip_hbonds_refolded': [5, 3, 8, 1, 6, 2, 7, 4, 1, 5],
        'design_ALA': [0.15, 0.22, 0.10, 0.30, 0.12, 0.25, 0.11, 0.18, 0.28, 0.13],
        'design_GLY': [0.08, 0.12, 0.06, 0.15, 0.07, 0.13, 0.05, 0.09, 0.14, 0.07],
    }
    df = pd.DataFrame(data)

    # Create output directory structure like BoltzGen
    final_dir = os.path.join(temp_dir, 'final_ranked_designs')
    os.makedirs(final_dir, exist_ok=True)
    csv_path = os.path.join(final_dir, 'all_designs_metrics.csv')
    df.to_csv(csv_path, index=False)

    return temp_dir


@pytest.fixture
def sample_output_dir(temp_dir):
    """Create a full sample BoltzGen output directory structure."""
    # Intermediate designs
    inter_dir = os.path.join(temp_dir, 'intermediate_designs')
    os.makedirs(inter_dir)
    for i in range(5):
        with open(os.path.join(inter_dir, f'design_{i}.cif'), 'w') as f:
            f.write(f'# Mock CIF for design_{i}\n')

    # Inverse-folded metrics
    if_dir = os.path.join(temp_dir, 'intermediate_designs_inverse_folded')
    os.makedirs(if_dir)
    import pandas as pd
    pd.DataFrame({
        'design_id': [f'design_{i}' for i in range(5)],
        'filter_rmsd_design': [1.0, 1.5, 2.0, 0.8, 1.2],
        'iptm_refolded': [0.8, 0.7, 0.5, 0.9, 0.75],
    }).to_csv(os.path.join(if_dir, 'aggregate_metrics_analyze.csv'), index=False)

    # Final ranked designs
    final_dir = os.path.join(temp_dir, 'final_ranked_designs')
    os.makedirs(final_dir)
    final_sub = os.path.join(final_dir, 'final_3_designs')
    os.makedirs(final_sub)
    for i in range(3):
        with open(os.path.join(final_sub, f'design_{i}.cif'), 'w') as f:
            f.write(f'# Final design {i}\n')

    pd.DataFrame({
        'design_id': ['design_0', 'design_3', 'design_4'],
        'filter_rmsd_design': [1.0, 0.8, 1.2],
        'iptm_refolded': [0.8, 0.9, 0.75],
    }).to_csv(os.path.join(final_dir, 'final_designs_metrics_3.csv'), index=False)

    pd.DataFrame({
        'design_id': [f'design_{i}' for i in range(5)],
        'filter_rmsd_design': [1.0, 1.5, 2.0, 0.8, 1.2],
    }).to_csv(os.path.join(final_dir, 'all_designs_metrics.csv'), index=False)

    return temp_dir


# ============= TEST CLASSES =============

class TestSetup:
    """Tests for setup and teardown functions."""

    def test_save_final_results(self, temp_dir):
        """Test that final results are saved as valid JSON."""
        utils.OUTPUT_DIR = temp_dir
        utils.save_final_results(
            results={'metric': 42, 'description': 'test run'},
            output_files={'plot': 'plot.png'},
            file_descriptions={'plot': 'A test plot'},
            status='completed',
        )
        out_path = os.path.join(temp_dir, 'final_results.json')
        assert os.path.exists(out_path)
        with open(out_path) as f:
            data = json.load(f)
        assert data['status'] == 'completed'
        assert data['summary']['metric'] == 42
        assert data['output_files']['plot'] == 'plot.png'

    def test_save_final_results_numpy_serialization(self, temp_dir):
        """Test that numpy types are serialized correctly."""
        import numpy as np
        utils.OUTPUT_DIR = temp_dir
        utils.save_final_results(
            results={
                'int_val': np.int64(42),
                'float_val': np.float64(3.14),
                'array_val': np.array([1, 2, 3]),
                'bool_val': np.bool_(True),
            },
            status='completed',
        )
        out_path = os.path.join(temp_dir, 'final_results.json')
        with open(out_path) as f:
            data = json.load(f)
        assert data['summary']['int_val'] == 42
        assert abs(data['summary']['float_val'] - 3.14) < 0.001
        assert data['summary']['array_val'] == [1, 2, 3]
        assert data['summary']['bool_val'] is True

    def test_copy_input_files_same_dir(self, temp_dir):
        """Test that copy_input_files handles same-directory gracefully."""
        utils.INPUT_DIR = temp_dir
        utils.WORK_DIR = temp_dir
        # Should not raise
        utils.copy_input_files()

    def test_copy_input_files_different_dirs(self, temp_dir):
        """Test that input files are copied to work dir."""
        input_dir = os.path.join(temp_dir, 'input')
        work_dir = os.path.join(temp_dir, 'work')
        os.makedirs(input_dir)
        os.makedirs(work_dir)

        with open(os.path.join(input_dir, 'test.yaml'), 'w') as f:
            f.write('entities: []\n')

        utils.INPUT_DIR = input_dir
        utils.WORK_DIR = work_dir
        utils.copy_input_files()

        assert os.path.exists(os.path.join(work_dir, 'test.yaml'))


class TestDesignSpec:
    """Tests for design specification YAML handling."""

    def test_create_design_spec_basic(self, temp_dir):
        """Test creating a basic design spec."""
        utils.WORK_DIR = temp_dir
        spec_path = utils.create_design_spec(
            entities=[
                {'protein': {'id': 'B', 'sequence': '80..140'}},
                {'file': {
                    'path': 'target.cif',
                    'include': [{'chain': {'id': 'A'}}],
                }},
            ],
            output_path=os.path.join(temp_dir, 'spec.yaml'),
        )
        assert os.path.exists(spec_path)

        # Verify YAML content
        spec = utils.load_design_spec(spec_path)
        assert 'entities' in spec
        assert len(spec['entities']) == 2
        assert spec['entities'][0]['protein']['id'] == 'B'
        assert spec['entities'][0]['protein']['sequence'] == '80..140'

    def test_create_design_spec_with_constraints(self, temp_dir):
        """Test creating a spec with bond constraints."""
        utils.WORK_DIR = temp_dir
        spec_path = utils.create_design_spec(
            entities=[
                {'protein': {'id': 'R', 'sequence': '3..5C6C3'}},
                {'ligand': {'id': 'Q', 'ccd': 'WHL'}},
            ],
            constraints=[
                {'bond': {'atom1': ['R', 4, 'SG'], 'atom2': ['Q', 1, 'CK']}},
            ],
            output_path=os.path.join(temp_dir, 'spec_constrained.yaml'),
        )
        spec = utils.load_design_spec(spec_path)
        assert 'constraints' in spec
        assert len(spec['constraints']) == 1

    def test_create_design_spec_peptide(self, temp_dir):
        """Test creating a peptide design spec."""
        utils.WORK_DIR = temp_dir
        spec_path = utils.create_design_spec(
            entities=[
                {'protein': {'id': 'B', 'sequence': '12..25'}},
                {'file': {
                    'path': 'target.cif',
                    'include': [{'chain': {'id': 'A'}}],
                    'binding_types': [
                        {'chain': {'id': 'A', 'binding': '50..70'}},
                    ],
                }},
            ],
            output_path=os.path.join(temp_dir, 'peptide_spec.yaml'),
        )
        spec = utils.load_design_spec(spec_path)
        assert spec['entities'][0]['protein']['sequence'] == '12..25'
        file_entity = spec['entities'][1]['file']
        assert 'binding_types' in file_entity

    def test_load_design_spec_missing_file(self, temp_dir):
        """Test that loading a non-existent spec raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            utils.load_design_spec(os.path.join(temp_dir, 'nonexistent.yaml'))

    def test_create_design_spec_default_path(self, temp_dir):
        """Test that default output path is in WORK_DIR."""
        utils.WORK_DIR = temp_dir
        spec_path = utils.create_design_spec(
            entities=[{'protein': {'id': 'A', 'sequence': '50'}}],
        )
        assert os.path.dirname(os.path.abspath(spec_path)) == os.path.abspath(temp_dir)
        assert os.path.basename(spec_path) == 'design_spec.yaml'


class TestOutputParsing:
    """Tests for pipeline output parsing."""

    def test_parse_pipeline_output_full(self, sample_output_dir):
        """Test parsing a complete output directory."""
        results = utils.parse_pipeline_output(sample_output_dir)
        assert results['n_intermediate_designs'] == 5
        assert results['n_final_designs'] == 3
        assert results['metrics'] is not None
        assert len(results['metrics']) == 5
        assert results['final_metrics'] is not None
        assert len(results['final_metrics']) == 3

    def test_parse_pipeline_output_empty(self, temp_dir):
        """Test parsing an empty output directory."""
        results = utils.parse_pipeline_output(temp_dir)
        assert results['n_intermediate_designs'] == 0
        assert results['n_final_designs'] == 0
        assert results['metrics'] is None

    def test_get_design_metrics(self, sample_metrics_csv):
        """Test getting design metrics."""
        df = utils.get_design_metrics(sample_metrics_csv)
        assert len(df) == 10
        assert 'filter_rmsd_design' in df.columns
        assert 'iptm_refolded' in df.columns

    def test_get_design_metrics_by_id(self, sample_metrics_csv):
        """Test filtering metrics by design ID."""
        df = utils.get_design_metrics(sample_metrics_csv, design_id='design_0')
        assert len(df) == 1
        assert df.iloc[0]['design_id'] == 'design_0'

    def test_get_design_metrics_missing(self, temp_dir):
        """Test that missing metrics raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            utils.get_design_metrics(temp_dir)

    def test_get_top_designs(self, sample_metrics_csv):
        """Test getting top N designs."""
        top = utils.get_top_designs(sample_metrics_csv, n=3)
        assert len(top) == 3

    def test_get_top_designs_sorted(self, sample_metrics_csv):
        """Test getting top designs sorted by specific metric."""
        top = utils.get_top_designs(
            sample_metrics_csv, n=3, sort_by='filter_rmsd_design')
        assert len(top) == 3
        # Should be sorted ascending (lower RMSD is better)
        values = top['filter_rmsd_design'].tolist()
        assert values == sorted(values)


class TestVisualization:
    """Tests for visualization functions."""

    def test_plot_design_metrics(self, sample_metrics_csv, temp_dir):
        """Test creating metrics histogram plot."""
        output_file = os.path.join(temp_dir, 'metrics.png')
        result = utils.plot_design_metrics(
            sample_metrics_csv, output_file=output_file)
        assert result is not None
        assert os.path.exists(output_file)
        assert os.path.getsize(output_file) > 100

    def test_plot_rmsd_vs_confidence(self, sample_metrics_csv, temp_dir):
        """Test creating RMSD vs confidence scatter plot."""
        output_file = os.path.join(temp_dir, 'scatter.png')
        result = utils.plot_rmsd_vs_confidence(
            sample_metrics_csv, output_file=output_file)
        assert result is not None
        assert os.path.exists(output_file)

    def test_plot_design_metrics_no_data(self, temp_dir):
        """Test that plot returns None when no metrics are available."""
        result = utils.plot_design_metrics(temp_dir)
        assert result is None


class TestConstants:
    """Tests for module constants."""

    def test_protocols_list(self):
        """Test that all expected protocols are defined."""
        assert 'protein-anything' in utils.PROTOCOLS
        assert 'peptide-anything' in utils.PROTOCOLS
        assert 'protein-small_molecule' in utils.PROTOCOLS
        assert 'antibody-anything' in utils.PROTOCOLS
        assert 'nanobody-anything' in utils.PROTOCOLS
        assert 'protein-redesign' in utils.PROTOCOLS
        assert len(utils.PROTOCOLS) == 6

    def test_pipeline_steps(self):
        """Test that all pipeline steps are defined."""
        assert 'design' in utils.PIPELINE_STEPS
        assert 'inverse_folding' in utils.PIPELINE_STEPS
        assert 'folding' in utils.PIPELINE_STEPS
        assert 'filtering' in utils.PIPELINE_STEPS
        assert len(utils.PIPELINE_STEPS) == 7


class TestCommandBuilding:
    """Tests for command construction (without executing)."""

    def test_run_design_pipeline_invalid_protocol(self, temp_dir):
        """Test that invalid protocol raises ValueError."""
        with pytest.raises(ValueError, match="Invalid protocol"):
            utils.run_design_pipeline(
                spec_path='spec.yaml',
                protocol='invalid-protocol',
            )

    def test_run_design_pipeline_invalid_step(self, temp_dir):
        """Test that invalid step raises ValueError."""
        with patch.object(utils, 'validate_design_spec', return_value={
            'valid': True, 'output_file': None, 'message': 'ok',
        }):
            with pytest.raises(ValueError, match="Invalid step"):
                utils.run_design_pipeline(
                    spec_path='spec.yaml',
                    steps=['nonexistent_step'],
                )

    def test_run_design_pipeline_auto_validates_spec(self, temp_dir):
        """Test that run_design_pipeline auto-validates the spec and rejects invalid ones."""
        bad_spec = os.path.join(temp_dir, 'bad_spec.yaml')
        with open(bad_spec, 'w') as f:
            f.write('not: valid_boltzgen_spec\n')
        with patch.object(utils, 'validate_design_spec', return_value={
            'valid': False,
            'output_file': None,
            'message': 'Missing entities section',
        }):
            with pytest.raises(ValueError, match="Invalid design spec"):
                utils.run_design_pipeline(
                    spec_path=bad_spec,
                    protocol='protein-anything',
                )


class TestCleanup:
    """Tests for cleanup functions."""

    def test_cleanup_no_error(self):
        """Test that cleanup runs without errors."""
        utils.boltzgen_cleanup(deep=False)
        utils.boltzgen_cleanup(deep=True)

    def test_clear_scratch_files(self, temp_dir):
        """Test clearing scratch files."""
        utils.SCRATCH_DIR = temp_dir
        # Create some scratch files
        for i in range(3):
            with open(os.path.join(temp_dir, f'scratch_{i}.tmp'), 'w') as f:
                f.write('test')
        utils._clear_scratch_files()
        remaining = os.listdir(temp_dir)
        assert len(remaining) == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
