#!/usr/bin/env python3
"""Nucleotide Transformer v2 utilities for Discovery platform workflows.

Provides DNA sequence embedding extraction, masked nucleotide prediction,
sequence similarity analysis, and batch processing using InstaDeep's
Nucleotide Transformer v2 (500M multi-species) foundation model.

Reference:
  Dalla-Torre et al., "The Nucleotide Transformer: Building and Evaluating
  Robust Foundation Models for Human Genomics", Nature Methods, 2024.
  https://www.nature.com/articles/s41592-024-02523-z
"""
import os
import sys
import glob
import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union

import numpy as np

# ============= CONSTANTS =============
INPUT_DIR = "/input"
OUTPUT_DIR = "/output"
WORK_DIR = "/workdir"
SCRATCH_DIR = "/tmp/nt_scratch"
DEFAULT_MODEL = "InstaDeepAI/nucleotide-transformer-v2-500m-multi-species"
MODEL_CACHE_DIR = "/app/model_cache"
MAX_TOKEN_LENGTH = 2048
NUCLEOTIDES = set("ACGTN")
COMPLEMENT = {"A": "T", "T": "A", "C": "G", "G": "C", "N": "N"}


# ============= SETUP FUNCTIONS =============
def quick_setup(input_dir='/input', output_dir='/output', work_dir='/workdir'):
    """Initialize logging, create directories, copy input files.

    ALL THREE parameters should be passed explicitly in every script.
    """
    global INPUT_DIR, OUTPUT_DIR, WORK_DIR
    INPUT_DIR, OUTPUT_DIR, WORK_DIR = input_dir, output_dir, work_dir

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(SCRATCH_DIR, exist_ok=True)
    os.chdir(WORK_DIR)
    _copy_input_files()
    logging.info(f"Working directory: {WORK_DIR}")
    logging.info(f"Files: {os.listdir('.')}")


def _copy_input_files():
    """Copy input files to working directory (with same-directory guard)."""
    if os.path.realpath(INPUT_DIR) == os.path.realpath(WORK_DIR):
        return
    if os.path.exists(INPUT_DIR):
        for f in glob.glob(os.path.join(INPUT_DIR, '*')):
            if os.path.isfile(f):
                shutil.copy(f, WORK_DIR)


def copy_outputs():
    """Copy output files to output directory (with same-directory guard)."""
    if os.path.realpath(WORK_DIR) == os.path.realpath(OUTPUT_DIR):
        return
    patterns = ['*.json', '*.csv', '*.png', '*.svg', '*.npy', '*.npz',
                '*.fasta', '*.fa', '*.log', '*.txt', '*.html']
    for pattern in patterns:
        for f in glob.glob(pattern):
            shutil.copy(f, OUTPUT_DIR)
    logging.info("Outputs copied to /output")


def quick_finish():
    """Copy output files to output directory."""
    copy_outputs()


def save_final_results(results: Dict, output_files: Dict = None,
                       file_descriptions: Dict = None, status: str = "completed"):
    """Save final results to JSON file (MANDATORY for every script).

    Args:
        results: Summary dict with key metrics
        output_files: Dict mapping name -> file path
        file_descriptions: Dict mapping name -> human description
        status: Status string (default 'completed')
    """
    final_data = {"status": status, "summary": results}
    if output_files:
        final_data["output_files"] = output_files
    if file_descriptions:
        final_data["file_descriptions"] = file_descriptions

    def _convert(obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, np.bool_):
            return bool(obj)
        return obj

    path = os.path.join(OUTPUT_DIR, 'final_results.json')
    with open(path, 'w') as f:
        json.dump(final_data, f, indent=2, default=_convert)
    logging.info(f"Saved final_results.json to {path}")


# ============= DNA SEQUENCE UTILITIES =============
def validate_dna(sequence: str, allow_n: bool = True) -> bool:
    """Validate that a string is a valid DNA sequence.

    Args:
        sequence: DNA sequence string
        allow_n: If True, allow N (unknown) nucleotides

    Returns:
        True if valid DNA sequence
    """
    if not sequence or not isinstance(sequence, str):
        return False
    valid = NUCLEOTIDES if allow_n else NUCLEOTIDES - {"N"}
    return all(c in valid for c in sequence.upper())


