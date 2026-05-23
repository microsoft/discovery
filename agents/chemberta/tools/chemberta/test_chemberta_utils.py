#!/usr/bin/env python3
"""Unit tests for chemberta_utils.py.

Tests are designed to run inside the Docker container with all dependencies.
Uses pytest. Run with: python3 -m pytest test_chemberta_utils.py -v
"""
import json
import os
import sys
import tempfile
import shutil
import pytest
import numpy as np

# Ensure /app is on path
sys.path.insert(0, '/app')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from chemberta_utils import (
    quick_setup, quick_finish, save_final_results,
    validate_smiles, canonicalize_smiles, augment_smiles,
    batch_validate_smiles, smiles_stats,
    load_model, extract_embeddings,
    compute_similarity_matrix, find_similar_molecules,
    cluster_molecules, reduce_dimensions,
    chemberta_cleanup,
)


# ============= FIXTURES =============
@pytest.fixture
def temp_dirs():
    """Create temporary directories for testing."""
    input_dir = tempfile.mkdtemp()
    output_dir = tempfile.mkdtemp()
    work_dir = tempfile.mkdtemp()
    yield input_dir, output_dir, work_dir
    shutil.rmtree(input_dir, ignore_errors=True)
    shutil.rmtree(output_dir, ignore_errors=True)
    shutil.rmtree(work_dir, ignore_errors=True)


@pytest.fixture
def sample_smiles():
    """Common drug-like SMILES for testing."""
    return [
        "CC(=O)Oc1ccccc1C(=O)O",           # Aspirin
        "CC(=O)NC1=CC=C(O)C=C1",            # Acetaminophen
        "CC12CCC3C(CCC4CC(=O)CCC34C)C1CCC2O",  # Testosterone
        "c1ccc2[nH]ccc2c1",                  # Indole
        "CCO",                                # Ethanol
        "C1CCCCC1",                           # Cyclohexane
        "c1ccccc1",                           # Benzene
        "CC(C)CC1=CC=C(C=C1)C(C)C(=O)O",    # Ibuprofen
    ]


@pytest.fixture
def model_and_tokenizer():
    """Load model and tokenizer (shared across tests for speed)."""
    model, tokenizer = load_model()
    return model, tokenizer


# ============= SETUP/TEARDOWN TESTS =============
class TestSetup:
    def test_quick_setup(self, temp_dirs):
        input_dir, output_dir, work_dir = temp_dirs
        quick_setup(input_dir=input_dir, output_dir=output_dir, work_dir=work_dir)
        assert os.path.isdir(output_dir)
        assert os.path.isdir(work_dir)

    def test_save_final_results(self, temp_dirs):
        _, output_dir, work_dir = temp_dirs
        os.chdir(work_dir)
        from chemberta_utils import OUTPUT_DIR
        import chemberta_utils
        chemberta_utils.OUTPUT_DIR = output_dir

        results = {"accuracy": 0.95, "n_molecules": 100}
        save_final_results(results, output_files={"model": "/output/model.pt"})

        path = os.path.join(output_dir, 'final_results.json')
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert data["status"] == "completed"
        assert data["summary"]["accuracy"] == 0.95

    def test_save_final_results_numpy_types(self, temp_dirs):
        _, output_dir, _ = temp_dirs
        import chemberta_utils
        chemberta_utils.OUTPUT_DIR = output_dir

        results = {
            "mean": np.float64(0.5),
            "count": np.int64(42),
            "array": np.array([1, 2, 3]),
        }
        save_final_results(results)
        path = os.path.join(output_dir, 'final_results.json')
        with open(path) as f:
            data = json.load(f)
        assert data["summary"]["mean"] == 0.5
        assert data["summary"]["count"] == 42
        assert data["summary"]["array"] == [1, 2, 3]


