#!/usr/bin/env python3
"""Unit tests for nucleotide_tf_utils.py -- run with pytest.

Tests cover DNA utilities, FASTA I/O, similarity analysis, clustering,
and dimensionality reduction. Model-dependent tests are skipped when
torch/transformers are not available (run those inside the container).
"""
import pytest
import os
import sys
import json
import tempfile
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from nucleotide_tf_utils import (
    validate_dna, reverse_complement, gc_content, chunk_sequence,
    parse_fasta, write_fasta, sequence_stats,
    compute_similarity_matrix, find_similar_sequences,
    cluster_sequences, reduce_dimensions,
    save_final_results, quick_setup
)


# ============= DNA VALIDATION =============
class TestValidateDNA:
    def test_valid_acgt(self):
        assert validate_dna("ACGTACGT") is True

    def test_valid_with_n(self):
        assert validate_dna("ACGTNACGT") is True

    def test_reject_n_when_strict(self):
        assert validate_dna("ACGTNACGT", allow_n=False) is False

    def test_invalid_chars(self):
        assert validate_dna("ACGTXYZ") is False

    def test_empty_string(self):
        assert validate_dna("") is False

    def test_none(self):
        assert validate_dna(None) is False

    def test_lowercase_accepted(self):
        assert validate_dna("acgtacgt") is True

    def test_mixed_case(self):
        assert validate_dna("AcGtNn") is True

    def test_protein_sequence_rejected(self):
        assert validate_dna("MVLSPADKTNVKAAWGKVGAHAGEYGAEAL") is False


# ============= REVERSE COMPLEMENT =============
class TestReverseComplement:
    def test_palindrome(self):
        assert reverse_complement("ACGT") == "ACGT"

    def test_non_palindrome(self):
        assert reverse_complement("AACG") == "CGTT"

    def test_with_n(self):
        assert reverse_complement("ANCG") == "CGNT"

    def test_single_base(self):
        assert reverse_complement("A") == "T"
        assert reverse_complement("C") == "G"

    def test_homopolymer(self):
        assert reverse_complement("AAAA") == "TTTT"

    def test_double_reverse_complement(self):
        seq = "ATCGATCG"
        assert reverse_complement(reverse_complement(seq)) == seq


# ============= GC CONTENT =============
class TestGCContent:
    def test_all_gc(self):
        assert gc_content("GCGCGC") == 1.0

    def test_all_at(self):
        assert gc_content("ATATAT") == 0.0

    def test_half(self):
        assert abs(gc_content("ACGT") - 0.5) < 1e-10

    def test_empty(self):
        assert gc_content("") == 0.0

    def test_n_ignored(self):
        # N should be excluded from both numerator and denominator
        assert abs(gc_content("GCNN") - 1.0) < 1e-10

    def test_all_n(self):
        assert gc_content("NNNN") == 0.0


# ============= CHUNK SEQUENCE =============
class TestChunkSequence:
    def test_short_no_chunking(self):
        seq = "ACGTAC"
        chunks = chunk_sequence(seq, chunk_size=12)
        assert len(chunks) == 1
        assert chunks[0] == seq

    def test_long_produces_multiple(self):
        seq = "A" * 12000
        chunks = chunk_sequence(seq, chunk_size=5994, overlap=600)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 5994

    def test_full_coverage(self):
        seq = "ACGT" * 3000  # 12000 bp
        chunks = chunk_sequence(seq, chunk_size=5994, overlap=600)
        # First chunk starts at beginning
        assert chunks[0][:4] == "ACGT"
        # Last chunk ends at end
        assert seq.endswith(chunks[-1])

    def test_overlap_exists(self):
        seq = "ABCDEF" * 2000  # 12000 chars
        chunks = chunk_sequence(seq, chunk_size=6000, overlap=600)
        if len(chunks) >= 2:
            # End of chunk 0 should overlap with start of chunk 1
            tail = chunks[0][-600:]
            head = chunks[1][:600:]
            assert tail == head

    def test_divisible_by_six(self):
        seq = "A" * 12000
        chunks = chunk_sequence(seq, chunk_size=5999, overlap=601)
        # chunk_size should be rounded down to multiple of 6
        for chunk in chunks[:-1]:  # last chunk can be shorter
            assert len(chunk) % 6 == 0 or len(chunk) == len(chunks[-1])


