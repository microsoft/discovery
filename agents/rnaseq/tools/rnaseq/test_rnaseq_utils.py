#!/usr/bin/env python3
"""Unit tests for rnaseq_utils.py — tests all major functions with synthetic data."""

import os
import sys
import json
import tempfile
import shutil
import pytest
import numpy as np
import pandas as pd

# Add parent directory to path for import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rnaseq_utils import (
    filter_low_count_genes,
    deseq2_normalize,
    log2_transform,
    run_pca,
    run_de_analysis,
    build_coexpression_network,
    elastic_net_classify,
    xgboost_rank,
    assemble_handoff_artifact,
    parse_phenotype_labels,
    quick_setup,
    save_final_results,
)


# ============= FIXTURES =============

def make_synthetic_counts(n_genes=500, n_disease=20, n_control=15, seed=42):
    """Create a synthetic RNA-seq count matrix with known DE genes."""
    np.random.seed(seed)
    n_samples = n_disease + n_control
    
    disease_ids = [f"D{i:03d}" for i in range(n_disease)]
    control_ids = [f"C{i:03d}" for i in range(n_control)]
    sample_ids = disease_ids + control_ids
    gene_ids = [f"GENE_{i:04d}" for i in range(n_genes)]
    
    # Base expression (Poisson-like)
    base_means = np.random.exponential(50, size=n_genes)
    counts = np.zeros((n_genes, n_samples))
    
    for j in range(n_samples):
        lib_factor = np.random.uniform(0.8, 1.2)
        counts[:, j] = np.random.poisson(base_means * lib_factor)
    
    # Inject DE for first 50 genes (20 up, 30 down)
    for i in range(20):  # Up in disease
        fold_change = np.random.uniform(2, 4)
        counts[i, :n_disease] = np.random.poisson(base_means[i] * fold_change, size=n_disease)
    
    for i in range(20, 50):  # Down in disease
        fold_change = np.random.uniform(0.2, 0.5)
        counts[i, :n_disease] = np.random.poisson(base_means[i] * fold_change, size=n_disease)
    
    df = pd.DataFrame(counts, index=gene_ids, columns=sample_ids).astype(float)
    
    labels = pd.Series(
        ['disease'] * n_disease + ['control'] * n_control,
        index=sample_ids
    )
    
    return df, labels, disease_ids, control_ids


@pytest.fixture
def synthetic_data():
    """Fixture providing synthetic count data."""
    return make_synthetic_counts()


@pytest.fixture
def tmp_dirs():
    """Create temporary input/output/work directories."""
    tmpdir = tempfile.mkdtemp()
    input_dir = os.path.join(tmpdir, 'input')
    output_dir = os.path.join(tmpdir, 'output')
    work_dir = os.path.join(tmpdir, 'workdir')
    for d in [input_dir, output_dir, work_dir]:
        os.makedirs(d)
    yield input_dir, output_dir, work_dir
    shutil.rmtree(tmpdir)


# ============= TESTS =============

class TestSetup:
    def test_quick_setup(self, tmp_dirs):
        input_dir, output_dir, work_dir = tmp_dirs
        quick_setup(input_dir=input_dir, output_dir=output_dir, work_dir=work_dir)
        assert os.path.exists(work_dir)
        assert os.path.exists(output_dir)

    def test_save_final_results(self, tmp_dirs):
        input_dir, output_dir, work_dir = tmp_dirs
        quick_setup(input_dir=input_dir, output_dir=output_dir, work_dir=work_dir)
        save_final_results({'test': 'value'}, {'file.csv': '/output/file.csv'})
        result_path = os.path.join(output_dir, 'final_results.json')
        assert os.path.exists(result_path)
        with open(result_path) as f:
            data = json.load(f)
        assert data['status'] == 'completed'
        assert data['summary']['test'] == 'value'


class TestQCNormalization:
    def test_filter_low_count_genes(self, synthetic_data):
        counts, labels, _, _ = synthetic_data
        filtered = filter_low_count_genes(counts, min_count=10, min_samples_frac=0.2)
        assert filtered.shape[0] <= counts.shape[0]
        assert filtered.shape[0] > 0
        assert filtered.shape[1] == counts.shape[1]

    def test_deseq2_normalize(self, synthetic_data):
        counts, labels, _, _ = synthetic_data
        normalized, size_factors = deseq2_normalize(counts)
        assert normalized.shape == counts.shape
        assert len(size_factors) == counts.shape[1]
        assert all(size_factors > 0)
        # Normalized library sizes should be more uniform
        raw_lib = counts.sum(axis=0)
        norm_lib = normalized.sum(axis=0)
        assert norm_lib.std() / norm_lib.mean() < raw_lib.std() / raw_lib.mean() + 0.1

    def test_log2_transform(self, synthetic_data):
        counts, _, _, _ = synthetic_data
        log_counts = log2_transform(counts, pseudocount=1.0)
        assert log_counts.shape == counts.shape
        assert (log_counts >= 0).all().all()
        # log2(0 + 1) = 0
        assert np.isclose(log_counts.min().min(), 0, atol=0.01) or log_counts.min().min() > 0

    def test_pca(self, synthetic_data):
        counts, labels, _, _ = synthetic_data
        normalized, _ = deseq2_normalize(counts)
        log_expr = log2_transform(normalized)
        pca_result = run_pca(log_expr, n_components=5)
        
        assert 'scores' in pca_result
        assert 'loadings' in pca_result
        assert 'variance_explained' in pca_result
        assert pca_result['scores'].shape[0] == counts.shape[1]
        assert pca_result['scores'].shape[1] == 5
        assert sum(pca_result['variance_explained']) <= 1.0 + 1e-6