def reverse_complement(sequence: str) -> str:
    """Return the reverse complement of a DNA sequence.

    Args:
        sequence: DNA sequence string

    Returns:
        Reverse complement string
    """
    return "".join(COMPLEMENT.get(c, "N") for c in reversed(sequence.upper()))


def gc_content(sequence: str) -> float:
    """Calculate GC content of a DNA sequence.

    Args:
        sequence: DNA sequence string

    Returns:
        GC content as fraction (0.0 to 1.0)
    """
    seq = sequence.upper()
    if not seq:
        return 0.0
    gc = sum(1 for c in seq if c in "GC")
    total = sum(1 for c in seq if c in "ACGT")
    return gc / total if total > 0 else 0.0


def chunk_sequence(sequence: str, chunk_size: int = 5994,
                   overlap: int = 600) -> List[str]:
    """Split a long DNA sequence into overlapping chunks.

    The NT v2 model accepts max 2048 tokens. With 6-mer tokenization, each
    token covers 6 nucleotides, so 2047 tokens (plus CLS) = 12,282 nt max.
    Default chunk_size=5994 (999 6-mers) provides a safe margin.

    Args:
        sequence: DNA sequence string
        chunk_size: Max nucleotides per chunk (rounded down to multiple of 6)
        overlap: Overlapping nucleotides between chunks (rounded to multiple of 6)

    Returns:
        List of sequence chunks
    """
    if len(sequence) <= chunk_size:
        return [sequence]

    chunk_size = (chunk_size // 6) * 6
    overlap = (overlap // 6) * 6

    chunks = []
    start = 0
    while start < len(sequence):
        end = min(start + chunk_size, len(sequence))
        chunks.append(sequence[start:end])
        if end >= len(sequence):
            break
        start += chunk_size - overlap
    return chunks


def parse_fasta(fasta_path: str) -> List[Dict[str, str]]:
    """Parse a FASTA file into a list of sequence records.

    Args:
        fasta_path: Path to FASTA file

    Returns:
        List of dicts with 'id', 'description', and 'sequence' keys
    """
    records = []
    current_id = None
    current_desc = ""
    current_seq = []

    with open(fasta_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('>'):
                if current_id is not None:
                    records.append({
                        'id': current_id,
                        'description': current_desc,
                        'sequence': ''.join(current_seq)
                    })
                parts = line[1:].split(None, 1)
                current_id = parts[0] if parts else ''
                current_desc = parts[1] if len(parts) > 1 else ''
                current_seq = []
            else:
                current_seq.append(line.upper())

    if current_id is not None:
        records.append({
            'id': current_id,
            'description': current_desc,
            'sequence': ''.join(current_seq)
        })

    logging.info(f"Parsed {len(records)} sequences from {fasta_path}")
    return records


def write_fasta(records: List[Dict[str, str]], output_path: str,
                line_width: int = 80):
    """Write sequence records to a FASTA file.

    Args:
        records: List of dicts with 'id' and 'sequence' keys
        output_path: Output file path
        line_width: Characters per line for sequence wrapping
    """
    with open(output_path, 'w') as f:
        for rec in records:
            desc = rec.get('description', '')
            header = f">{rec['id']} {desc}".strip()
            f.write(header + '\n')
            seq = rec['sequence']
            for i in range(0, len(seq), line_width):
                f.write(seq[i:i + line_width] + '\n')
    logging.info(f"Wrote {len(records)} sequences to {output_path}")


def sequence_stats(sequence: str) -> Dict[str, Any]:
    """Compute basic statistics for a DNA sequence.

    Args:
        sequence: DNA sequence string

    Returns:
        Dict with length, gc_content, base_counts, n_count, estimated_tokens
    """
    seq = sequence.upper()
    counts = {base: seq.count(base) for base in "ACGTN"}
    return {
        'length': len(seq),
        'gc_content': gc_content(seq),
        'base_counts': counts,
        'n_count': counts.get('N', 0),
        'n_fraction': counts.get('N', 0) / len(seq) if seq else 0.0,
        'estimated_tokens': len(seq) // 6 + (1 if len(seq) % 6 else 0) + 1
    }


# ============= MODEL LOADING =============
def load_model(model_name: str = None, device: str = 'auto',
               half_precision: bool = False) -> Tuple[Any, Any]:
    """Load the Nucleotide Transformer model and tokenizer.

    Loads from HuggingFace cache (pre-downloaded in container) or downloads
    on first use. Set HF_HOME=/app/model_cache to use the container cache.

    Args:
        model_name: HuggingFace model name or local path.
                    Defaults to NT v2 500M multi-species.
        device: 'auto' (detect GPU), 'cpu', or 'cuda'
        half_precision: Load in float16 (saves ~50% memory, GPU only)

    Returns:
        Tuple of (model, tokenizer)
    """
    import torch
    from transformers import AutoTokenizer, AutoModelForMaskedLM

    if model_name is None:
        model_name = DEFAULT_MODEL

    if device == 'auto':
        device = 'cuda' if torch.cuda.is_available() else 'cpu'

    logging.info(f"Loading model: {model_name} on {device}")

    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)

    kwargs = {'trust_remote_code': True}
    if half_precision and device != 'cpu':
        kwargs['torch_dtype'] = torch.float16

    model = AutoModelForMaskedLM.from_pretrained(model_name, **kwargs)
    model = model.to(device)
    model.eval()

    n_params = sum(p.numel() for p in model.parameters())
    logging.info(f"Model loaded: {n_params:,} parameters on {device}")
    return model, tokenizer


def get_device(model: Any) -> str:
    """Get the device a model is on.

    Args:
        model: PyTorch model

    Returns:
        Device string ('cpu' or 'cuda:N')
    """
    return str(next(model.parameters()).device)


# ============= EMBEDDING EXTRACTION =============
def extract_embeddings(sequences: Union[str, List[str]], model: Any, tokenizer: Any,
                       pooling: str = 'mean', max_length: int = None,
                       layer: int = -1) -> np.ndarray:
    """Extract embeddings from DNA sequences using the Nucleotide Transformer.

    Args:
        sequences: Single DNA sequence string or list of sequences
        model: Loaded NT model (from load_model)
        tokenizer: Loaded NT tokenizer (from load_model)
        pooling: 'mean' (default, recommended), 'cls', or 'max'
        max_length: Max token length (defaults to model's max)
        layer: Hidden layer index (-1 = last, -2 = second-to-last, etc.)

    Returns:
        numpy array of shape (n_sequences, embedding_dim)
        Embedding dim is 1024 for the 500M model.
    """
    import torch

    if isinstance(sequences, str):
        sequences = [sequences]

    if max_length is None:
        max_length = tokenizer.model_max_length

    device = get_device(model)

    tokens_ids = tokenizer.batch_encode_plus(
        sequences,
        return_tensors="pt",
        padding="max_length",
        max_length=max_length,
        truncation=True
    )["input_ids"].to(device)

    attention_mask = (tokens_ids != tokenizer.pad_token_id).to(device)

    with torch.no_grad():
        outputs = model(
            tokens_ids,
            attention_mask=attention_mask,
            encoder_attention_mask=attention_mask,
            output_hidden_states=True
        )

    hidden_states = outputs['hidden_states'][layer]

    if pooling == 'cls':
        embeddings = hidden_states[:, 0, :]
    elif pooling == 'max':
        mask = attention_mask.unsqueeze(-1).float()
        masked_hidden = hidden_states * mask + (-1e9) * (1 - mask)
        embeddings = masked_hidden.max(dim=1).values
    else:  # mean pooling
        mask = attention_mask.unsqueeze(-1).float()
        embeddings = (hidden_states * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)

    return embeddings.cpu().numpy()


def batch_extract_embeddings(sequences: List[str], model: Any, tokenizer: Any,
                              batch_size: int = 8, pooling: str = 'mean',
                              max_length: int = None, layer: int = -1,
                              show_progress: bool = True) -> np.ndarray:
    """Extract embeddings in batches for memory efficiency.

    Args:
        sequences: List of DNA sequences
        model: Loaded NT model
        tokenizer: Loaded NT tokenizer
        batch_size: Sequences per batch (reduce if OOM)
        pooling: 'mean', 'cls', or 'max'
        max_length: Max token length
        layer: Hidden layer index
        show_progress: Log progress per batch

    Returns:
        numpy array of shape (n_sequences, embedding_dim)
    """
    all_embeddings = []
    n_batches = (len(sequences) + batch_size - 1) // batch_size

    for i in range(0, len(sequences), batch_size):
        batch = sequences[i:i + batch_size]
        batch_num = i // batch_size + 1

        if show_progress:
            logging.info(f"Batch {batch_num}/{n_batches} ({len(batch)} sequences)")

        emb = extract_embeddings(
            batch, model, tokenizer,
            pooling=pooling, max_length=max_length, layer=layer
        )
        all_embeddings.append(emb)

    return np.concatenate(all_embeddings, axis=0)


# ============= MASKED LANGUAGE MODELING =============
def predict_masked(sequence: str, model: Any, tokenizer: Any,
                   mask_positions: List[int] = None, top_k: int = 5,
                   mask_fraction: float = 0.15) -> Dict[str, Any]:
    """Predict masked nucleotides in a DNA sequence.

    Masks tokens and uses the model to predict what should be there.
    Can be used for variant effect prediction (mask a SNP site and see
    what the model predicts) or sequence quality assessment.

    Args:
        sequence: DNA sequence string
        model: Loaded NT model
        tokenizer: Loaded NT tokenizer
        mask_positions: Nucleotide positions to mask (0-indexed).
                       If None, randomly masks mask_fraction of tokens.
        top_k: Top predictions to return per masked position
        mask_fraction: Fraction of tokens to mask (used if mask_positions is None)

    Returns:
        Dict with 'predictions' (list of per-position results),
        'n_masked_tokens', and 'pseudo_perplexity'
    """
    import torch

    device = get_device(model)

    tokens = tokenizer.encode(sequence, return_tensors="pt").to(device)
    original_tokens = tokens.clone()
    n_tokens = tokens.shape[1]

    if mask_positions is not None:
        # Convert nucleotide positions to token positions
        # 6-mer tokenization: position p -> token p // 6 + 1 (CLS at 0)
        token_positions = sorted(set(
            p // 6 + 1 for p in mask_positions
            if 0 <= p // 6 + 1 < n_tokens
        ))
    else:
        n_mask = max(1, int((n_tokens - 1) * mask_fraction))
        token_positions = sorted(
            np.random.choice(range(1, n_tokens), size=min(n_mask, n_tokens - 1),
                             replace=False).tolist()
        )

    masked_tokens = tokens.clone()
    mask_token_id = tokenizer.mask_token_id
    for pos in token_positions:
        masked_tokens[0, pos] = mask_token_id

    with torch.no_grad():
        outputs = model(masked_tokens)

    logits = outputs.logits

    predictions = []
    total_log_prob = 0.0
    for pos in token_positions:
        position_logits = logits[0, pos]
        probs = torch.softmax(position_logits, dim=-1)
        top_probs, top_indices = probs.topk(top_k)

        original_token = tokenizer.decode([original_tokens[0, pos].item()])

        preds = []
        for prob, idx in zip(top_probs.cpu().numpy(), top_indices.cpu().numpy()):
            token_str = tokenizer.decode([idx])
            preds.append({
                'token': token_str,
                'probability': float(prob),
                'is_original': token_str.strip() == original_token.strip()
            })

        predictions.append({
            'token_position': int(pos),
            'original_token': original_token.strip(),
            'top_predictions': preds
        })

        orig_prob = probs[original_tokens[0, pos]].item()
        total_log_prob += np.log(max(orig_prob, 1e-10))

    perplexity = float(np.exp(-total_log_prob / max(len(token_positions), 1)))

    return {
        'predictions': predictions,
        'n_masked_tokens': len(token_positions),
        'pseudo_perplexity': perplexity,
    }


# ============= SIMILARITY & ANALYSIS =============
def compute_similarity_matrix(embeddings: np.ndarray,
                              metric: str = 'cosine') -> np.ndarray:
    """Compute pairwise similarity matrix from embeddings.

    Args:
        embeddings: Array of shape (n_sequences, embedding_dim)
        metric: 'cosine' (default) or 'euclidean'

    Returns:
        Similarity matrix of shape (n_sequences, n_sequences), values 0-1
    """
    if metric == 'cosine':
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        normalized = embeddings / norms
        return np.dot(normalized, normalized.T)
    elif metric == 'euclidean':
        from scipy.spatial.distance import pdist, squareform
        distances = squareform(pdist(embeddings, metric='euclidean'))
        return 1.0 / (1.0 + distances)
    else:
        raise ValueError(f"Unknown metric: {metric}. Use 'cosine' or 'euclidean'.")


def find_similar_sequences(query_embedding: np.ndarray,
                           reference_embeddings: np.ndarray,
                           labels: List[str] = None,
                           top_k: int = 5) -> List[Dict]:
    """Find the most similar sequences to a query by cosine similarity.

    Args:
        query_embedding: Shape (embedding_dim,)
        reference_embeddings: Shape (n_ref, embedding_dim)
        labels: Optional labels for reference sequences
        top_k: Number of top matches

    Returns:
        List of dicts with 'index', 'similarity', and optionally 'label'
    """
    query_norm = query_embedding / (np.linalg.norm(query_embedding) + 1e-10)
    ref_norms = reference_embeddings / (
        np.linalg.norm(reference_embeddings, axis=1, keepdims=True) + 1e-10
    )
    similarities = np.dot(ref_norms, query_norm)

    top_indices = np.argsort(similarities)[::-1][:top_k]

    results = []
    for idx in top_indices:
        result = {'index': int(idx), 'similarity': float(similarities[idx])}
        if labels is not None:
            result['label'] = labels[idx]
        results.append(result)
    return results


def cluster_sequences(embeddings: np.ndarray, n_clusters: int = None,
                      method: str = 'kmeans',
                      random_state: int = 42) -> Dict[str, Any]:
    """Cluster sequences based on their embeddings.

    Args:
        embeddings: Shape (n_sequences, embedding_dim)
        n_clusters: Number of clusters (auto-determined if None)
        method: 'kmeans' or 'agglomerative'
        random_state: Random seed

    Returns:
        Dict with 'labels', 'n_clusters', 'silhouette_score', 'cluster_sizes'
    """
    from sklearn.cluster import KMeans, AgglomerativeClustering
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler()
    scaled = scaler.fit_transform(embeddings)

    if n_clusters is None:
        max_k = min(10, len(embeddings) - 1)
        if max_k < 2:
            return {
                'labels': [0] * len(embeddings),
                'n_clusters': 1,
                'silhouette_score': 0.0,
                'cluster_sizes': {0: len(embeddings)}
            }
        best_score, best_k = -1, 2
        for k in range(2, max_k + 1):
            km = KMeans(n_clusters=k, random_state=random_state, n_init=10)
            labs = km.fit_predict(scaled)
            score = silhouette_score(scaled, labs)
            if score > best_score:
                best_score, best_k = score, k
        n_clusters = best_k

    if method == 'kmeans':
        clusterer = KMeans(n_clusters=n_clusters, random_state=random_state, n_init=10)
    elif method == 'agglomerative':
        clusterer = AgglomerativeClustering(n_clusters=n_clusters)
    else:
        raise ValueError(f"Unknown method: {method}")

    labels = clusterer.fit_predict(scaled)
    score = silhouette_score(scaled, labels) if n_clusters > 1 else 0.0

    sizes = {}
    for lab in labels:
        sizes[int(lab)] = sizes.get(int(lab), 0) + 1

    return {
        'labels': labels.tolist(),
        'n_clusters': int(n_clusters),
        'silhouette_score': float(score),
        'cluster_sizes': sizes
    }


def reduce_dimensions(embeddings: np.ndarray, n_components: int = 2,
                      method: str = 'pca') -> Tuple[np.ndarray, Dict]:
    """Reduce embedding dimensionality for visualization.

    Args:
        embeddings: Shape (n_sequences, embedding_dim)
        n_components: Target dimensions (2 or 3)
        method: 'pca' or 'tsne'

    Returns:
        Tuple of (reduced array shape (n, n_components), metadata dict)
    """
    if method == 'pca':
        from sklearn.decomposition import PCA
        reducer = PCA(n_components=n_components)
        reduced = reducer.fit_transform(embeddings)
        metadata = {
            'method': 'PCA',
            'explained_variance_ratio': reducer.explained_variance_ratio_.tolist(),
            'total_variance_explained': float(sum(reducer.explained_variance_ratio_))
        }
    elif method == 'tsne':
        from sklearn.manifold import TSNE
        perp = min(30, max(5, len(embeddings) - 1))
        reducer = TSNE(n_components=n_components, random_state=42, perplexity=perp)
        reduced = reducer.fit_transform(embeddings)
        metadata = {
            'method': 't-SNE',
            'kl_divergence': float(reducer.kl_divergence_)
        }
    else:
        raise ValueError(f"Unknown method: {method}. Use 'pca' or 'tsne'.")
    return reduced, metadata


# ============= VISUALIZATION =============
def plot_embedding_scatter(embeddings_2d: np.ndarray, labels: List[str] = None,
                           cluster_labels: List[int] = None,
                           output_file: str = 'embedding_scatter.png',
                           title: str = 'DNA Sequence Embeddings',
                           figsize: Tuple[int, int] = (10, 8)) -> str:
    """Create 2D scatter plot of sequence embeddings.

    Args:
        embeddings_2d: Reduced embeddings shape (n, 2)
        labels: Sequence labels for annotation
        cluster_labels: Cluster IDs for coloring
        output_file: Output filename
        title: Plot title
        figsize: Figure size tuple

    Returns:
        Path to saved plot
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=figsize)

    if cluster_labels is not None:
        scatter = ax.scatter(embeddings_2d[:, 0], embeddings_2d[:, 1],
                             c=cluster_labels, cmap='tab10', alpha=0.7, s=60)
        plt.colorbar(scatter, label='Cluster')
    else:
        ax.scatter(embeddings_2d[:, 0], embeddings_2d[:, 1], alpha=0.7, s=60)

    if labels is not None:
        for i, label in enumerate(labels):
            ax.annotate(label, (embeddings_2d[i, 0], embeddings_2d[i, 1]),
                        fontsize=7, alpha=0.8,
                        xytext=(5, 5), textcoords='offset points')

    ax.set_xlabel('Component 1')
    ax.set_ylabel('Component 2')
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    output_path = os.path.join(OUTPUT_DIR, output_file)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved plot: {output_path}")
    return output_path


def plot_similarity_matrix(similarity: np.ndarray, labels: List[str] = None,
                           output_file: str = 'similarity_matrix.png',
                           title: str = 'Sequence Similarity Matrix',
                           figsize: Tuple[int, int] = (10, 8)) -> str:
    """Create heatmap of pairwise sequence similarities.

    Args:
        similarity: Similarity matrix shape (n, n)
        labels: Sequence labels for axes
        output_file: Output filename
        title: Plot title
        figsize: Figure size tuple

    Returns:
        Path to saved plot
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import seaborn as sns

    fig, ax = plt.subplots(figsize=figsize)
    sns.heatmap(similarity, annot=len(similarity) <= 15, fmt='.2f',
                cmap='YlOrRd', vmin=0, vmax=1, ax=ax,
                xticklabels=labels if labels else False,
                yticklabels=labels if labels else False)
    ax.set_title(title)
    plt.tight_layout()
    output_path = os.path.join(OUTPUT_DIR, output_file)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved plot: {output_path}")
    return output_path


def plot_token_probabilities(predictions: List[Dict],
                             output_file: str = 'token_probs.png',
                             title: str = 'Masked Token Predictions',
                             figsize: Tuple[int, int] = (14, 5)) -> str:
    """Visualize masked token prediction probabilities.

    Args:
        predictions: List from predict_masked()['predictions']
        output_file: Output filename
        title: Plot title
        figsize: Figure size tuple

    Returns:
        Path to saved plot
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    n_show = min(len(predictions), 6)
    fig, axes = plt.subplots(1, n_show, figsize=figsize, squeeze=False)

    for i, pred in enumerate(predictions[:n_show]):
        ax = axes[0, i]
        tokens = [p['token'][:10] for p in pred['top_predictions']]
        probs = [p['probability'] for p in pred['top_predictions']]
        colors = ['#2ecc71' if p.get('is_original') else '#3498db'
                  for p in pred['top_predictions']]

        ax.barh(range(len(tokens)), probs, color=colors)
        ax.set_yticks(range(len(tokens)))
        ax.set_yticklabels(tokens, fontsize=8)
        ax.set_xlabel('Probability')
        ax.set_title(f'Pos {pred["token_position"]}', fontsize=9)
        ax.invert_yaxis()

    fig.suptitle(title)
    plt.tight_layout()
    output_path = os.path.join(OUTPUT_DIR, output_file)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved plot: {output_path}")
    return output_path


def plot_sequence_stats(sequences: List[str], labels: List[str] = None,
                        output_file: str = 'sequence_stats.png') -> str:
    """Plot summary statistics for a collection of DNA sequences.

    Args:
        sequences: List of DNA sequences
        labels: Optional sequence labels
        output_file: Output filename

    Returns:
        Path to saved plot
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    stats = [sequence_stats(seq) for seq in sequences]
    lengths = [s['length'] for s in stats]
    gc_vals = [s['gc_content'] for s in stats]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    axes[0].hist(lengths, bins=min(30, len(lengths)),
                 color='steelblue', alpha=0.7, edgecolor='black')
    axes[0].set_xlabel('Sequence Length (bp)')
    axes[0].set_ylabel('Count')
    axes[0].set_title('Sequence Length Distribution')
    axes[0].axvline(np.median(lengths), color='red', linestyle='--',
                    label=f'Median: {np.median(lengths):.0f}')
    axes[0].legend()

    axes[1].hist(gc_vals, bins=min(30, len(gc_vals)),
                 color='seagreen', alpha=0.7, edgecolor='black')
    axes[1].set_xlabel('GC Content')
    axes[1].set_ylabel('Count')
    axes[1].set_title('GC Content Distribution')
    axes[1].axvline(np.mean(gc_vals), color='red', linestyle='--',
                    label=f'Mean: {np.mean(gc_vals):.2f}')
    axes[1].legend()

    plt.tight_layout()
    output_path = os.path.join(OUTPUT_DIR, output_file)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved plot: {output_path}")
    return output_path


# ============= CLEANUP =============
def nt_cleanup(deep: bool = False):
    """Clean up resources between calculations.

    Args:
        deep: If True, also clear GPU cache and scratch files
    """
    try:
        if deep:
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    logging.info("GPU memory cache cleared")
            except ImportError:
                pass
            _clear_scratch_files()
            logging.info("Deep cleanup completed")
    except Exception as e:
        logging.warning(f"Cleanup warning: {e}")


def _clear_scratch_files():
    """Remove scratch files."""
    cleared = 0
    try:
        for entry in os.scandir(SCRATCH_DIR):
            if entry.is_file():
                try:
                    os.remove(entry.path)
                    cleared += 1
                except OSError:
                    pass
    except FileNotFoundError:
        pass
    if cleared:
        logging.info(f"Cleared {cleared} scratch files")