# ============= FASTA I/O =============
class TestFASTA:
    def test_parse_basic(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.fasta', delete=False) as f:
            f.write(">seq1 test sequence\nACGTACGT\n>seq2\nGGGGAAAA\n")
            path = f.name
        try:
            records = parse_fasta(path)
            assert len(records) == 2
            assert records[0]['id'] == 'seq1'
            assert records[0]['sequence'] == 'ACGTACGT'
            assert records[0]['description'] == 'test sequence'
            assert records[1]['id'] == 'seq2'
            assert records[1]['sequence'] == 'GGGGAAAA'
        finally:
            os.unlink(path)

    def test_parse_multiline_sequence(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.fasta', delete=False) as f:
            f.write(">seq1\nACGT\nACGT\nACGT\n")
            path = f.name
        try:
            records = parse_fasta(path)
            assert len(records) == 1
            assert records[0]['sequence'] == 'ACGTACGTACGT'
        finally:
            os.unlink(path)

    def test_roundtrip(self):
        records = [
            {'id': 'test1', 'description': 'first', 'sequence': 'ACGT' * 25},
            {'id': 'test2', 'description': 'second', 'sequence': 'GGCC' * 10}
        ]
        with tempfile.NamedTemporaryFile(suffix='.fasta', delete=False) as f:
            path = f.name
        try:
            write_fasta(records, path)
            parsed = parse_fasta(path)
            assert len(parsed) == 2
            assert parsed[0]['sequence'] == records[0]['sequence']
            assert parsed[1]['sequence'] == records[1]['sequence']
        finally:
            os.unlink(path)

    def test_parse_missing_file(self):
        with pytest.raises(FileNotFoundError):
            parse_fasta("nonexistent.fasta")

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.fasta', delete=False) as f:
            f.write("")
            path = f.name
        try:
            records = parse_fasta(path)
            assert len(records) == 0
        finally:
            os.unlink(path)


# ============= SEQUENCE STATS =============
class TestSequenceStats:
    def test_basic(self):
        stats = sequence_stats("ACGTACGT")
        assert stats['length'] == 8
        assert abs(stats['gc_content'] - 0.5) < 1e-10
        assert stats['n_count'] == 0
        assert stats['base_counts']['A'] == 2
        assert stats['base_counts']['C'] == 2

    def test_with_n(self):
        stats = sequence_stats("ACGTNNN")
        assert stats['n_count'] == 3
        assert abs(stats['n_fraction'] - 3 / 7) < 1e-10

    def test_estimated_tokens(self):
        # 12 bases = 2 6-mers + CLS = 3 tokens
        stats = sequence_stats("ACGTACGTACGT")
        assert stats['estimated_tokens'] == 3  # 12//6 + 0 + 1 = 3

    def test_non_multiple_of_six(self):
        # 7 bases = 1 6-mer + 1 leftover + CLS
        stats = sequence_stats("ACGTACG")
        assert stats['estimated_tokens'] == 3  # 7//6 + 1 + 1 = 3


# ============= SIMILARITY MATRIX =============
class TestSimilarityMatrix:
    def test_cosine_identical(self):
        embeddings = np.array([[1.0, 0.0], [1.0, 0.0]])
        sim = compute_similarity_matrix(embeddings, metric='cosine')
        assert abs(sim[0, 1] - 1.0) < 1e-6

    def test_cosine_orthogonal(self):
        embeddings = np.array([[1.0, 0.0], [0.0, 1.0]])
        sim = compute_similarity_matrix(embeddings, metric='cosine')
        assert abs(sim[0, 1]) < 1e-6

    def test_cosine_opposite(self):
        embeddings = np.array([[1.0, 0.0], [-1.0, 0.0]])
        sim = compute_similarity_matrix(embeddings, metric='cosine')
        assert abs(sim[0, 1] - (-1.0)) < 1e-6

    def test_diagonal_is_one(self):
        embeddings = np.random.randn(5, 10)
        sim = compute_similarity_matrix(embeddings, metric='cosine')
        np.testing.assert_allclose(np.diag(sim), 1.0, atol=1e-6)

    def test_euclidean(self):
        embeddings = np.array([[0.0, 0.0], [1.0, 0.0]])
        sim = compute_similarity_matrix(embeddings, metric='euclidean')
        assert sim[0, 0] > sim[0, 1]

    def test_unknown_metric_raises(self):
        embeddings = np.array([[1.0, 0.0]])
        with pytest.raises(ValueError, match="Unknown metric"):
            compute_similarity_matrix(embeddings, metric='unknown')


# ============= FIND SIMILAR =============
class TestFindSimilar:
    def test_finds_most_similar(self):
        query = np.array([1.0, 0.0, 0.0])
        refs = np.array([
            [1.0, 0.0, 0.0],   # identical
            [0.0, 1.0, 0.0],   # orthogonal
            [0.9, 0.1, 0.0],   # similar
        ])
        results = find_similar_sequences(query, refs, top_k=2)
        assert len(results) == 2
        assert results[0]['index'] == 0
        assert results[0]['similarity'] > results[1]['similarity']

    def test_with_labels(self):
        query = np.array([1.0, 0.0])
        refs = np.array([[1.0, 0.0], [0.0, 1.0]])
        labels = ['seq_a', 'seq_b']
        results = find_similar_sequences(query, refs, labels=labels, top_k=2)
        assert results[0]['label'] == 'seq_a'

    def test_top_k_limits_results(self):
        query = np.array([1.0, 0.0])
        refs = np.random.randn(20, 2)
        results = find_similar_sequences(query, refs, top_k=3)
        assert len(results) == 3


# ============= CLUSTERING =============
class TestClustering:
    def test_two_clear_clusters(self):
        np.random.seed(42)
        # Use large multi-dimensional separation so StandardScaler can't dilute it
        c1 = np.random.randn(15, 5) * 0.5 + np.array([10, 10, 10, 10, 10])
        c2 = np.random.randn(15, 5) * 0.5 + np.array([-10, -10, -10, -10, -10])
        embeddings = np.vstack([c1, c2])

        result = cluster_sequences(embeddings, n_clusters=2)
        assert result['n_clusters'] == 2
        assert len(result['labels']) == 30
        assert result['silhouette_score'] > 0.5

    def test_auto_determine_clusters(self):
        np.random.seed(42)
        c1 = np.random.randn(15, 5) + np.array([10, 0, 0, 0, 0])
        c2 = np.random.randn(15, 5) + np.array([-10, 0, 0, 0, 0])
        embeddings = np.vstack([c1, c2])

        result = cluster_sequences(embeddings)
        assert result['n_clusters'] >= 2

    def test_single_sequence(self):
        embeddings = np.array([[1.0, 2.0, 3.0]])
        result = cluster_sequences(embeddings)
        assert result['n_clusters'] == 1
        assert result['labels'] == [0]

    def test_agglomerative(self):
        np.random.seed(42)
        c1 = np.random.randn(10, 5) + 5
        c2 = np.random.randn(10, 5) - 5
        embeddings = np.vstack([c1, c2])

        result = cluster_sequences(embeddings, n_clusters=2, method='agglomerative')
        assert result['n_clusters'] == 2

    def test_cluster_sizes_sum(self):
        np.random.seed(42)
        embeddings = np.random.randn(20, 5)
        result = cluster_sequences(embeddings, n_clusters=3)
        total = sum(result['cluster_sizes'].values())
        assert total == 20


# ============= DIMENSIONALITY REDUCTION =============
class TestReduceDimensions:
    def test_pca_output_shape(self):
        np.random.seed(42)
        embeddings = np.random.randn(20, 50)
        reduced, meta = reduce_dimensions(embeddings, n_components=2, method='pca')
        assert reduced.shape == (20, 2)
        assert meta['method'] == 'PCA'
        assert 'explained_variance_ratio' in meta

    def test_pca_3d(self):
        np.random.seed(42)
        embeddings = np.random.randn(20, 50)
        reduced, meta = reduce_dimensions(embeddings, n_components=3, method='pca')
        assert reduced.shape == (20, 3)

    def test_tsne(self):
        np.random.seed(42)
        embeddings = np.random.randn(20, 50)
        reduced, meta = reduce_dimensions(embeddings, n_components=2, method='tsne')
        assert reduced.shape == (20, 2)
        assert meta['method'] == 't-SNE'

    def test_unknown_method_raises(self):
        embeddings = np.random.randn(10, 5)
        with pytest.raises(ValueError, match="Unknown method"):
            reduce_dimensions(embeddings, method='umap')


# ============= SAVE FINAL RESULTS =============
class TestSaveFinalResults:
    def test_basic_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import nucleotide_tf_utils as utils
            old_output = utils.OUTPUT_DIR
            utils.OUTPUT_DIR = tmpdir
            try:
                save_final_results(
                    results={'n_sequences': 5, 'mean_gc': 0.45},
                    output_files={'embeddings': '/output/embeddings.npy'},
                    file_descriptions={'embeddings': 'Sequence embeddings'}
                )
                path = os.path.join(tmpdir, 'final_results.json')
                assert os.path.exists(path)
                with open(path) as f:
                    data = json.load(f)
                assert data['status'] == 'completed'
                assert data['summary']['n_sequences'] == 5
            finally:
                utils.OUTPUT_DIR = old_output

    def test_numpy_serialization(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import nucleotide_tf_utils as utils
            old_output = utils.OUTPUT_DIR
            utils.OUTPUT_DIR = tmpdir
            try:
                save_final_results(
                    results={
                        'array': np.array([1.0, 2.0, 3.0]),
                        'int': np.int64(42),
                        'float': np.float32(3.14),
                        'bool': np.bool_(True)
                    }
                )
                path = os.path.join(tmpdir, 'final_results.json')
                with open(path) as f:
                    data = json.load(f)
                assert data['summary']['array'] == [1.0, 2.0, 3.0]
                assert data['summary']['int'] == 42
            finally:
                utils.OUTPUT_DIR = old_output


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