# ============= SMILES UTILITY TESTS =============
class TestSmilesUtils:
    def test_validate_smiles_valid(self):
        assert validate_smiles("CCO") is True
        assert validate_smiles("c1ccccc1") is True
        assert validate_smiles("CC(=O)Oc1ccccc1C(=O)O") is True

    def test_validate_smiles_invalid(self):
        assert validate_smiles("") is False
        assert validate_smiles("not_a_smiles") is False
        assert validate_smiles(None) is False
        assert validate_smiles(123) is False

    def test_canonicalize_smiles(self):
        canon = canonicalize_smiles("C(O)C")
        assert canon is not None
        assert canon == "CCO"  # Canonical form of ethanol

    def test_canonicalize_smiles_invalid(self):
        assert canonicalize_smiles("invalid") is None

    def test_augment_smiles(self):
        aug = augment_smiles("c1ccccc1", n_augmentations=5)
        assert len(aug) >= 1  # At least canonical
        # All augmented SMILES should represent the same molecule
        from rdkit import Chem
        canon = Chem.MolToSmiles(Chem.MolFromSmiles("c1ccccc1"))
        for smi in aug:
            mol = Chem.MolFromSmiles(smi)
            assert mol is not None
            assert Chem.MolToSmiles(mol) == canon

    def test_augment_smiles_invalid(self):
        aug = augment_smiles("invalid_smiles")
        assert aug == ["invalid_smiles"]

    def test_batch_validate_smiles(self):
        result = batch_validate_smiles(["CCO", "invalid", "c1ccccc1", ""])
        assert result["total"] == 4
        assert result["valid"] == 2
        assert result["invalid"] == 2
        assert len(result["invalid_entries"]) == 2

    def test_smiles_stats(self, sample_smiles):
        stats = smiles_stats(sample_smiles)
        assert stats["n_molecules"] == len(sample_smiles)
        assert stats["n_invalid"] == 0
        assert stats["molecular_weight"]["mean"] > 0
        assert stats["n_atoms"]["mean"] > 0


# ============= MODEL LOADING TESTS =============
class TestModelLoading:
    def test_load_model(self, model_and_tokenizer):
        model, tokenizer = model_and_tokenizer
        assert model is not None
        assert tokenizer is not None
        # Check model dimensions
        assert model.config.hidden_size > 0

    def test_tokenizer_encodes_smiles(self, model_and_tokenizer):
        _, tokenizer = model_and_tokenizer
        encoded = tokenizer("CCO", return_tensors='pt')
        assert 'input_ids' in encoded
        assert 'attention_mask' in encoded
        assert encoded['input_ids'].shape[0] == 1

    def test_model_cache_exists(self):
        """Verify pre-cached model exists in container."""
        assert os.path.exists('/app/model_cache'), \
            "Pre-cached model not found at /app/model_cache"


# ============= EMBEDDING TESTS =============
class TestEmbeddings:
    def test_extract_embeddings_mean(self, model_and_tokenizer, sample_smiles):
        model, tokenizer = model_and_tokenizer
        emb = extract_embeddings(sample_smiles[:3], model, tokenizer, pooling='mean')
        assert emb.shape == (3, model.config.hidden_size)
        assert not np.isnan(emb).any()

    def test_extract_embeddings_cls(self, model_and_tokenizer, sample_smiles):
        model, tokenizer = model_and_tokenizer
        emb = extract_embeddings(sample_smiles[:3], model, tokenizer, pooling='cls')
        assert emb.shape == (3, model.config.hidden_size)

    def test_extract_embeddings_max(self, model_and_tokenizer, sample_smiles):
        model, tokenizer = model_and_tokenizer
        emb = extract_embeddings(sample_smiles[:3], model, tokenizer, pooling='max')
        assert emb.shape == (3, model.config.hidden_size)

    def test_embeddings_differ_across_molecules(self, model_and_tokenizer):
        model, tokenizer = model_and_tokenizer
        emb = extract_embeddings(["CCO", "c1ccccc1"], model, tokenizer)
        # Different molecules should have different embeddings
        assert not np.allclose(emb[0], emb[1])

    def test_embeddings_batch_consistency(self, model_and_tokenizer, sample_smiles):
        model, tokenizer = model_and_tokenizer
        # Results should be the same regardless of batch size
        emb1 = extract_embeddings(sample_smiles[:4], model, tokenizer, batch_size=2)
        emb2 = extract_embeddings(sample_smiles[:4], model, tokenizer, batch_size=4)
        np.testing.assert_allclose(emb1, emb2, atol=1e-5)