class TestPhenotypeLabels:
    def test_parse_labels(self):
        pheno = pd.DataFrame({
            'source_name_ch1': ['psoriasis lesional skin', 'psoriasis lesional skin',
                                'normal skin', 'normal skin'],
        }, index=['S1', 'S2', 'S3', 'S4'])
        
        labels = parse_phenotype_labels(pheno, disease_keywords=['psoriasis', 'lesional'],
                                         control_keywords=['normal'])
        assert (labels == 'disease').sum() == 2
        assert (labels == 'control').sum() == 2


class TestDifferentialExpression:
    def test_ttest_de(self, synthetic_data):
        counts, labels, _, _ = synthetic_data
        normalized, _ = deseq2_normalize(counts)
        log_expr = log2_transform(normalized)
        
        de = run_de_analysis(log_expr, labels, method='ttest',
                            fdr_threshold=0.05, log2fc_threshold=0.5)
        
        assert 'log2FC' in de.columns
        assert 'fdr' in de.columns
        assert 'significant' in de.columns
        assert de['significant'].sum() > 0  # Should detect some injected DE genes
        
        # Check that known DE genes are enriched in significant set
        known_de = [f"GENE_{i:04d}" for i in range(50)]
        sig_genes = de[de['significant']].index.tolist()
        overlap = set(sig_genes) & set(known_de)
        assert len(overlap) > 5, f"Only {len(overlap)} of 50 known DE genes detected"

    def test_limma_voom_de(self, synthetic_data):
        counts, labels, _, _ = synthetic_data
        normalized, _ = deseq2_normalize(counts)
        log_expr = log2_transform(normalized)
        
        de = run_de_analysis(log_expr, labels, method='limma_voom',
                            fdr_threshold=0.05, log2fc_threshold=0.5,
                            raw_counts=counts)
        
        assert 'log2FC' in de.columns
        assert 'sigma2_moderated' in de.columns
        assert de['significant'].sum() > 0


class TestWGCNA:
    def test_build_network(self, synthetic_data):
        counts, labels, _, _ = synthetic_data
        normalized, _ = deseq2_normalize(counts)
        log_expr = log2_transform(normalized)
        
        result = build_coexpression_network(
            log_expr, n_top_var_genes=300,
            min_module_size=10, merge_threshold=0.25
        )
        
        assert 'modules' in result
        assert 'module_eigengenes' in result
        assert 'hub_genes' in result
        assert result['n_modules'] >= 1
        assert len(result['modules']) > 0

    def test_hub_genes(self, synthetic_data):
        counts, labels, _, _ = synthetic_data
        normalized, _ = deseq2_normalize(counts)
        log_expr = log2_transform(normalized)
        
        result = build_coexpression_network(
            log_expr, n_top_var_genes=300,
            min_module_size=10
        )
        
        for mod, hubs in result['hub_genes'].items():
            assert len(hubs) > 0
            assert all(isinstance(h, tuple) and len(h) == 2 for h in hubs)


class TestMachineLearning:
    def test_elastic_net(self, synthetic_data):
        counts, labels, _, _ = synthetic_data
        normalized, _ = deseq2_normalize(counts)
        log_expr = log2_transform(normalized)
        
        result = elastic_net_classify(log_expr, labels, alpha=0.5,
                                      n_cv=3, n_top_genes=300)
        
        assert 'nonzero_genes' in result
        assert 'cv_accuracy_mean' in result
        assert result['cv_accuracy_mean'] > 0.5  # Better than chance
        assert result['n_nonzero'] > 0

    def test_xgboost(self, synthetic_data):
        counts, labels, _, _ = synthetic_data
        normalized, _ = deseq2_normalize(counts)
        log_expr = log2_transform(normalized)
        
        result = xgboost_rank(log_expr, labels, n_estimators=50,
                              n_cv=3, n_top_genes=300)
        
        assert 'feature_importance' in result
        assert 'cv_accuracy_mean' in result
        assert result['cv_accuracy_mean'] > 0.5
        assert len(result['feature_importance']) > 0


class TestHandoff:
    def test_assemble_artifact(self, synthetic_data, tmp_dirs):
        input_dir, output_dir, work_dir = tmp_dirs
        quick_setup(input_dir=input_dir, output_dir=output_dir, work_dir=work_dir)
        
        counts, labels, _, _ = synthetic_data
        normalized, _ = deseq2_normalize(counts)
        log_expr = log2_transform(normalized)
        
        # Minimal pipeline
        de = run_de_analysis(log_expr, labels, method='ttest',
                            fdr_threshold=0.05, log2fc_threshold=0.5)
        wgcna = build_coexpression_network(log_expr, n_top_var_genes=200,
                                            min_module_size=10)
        en = elastic_net_classify(log_expr, labels, n_cv=3, n_top_genes=200)
        xgb = xgboost_rank(log_expr, labels, n_estimators=30, n_cv=3,
                           n_top_genes=200)
        
        artifact = assemble_handoff_artifact(
            de_results=de,
            wgcna_result=wgcna,
            elastic_net_result=en,
            xgboost_result=xgb,
            phenotype_summary={'condition': 'disease_vs_control', 'n_disease': 20, 'n_control': 15},
            dataset_info={'accession': 'synthetic', 'platform': 'test'},
            output_path=os.path.join(output_dir, 'handoff_artifact.json')
        )
        
        assert 'ranked_degs' in artifact
        assert 'coexpression_modules' in artifact
        assert 'model_feature_importance' in artifact
        assert len(artifact['ranked_degs']) > 0
        
        # Check file was written
        assert os.path.exists(os.path.join(output_dir, 'handoff_artifact.json'))


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