# ============= SIMILARITY & CLUSTERING TESTS =============
class TestSimilarityClustering:
    def test_similarity_matrix_cosine(self):
        emb = np.random.randn(5, 10)
        sim = compute_similarity_matrix(emb, metric='cosine')
        assert sim.shape == (5, 5)
        # Diagonal should be 1 (self-similarity)
        np.testing.assert_allclose(np.diag(sim), 1.0, atol=1e-6)

    def test_similarity_matrix_euclidean(self):
        emb = np.random.randn(5, 10)
        sim = compute_similarity_matrix(emb, metric='euclidean')
        assert sim.shape == (5, 5)
        assert np.all(sim >= 0)

    def test_find_similar_molecules(self):
        np.random.seed(42)
        db = np.random.randn(10, 8)
        query = db[0]  # Most similar to itself
        labels = [f"mol_{i}" for i in range(10)]
        results = find_similar_molecules(query, db, labels, top_k=3)
        assert len(results) == 3
        assert results[0]["similarity"] > results[1]["similarity"]

    def test_cluster_molecules_kmeans(self):
        np.random.seed(42)
        # Create 3 distinct clusters
        c1 = np.random.randn(10, 8) + np.array([5, 0, 0, 0, 0, 0, 0, 0])
        c2 = np.random.randn(10, 8) + np.array([0, 5, 0, 0, 0, 0, 0, 0])
        c3 = np.random.randn(10, 8) + np.array([0, 0, 5, 0, 0, 0, 0, 0])
        emb = np.vstack([c1, c2, c3])

        result = cluster_molecules(emb, n_clusters=3)
        assert result["n_clusters"] == 3
        assert len(result["labels"]) == 30
        assert result["silhouette_score"] > 0

    def test_cluster_molecules_auto_k(self):
        np.random.seed(42)
        c1 = np.random.randn(15, 8) + 5
        c2 = np.random.randn(15, 8) - 5
        emb = np.vstack([c1, c2])

        result = cluster_molecules(emb, n_clusters=None)
        assert result["n_clusters"] >= 2
        assert "silhouette_score" in result

    def test_reduce_dimensions_pca(self):
        emb = np.random.randn(20, 50)
        reduced, meta = reduce_dimensions(emb, n_components=2, method='pca')
        assert reduced.shape == (20, 2)
        assert meta["method"] == "PCA"
        assert len(meta["explained_variance_ratio"]) == 2

    def test_reduce_dimensions_tsne(self):
        emb = np.random.randn(20, 50)
        reduced, meta = reduce_dimensions(emb, n_components=2, method='tsne')
        assert reduced.shape == (20, 2)
        assert meta["method"] == "t-SNE"


# ============= INTEGRATION TESTS =============
class TestIntegration:
    def test_embedding_to_clustering_pipeline(self, model_and_tokenizer, sample_smiles):
        """Test full pipeline: SMILES → embeddings → clustering → visualization."""
        model, tokenizer = model_and_tokenizer

        # Extract embeddings
        emb = extract_embeddings(sample_smiles, model, tokenizer)
        assert emb.shape[0] == len(sample_smiles)

        # Compute similarity
        sim = compute_similarity_matrix(emb)
        assert sim.shape == (len(sample_smiles), len(sample_smiles))

        # Cluster
        result = cluster_molecules(emb, n_clusters=2)
        assert result["n_clusters"] == 2
        assert len(result["labels"]) == len(sample_smiles)

        # Dimensionality reduction
        reduced, meta = reduce_dimensions(emb, method='pca')
        assert reduced.shape == (len(sample_smiles), 2)

    def test_smiles_stats_with_embeddings(self, model_and_tokenizer, sample_smiles):
        """Test SMILES stats and embedding extraction together."""
        model, tokenizer = model_and_tokenizer

        stats = smiles_stats(sample_smiles)
        assert stats["n_molecules"] == len(sample_smiles)

        emb = extract_embeddings(sample_smiles, model, tokenizer)
        assert emb.shape[0] == stats["n_molecules"]


# ============= CLEANUP TESTS =============
class TestCleanup:
    def test_cleanup_basic(self):
        chemberta_cleanup(deep=False)  # Should not raise

    def test_cleanup_deep(self):
        chemberta_cleanup(deep=True)  # Should not raise


# ============= RUN TESTS =============
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
