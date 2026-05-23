#!/usr/bin/env python3
"""RNA-seq bioinformatics utilities library for Microsoft Discovery platform.

Provides end-to-end bulk RNA-seq analysis: GEO data ingestion, QC, normalization,
differential expression, co-expression network modules (WGCNA-style), and
machine-learning feature ranking (elastic net, XGBoost).
"""

import os
import sys
import glob
import json
import logging
import shutil
import subprocess
import traceback
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union

import numpy as np
import pandas as pd
import scipy.stats as stats
from scipy.cluster.hierarchy import linkage, fcluster, dendrogram
from scipy.spatial.distance import pdist, squareform

# Suppress warnings for cleaner logs
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

# ============= CONSTANTS =============
INPUT_DIR = "/input"
OUTPUT_DIR = "/output"
WORK_DIR = "/workdir"
SCRATCH_DIR = "/tmp/rnaseq_scratch"

# ============= SETUP FUNCTIONS =============

def quick_setup(input_dir='/input', output_dir='/output', work_dir='/workdir'):
    """Initialize logging, create directories, copy input files.

    ALL THREE parameters should be passed explicitly in every script.
    """
    global INPUT_DIR, OUTPUT_DIR, WORK_DIR
    INPUT_DIR, OUTPUT_DIR, WORK_DIR = input_dir, output_dir, work_dir

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    for d in [WORK_DIR, OUTPUT_DIR, SCRATCH_DIR]:
        os.makedirs(d, exist_ok=True)
    os.chdir(WORK_DIR)
    copy_input_files()
    logging.info(f"Working directory: {WORK_DIR}")
    logging.info(f"Input files: {os.listdir(INPUT_DIR) if os.path.exists(INPUT_DIR) else 'none'}")


def copy_input_files():
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
    patterns = ['*.out', '*.log', '*.dat', '*.png', '*.json', '*.csv',
                '*.html', '*.tsv', '*.xlsx', '*.pdf', '*.svg']
    for pattern in patterns:
        for f in glob.glob(os.path.join(WORK_DIR, pattern)):
            shutil.copy(f, OUTPUT_DIR)
    logging.info("Outputs copied to /output")


def quick_finish():
    """Copy output files to output directory."""
    copy_outputs()


def save_final_results(results: Dict, output_files: Dict = None,
                       file_descriptions: Dict = None, status: str = "completed"):
    """Save final results to JSON file (MANDATORY for every script)."""
    final_data = {"status": status, "summary": results}
    if output_files:
        final_data["output_files"] = output_files
    if file_descriptions:
        final_data["file_descriptions"] = file_descriptions
    out_path = os.path.join(OUTPUT_DIR, 'final_results.json')
    with open(out_path, 'w') as f:
        json.dump(final_data, f, indent=2, default=str)
    logging.info(f"Saved final_results.json to {out_path}")


# ============= GEO DATA LOADING =============

def download_geo_dataset(geo_accession: str, output_dir: str = None,
                         timeout: int = 600) -> Dict:
    """Download and parse a GEO dataset using GEOparse.

    Parameters
    ----------
    geo_accession : str
        GEO series accession (e.g., 'GSE54456')
    output_dir : str
        Where to save downloaded files. Defaults to WORK_DIR.
    timeout : int
        Download timeout in seconds.

    Returns
    -------
    dict with keys: 'expression_matrix', 'phenotype', 'gse' object
    """
    import GEOparse

    dl_dir = output_dir or WORK_DIR
    logging.info(f"Downloading {geo_accession} from GEO...")
    gse = GEOparse.get_GEO(geo=geo_accession, destdir=dl_dir, silent=True)
    logging.info(f"Downloaded {geo_accession}: {len(gse.gsms)} samples, "
                 f"{len(gse.gpls)} platform(s)")

    # Extract expression matrix from all GSMs
    sample_data = {}
    phenotype_rows = []

    for gsm_name, gsm in gse.gsms.items():
        # Get expression table
        table = gsm.table
        if table is not None and len(table) > 0:
            if 'VALUE' in table.columns and 'ID_REF' in table.columns:
                series = table.set_index('ID_REF')['VALUE']
                series.name = gsm_name
                sample_data[gsm_name] = series

        # Get phenotype metadata
        meta = gsm.metadata
        pheno = {'sample_id': gsm_name}
        for key, vals in meta.items():
            pheno[key] = vals[0] if len(vals) == 1 else '; '.join(vals)
        phenotype_rows.append(pheno)

    expr_matrix = pd.DataFrame(sample_data)
    if expr_matrix.empty:
        logging.warning("Expression matrix from GSMs is empty — trying supplementary files")

    phenotype_df = pd.DataFrame(phenotype_rows).set_index('sample_id')

    logging.info(f"Expression matrix: {expr_matrix.shape[0]} genes × {expr_matrix.shape[1]} samples")
    logging.info(f"Phenotype table: {phenotype_df.shape[0]} samples × {phenotype_df.shape[1]} fields")

    return {
        'expression_matrix': expr_matrix,
        'phenotype': phenotype_df,
        'gse': gse
    }


def load_expression_from_file(filepath: str, sep: str = '\t',
                               index_col: int = 0) -> pd.DataFrame:
    """Load expression matrix from a tab/comma-delimited file.

    Parameters
    ----------
    filepath : str
        Path to the expression matrix file.
    sep : str
        Delimiter (default: tab).
    index_col : int
        Column to use as index (gene IDs).

    Returns
    -------
    pd.DataFrame with genes as rows, samples as columns
    """
    df = pd.read_csv(filepath, sep=sep, index_col=index_col)
    # Ensure numeric
    df = df.apply(pd.to_numeric, errors='coerce')
    logging.info(f"Loaded expression matrix: {df.shape[0]} genes × {df.shape[1]} samples")
    return df


def parse_phenotype_labels(phenotype_df: pd.DataFrame,
                           condition_column: str = None,
                           disease_keywords: List[str] = None,
                           control_keywords: List[str] = None) -> pd.Series:
    """Parse phenotype metadata to extract disease/control labels.

    Parameters
    ----------
    phenotype_df : pd.DataFrame
        Phenotype metadata with samples as rows.
    condition_column : str
        Column name containing the condition. If None, auto-detect from
        'characteristics_ch1', 'source_name_ch1', 'title', 'description'.
    disease_keywords : list of str
        Keywords indicating disease samples (e.g., ['psoriasis', 'lesional', 'PP']).
    control_keywords : list of str
        Keywords indicating control samples (e.g., ['normal', 'control', 'healthy', 'NN']).

    Returns
    -------
    pd.Series with index=sample_id, values='disease' or 'control'
    """
    if disease_keywords is None:
        disease_keywords = ['psoriasis', 'lesional', 'disease', 'case', 'tumor', 'treated']
    if control_keywords is None:
        control_keywords = ['normal', 'control', 'healthy', 'untreated', 'uninvolved']

    # Auto-detect condition column
    candidate_cols = ['characteristics_ch1', 'source_name_ch1', 'title',
                      'description', 'phenotype', 'condition', 'group']
    if condition_column is None:
        for col in candidate_cols:
            if col in phenotype_df.columns:
                vals = phenotype_df[col].astype(str).str.lower()
                has_disease = vals.str.contains('|'.join(disease_keywords), na=False).any()
                has_control = vals.str.contains('|'.join(control_keywords), na=False).any()
                if has_disease and has_control:
                    condition_column = col
                    logging.info(f"Auto-detected condition column: '{col}'")
                    break

    if condition_column is None:
        raise ValueError("Could not auto-detect condition column. Please specify explicitly.")

    vals = phenotype_df[condition_column].astype(str).str.lower()
    labels = pd.Series(index=phenotype_df.index, dtype=str)
    labels[vals.str.contains('|'.join(disease_keywords), na=False)] = 'disease'
    labels[vals.str.contains('|'.join(control_keywords), na=False)] = 'control'

    n_disease = (labels == 'disease').sum()
    n_control = (labels == 'control').sum()
    n_unlabeled = labels.eq('').sum() + labels.isna().sum()
    logging.info(f"Labels: {n_disease} disease, {n_control} control, {n_unlabeled} unlabeled")

    return labels


# ============= QC & NORMALIZATION =============

def filter_low_count_genes(expr_matrix: pd.DataFrame,
                           min_count: float = 10,
                           min_samples_frac: float = 0.2) -> pd.DataFrame:
    """Filter genes with low counts across samples.

    Parameters
    ----------
    expr_matrix : pd.DataFrame
        Raw count matrix (genes × samples).
    min_count : float
        Minimum count threshold.
    min_samples_frac : float
        Minimum fraction of samples that must pass the threshold.

    Returns
    -------
    Filtered DataFrame
    """
    n_before = expr_matrix.shape[0]
    min_samples = int(min_samples_frac * expr_matrix.shape[1])
    keep = (expr_matrix >= min_count).sum(axis=1) >= min_samples
    filtered = expr_matrix.loc[keep]
    n_after = filtered.shape[0]
    logging.info(f"Gene filtering: {n_before} → {n_after} genes "
                 f"(removed {n_before - n_after}, min_count={min_count}, "
                 f"min_samples={min_samples})")
    return filtered


def deseq2_normalize(counts: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
    """DESeq2-style median-of-ratios normalization.

    Parameters
    ----------
    counts : pd.DataFrame
        Raw count matrix (genes × samples). Must contain non-negative integers/floats.

    Returns
    -------
    (normalized_counts, size_factors)
    """
    # Step 1: geometric mean per gene (pseudo-reference)
    log_counts = np.log(counts.replace(0, np.nan))
    geo_means = log_counts.mean(axis=1)

    # Step 2: ratios to pseudo-reference
    valid = np.isfinite(geo_means)
    ratios = counts.loc[valid].div(np.exp(geo_means[valid]), axis=0)

    # Step 3: size factors = median of ratios per sample
    size_factors = ratios.median(axis=0)
    size_factors = size_factors.replace(0, 1.0)

    # Step 4: normalize
    normalized = counts.div(size_factors, axis=1)

    logging.info(f"DESeq2 normalization: size factors range [{size_factors.min():.3f}, "
                 f"{size_factors.max():.3f}]")
    return normalized, size_factors


def log2_transform(expr_matrix: pd.DataFrame, pseudocount: float = 1.0) -> pd.DataFrame:
    """Log2-transform expression values with pseudocount.

    Parameters
    ----------
    expr_matrix : pd.DataFrame
        Expression matrix (normalized counts or raw counts).
    pseudocount : float
        Added before log (default: 1.0).

    Returns
    -------
    log2-transformed DataFrame
    """
    result = np.log2(expr_matrix + pseudocount)
    logging.info(f"Log2-transformed with pseudocount={pseudocount}")
    return result


def voom_transform(counts: pd.DataFrame, design: pd.DataFrame = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Voom transformation: log2-CPM with precision weights.

    Parameters
    ----------
    counts : pd.DataFrame
        Raw count matrix (genes × samples).
    design : pd.DataFrame
        Design matrix for the linear model. If None, intercept-only.

    Returns
    -------
    (log_cpm, weights) — both DataFrames with same shape as counts
    """
    # Library sizes
    lib_sizes = counts.sum(axis=0)

    # CPM
    cpm = counts.div(lib_sizes, axis=1) * 1e6

    # Log2-CPM
    log_cpm = np.log2(cpm + 0.5)

    # Fit linear model per gene to get residual variance
    from sklearn.linear_model import LinearRegression

    if design is None:
        design = pd.DataFrame({'intercept': 1.0}, index=counts.columns)

    X = design.values
    fitted_values = np.zeros_like(log_cpm.values)
    residual_var = np.zeros(log_cpm.shape[0])

    for i in range(log_cpm.shape[0]):
        y = log_cpm.iloc[i].values
        model = LinearRegression().fit(X, y)
        fitted_values[i] = model.predict(X)
        resid = y - fitted_values[i]
        residual_var[i] = np.var(resid, ddof=X.shape[1])

    # Mean-variance trend: fit lowess
    mean_expr = log_cpm.mean(axis=1).values
    sqrt_sd = np.sqrt(np.maximum(residual_var, 1e-10))

    from statsmodels.nonparametric.smoothers_lowess import lowess
    trend = lowess(sqrt_sd, mean_expr, frac=0.3, return_sorted=False)
    trend = np.maximum(trend, 1e-10)

    # Weights = 1 / (trend^2)
    weights_vals = 1.0 / (trend ** 2)
    weights_matrix = np.tile(weights_vals.reshape(-1, 1), (1, counts.shape[1]))
    weights = pd.DataFrame(weights_matrix, index=counts.index, columns=counts.columns)

    logging.info(f"Voom transform complete: {log_cpm.shape[0]} genes, "
                 f"weight range [{weights.values.min():.3f}, {weights.values.max():.3f}]")
    return log_cpm, weights


def run_pca(expr_matrix: pd.DataFrame, n_components: int = 10) -> Dict:
    """Run PCA on expression matrix for QC visualization.

    Parameters
    ----------
    expr_matrix : pd.DataFrame
        Log-transformed expression matrix (genes × samples).
    n_components : int
        Number of PCs to compute.

    Returns
    -------
    dict with 'scores' (samples × PCs), 'loadings' (genes × PCs),
    'variance_explained', 'cumulative_variance'
    """
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    # Transpose so samples are rows
    X = expr_matrix.T.values
    X = np.nan_to_num(X, nan=0.0)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    n_comp = min(n_components, X_scaled.shape[0], X_scaled.shape[1])
    pca = PCA(n_components=n_comp)
    scores = pca.fit_transform(X_scaled)

    scores_df = pd.DataFrame(
        scores,
        index=expr_matrix.columns,
        columns=[f'PC{i+1}' for i in range(n_comp)]
    )
    loadings_df = pd.DataFrame(
        pca.components_.T,
        index=expr_matrix.index,
        columns=[f'PC{i+1}' for i in range(n_comp)]
    )

    var_explained = pca.explained_variance_ratio_
    logging.info(f"PCA: PC1={var_explained[0]*100:.1f}%, PC2={var_explained[1]*100:.1f}%")

    return {
        'scores': scores_df,
        'loadings': loadings_df,
        'variance_explained': var_explained,
        'cumulative_variance': np.cumsum(var_explained)
    }


def plot_pca(pca_result: Dict, labels: pd.Series, output_file: str,
             title: str = "PCA of Gene Expression"):
    """Plot PCA scores colored by condition.

    Parameters
    ----------
    pca_result : dict
        Output of run_pca().
    labels : pd.Series
        Condition labels (disease/control).
    output_file : str
        Path to save the plot.
    title : str
        Plot title.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    scores = pca_result['scores']
    var_exp = pca_result['variance_explained']

    fig, ax = plt.subplots(1, 1, figsize=(8, 6))
    colors = {'disease': '#e74c3c', 'control': '#3498db'}

    for condition in ['disease', 'control']:
        mask = labels == condition
        samples = scores.index[scores.index.isin(mask.index[mask])]
        if len(samples) > 0:
            ax.scatter(scores.loc[samples, 'PC1'],
                      scores.loc[samples, 'PC2'],
                      c=colors.get(condition, '#999999'),
                      label=f"{condition} (n={len(samples)})",
                      alpha=0.7, s=40, edgecolors='white', linewidth=0.5)

    ax.set_xlabel(f"PC1 ({var_exp[0]*100:.1f}%)")
    ax.set_ylabel(f"PC2 ({var_exp[1]*100:.1f}%)")
    ax.set_title(title)
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved PCA plot: {output_file}")


# ============= DIFFERENTIAL EXPRESSION =============

def run_de_analysis(expr_matrix: pd.DataFrame, labels: pd.Series,
                    method: str = 'limma_voom',
                    fdr_threshold: float = 0.05,
                    log2fc_threshold: float = 1.0,
                    raw_counts: pd.DataFrame = None) -> pd.DataFrame:
    """Run differential expression analysis (disease vs. control).

    Parameters
    ----------
    expr_matrix : pd.DataFrame
        Log2-transformed, normalized expression matrix (genes × samples).
    labels : pd.Series
        Condition labels: 'disease' or 'control'.
    method : str
        'limma_voom' — empirical Bayes moderated t-test (recommended)
        'ttest' — simple Welch's t-test with BH correction
    fdr_threshold : float
        FDR cutoff for significance.
    log2fc_threshold : float
        Minimum absolute log2 fold-change.
    raw_counts : pd.DataFrame
        Raw counts (needed for limma_voom method). If None, uses expr_matrix.

    Returns
    -------
    pd.DataFrame with columns: log2FC, t_statistic, p_value, fdr, significant, abs_log2FC
    Sorted by FDR ascending.
    """
    from statsmodels.stats.multitest import multipletests

    common_samples = labels.dropna().index.intersection(expr_matrix.columns)
    labels = labels.loc[common_samples]
    disease_samples = labels[labels == 'disease'].index
    control_samples = labels[labels == 'control'].index

    logging.info(f"DE analysis ({method}): {len(disease_samples)} disease vs "
                 f"{len(control_samples)} control")

    if method == 'limma_voom' and raw_counts is not None:
        return _limma_voom_de(raw_counts[common_samples], labels, fdr_threshold, log2fc_threshold)
    else:
        return _ttest_de(expr_matrix[common_samples], labels, fdr_threshold, log2fc_threshold)


def _ttest_de(expr_matrix: pd.DataFrame, labels: pd.Series,
              fdr_threshold: float, log2fc_threshold: float) -> pd.DataFrame:
    """Simple t-test DE with BH correction."""
    from statsmodels.stats.multitest import multipletests

    disease_samples = labels[labels == 'disease'].index
    control_samples = labels[labels == 'control'].index

    results = []
    for gene in expr_matrix.index:
        d_vals = expr_matrix.loc[gene, disease_samples].values.astype(float)
        c_vals = expr_matrix.loc[gene, control_samples].values.astype(float)

        d_vals = d_vals[np.isfinite(d_vals)]
        c_vals = c_vals[np.isfinite(c_vals)]

        if len(d_vals) < 3 or len(c_vals) < 3:
            continue

        log2fc = np.mean(d_vals) - np.mean(c_vals)
        t_stat, p_val = stats.ttest_ind(d_vals, c_vals, equal_var=False)

        results.append({
            'gene': gene,
            'log2FC': log2fc,
            'mean_disease': np.mean(d_vals),
            'mean_control': np.mean(c_vals),
            't_statistic': t_stat,
            'p_value': p_val
        })

    df = pd.DataFrame(results).set_index('gene')
    df = df.dropna(subset=['p_value'])

    # BH FDR correction
    _, fdr, _, _ = multipletests(df['p_value'].values, method='fdr_bh')
    df['fdr'] = fdr
    df['abs_log2FC'] = df['log2FC'].abs()
    df['significant'] = (df['fdr'] < fdr_threshold) & (df['abs_log2FC'] >= log2fc_threshold)
    df = df.sort_values('fdr')

    n_sig = df['significant'].sum()
    logging.info(f"DE results: {n_sig} significant genes (FDR<{fdr_threshold}, |log2FC|>={log2fc_threshold})")
    return df


def _limma_voom_de(counts: pd.DataFrame, labels: pd.Series,
                   fdr_threshold: float, log2fc_threshold: float) -> pd.DataFrame:
    """Limma-voom style DE: weighted OLS with empirical Bayes variance moderation."""
    from statsmodels.stats.multitest import multipletests
    from statsmodels.nonparametric.smoothers_lowess import lowess

    disease_samples = labels[labels == 'disease'].index.tolist()
    control_samples = labels[labels == 'control'].index.tolist()
    all_samples = disease_samples + control_samples

    raw = counts[all_samples]

    # Filter
    raw = filter_low_count_genes(raw, min_count=10, min_samples_frac=0.2)

    # Library sizes and CPM
    lib_sizes = raw.sum(axis=0)
    cpm = raw.div(lib_sizes, axis=1) * 1e6
    log_cpm = np.log2(cpm + 0.5)

    # Design matrix: intercept + condition
    design = pd.DataFrame({
        'intercept': 1.0,
        'condition': [1.0 if s in disease_samples else 0.0 for s in all_samples]
    }, index=all_samples)

    X = design.values
    n = X.shape[0]
    p = X.shape[1]

    # Fit per gene
    from numpy.linalg import lstsq

    betas = np.zeros((log_cpm.shape[0], p))
    residuals = np.zeros_like(log_cpm.values)
    sigma2 = np.zeros(log_cpm.shape[0])

    for i in range(log_cpm.shape[0]):
        y = log_cpm.iloc[i].values
        b, res, _, _ = lstsq(X, y, rcond=None)
        betas[i] = b
        fitted = X @ b
        residuals[i] = y - fitted
        sigma2[i] = np.sum((y - fitted) ** 2) / (n - p)

    # Empirical Bayes moderation (Smyth, 2004)
    s2 = sigma2.copy()
    s2_pos = s2[s2 > 0]
    if len(s2_pos) > 10:
        log_s2 = np.log(s2_pos)
        # Method of moments for prior
        s0_2 = np.exp(np.mean(log_s2))  # prior variance estimate
        d0 = max(2 * (len(s2_pos) - 1) / np.var(log_s2) - (n - p), 2)  # prior df

        # Moderated variance
        s2_mod = (d0 * s0_2 + (n - p) * s2) / (d0 + n - p)
        df_total = d0 + n - p
    else:
        s2_mod = s2
        df_total = n - p

    # Moderated t-statistics for condition coefficient (column 1)
    XtX_inv = np.linalg.inv(X.T @ X)
    se_coef = np.sqrt(s2_mod * XtX_inv[1, 1])
    se_coef = np.maximum(se_coef, 1e-10)
    t_mod = betas[:, 1] / se_coef

    # P-values from t-distribution
    p_values = 2 * stats.t.sf(np.abs(t_mod), df=df_total)

    # Build results
    results_df = pd.DataFrame({
        'log2FC': betas[:, 1],
        'mean_disease': log_cpm[disease_samples].mean(axis=1).values,
        'mean_control': log_cpm[control_samples].mean(axis=1).values,
        't_statistic': t_mod,
        'p_value': p_values,
        'sigma2_moderated': s2_mod,
    }, index=log_cpm.index)

    results_df = results_df.dropna(subset=['p_value'])
    _, fdr, _, _ = multipletests(results_df['p_value'].values, method='fdr_bh')
    results_df['fdr'] = fdr
    results_df['abs_log2FC'] = results_df['log2FC'].abs()
    results_df['significant'] = (
        (results_df['fdr'] < fdr_threshold) &
        (results_df['abs_log2FC'] >= log2fc_threshold)
    )
    results_df = results_df.sort_values('fdr')

    n_sig = results_df['significant'].sum()
    logging.info(f"Limma-voom DE: {n_sig} significant DEGs "
                 f"(FDR<{fdr_threshold}, |log2FC|>={log2fc_threshold})")
    return results_df


def plot_volcano(de_results: pd.DataFrame, output_file: str,
                 fdr_threshold: float = 0.05, log2fc_threshold: float = 1.0,
                 n_label: int = 15, title: str = "Volcano Plot"):
    """Plot volcano plot of DE results.

    Parameters
    ----------
    de_results : pd.DataFrame
        Output of run_de_analysis().
    output_file : str
        Path to save the plot.
    fdr_threshold : float
        FDR cutoff line.
    log2fc_threshold : float
        log2FC cutoff lines.
    n_label : int
        Number of top genes to label.
    title : str
        Plot title.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    df = de_results.copy()
    df['-log10_fdr'] = -np.log10(df['fdr'].clip(lower=1e-300))

    fig, ax = plt.subplots(figsize=(10, 8))

    # Non-significant
    ns = ~df['significant']
    ax.scatter(df.loc[ns, 'log2FC'], df.loc[ns, '-log10_fdr'],
              c='#cccccc', s=10, alpha=0.5, label='Not significant')

    # Significant up
    up = df['significant'] & (df['log2FC'] > 0)
    ax.scatter(df.loc[up, 'log2FC'], df.loc[up, '-log10_fdr'],
              c='#e74c3c', s=20, alpha=0.7, label=f'Up ({up.sum()})')

    # Significant down
    down = df['significant'] & (df['log2FC'] < 0)
    ax.scatter(df.loc[down, 'log2FC'], df.loc[down, '-log10_fdr'],
              c='#3498db', s=20, alpha=0.7, label=f'Down ({down.sum()})')

    # Threshold lines
    ax.axhline(-np.log10(fdr_threshold), ls='--', c='gray', lw=0.5)
    ax.axvline(log2fc_threshold, ls='--', c='gray', lw=0.5)
    ax.axvline(-log2fc_threshold, ls='--', c='gray', lw=0.5)

    # Label top genes
    top_genes = df.head(n_label).index.tolist()
    for gene in top_genes:
        ax.annotate(gene, (df.loc[gene, 'log2FC'], df.loc[gene, '-log10_fdr']),
                   fontsize=6, alpha=0.8,
                   textcoords="offset points", xytext=(5, 5))

    ax.set_xlabel("log2 Fold Change")
    ax.set_ylabel("-log10(FDR)")
    ax.set_title(title)
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.2)
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved volcano plot: {output_file}")


# ============= WGCNA-STYLE CO-EXPRESSION ANALYSIS =============

def build_coexpression_network(expr_matrix: pd.DataFrame,
                                n_top_var_genes: int = 5000,
                                soft_power: int = None,
                                min_module_size: int = 30,
                                merge_threshold: float = 0.25) -> Dict:
    """Build weighted gene co-expression network (WGCNA-style).

    Parameters
    ----------
    expr_matrix : pd.DataFrame
        Log2-normalized expression matrix (genes × samples).
    n_top_var_genes : int
        Number of most variable genes to use.
    soft_power : int
        Soft-thresholding power. If None, auto-select.
    min_module_size : int
        Minimum genes per module.
    merge_threshold : float
        Module merge distance threshold.

    Returns
    -------
    dict with: 'modules' (gene→module), 'module_eigengenes', 'hub_genes',
    'connectivity', 'n_modules', 'soft_power', 'adjacency_summary'
    """
    logging.info(f"Building co-expression network with top {n_top_var_genes} variable genes...")

    # Select top variable genes
    gene_var = expr_matrix.var(axis=1).sort_values(ascending=False)
    top_genes = gene_var.head(n_top_var_genes).index
    expr_sub = expr_matrix.loc[top_genes].T  # samples × genes

    # Remove any genes with zero variance
    expr_sub = expr_sub.loc[:, expr_sub.var() > 0]
    logging.info(f"Using {expr_sub.shape[1]} genes after variance filter")

    # Auto-select soft power (scale-free topology criterion)
    if soft_power is None:
        soft_power = _pick_soft_threshold(expr_sub)
        logging.info(f"Auto-selected soft power: {soft_power}")

    # Correlation matrix (Pearson) — .copy() to avoid read-only numpy array
    cor_matrix = expr_sub.corr().values.copy()
    np.fill_diagonal(cor_matrix, 0)

    # Adjacency matrix (signed network)
    adjacency = np.power((1 + cor_matrix) / 2, soft_power)
    np.fill_diagonal(adjacency, 0)

    # Topological Overlap Matrix (TOM)
    tom = _compute_tom(adjacency)
    dist_tom = 1 - tom

    # Hierarchical clustering
    np.fill_diagonal(dist_tom, 0)
    dist_condensed = squareform(dist_tom, checks=False)
    dist_condensed = np.nan_to_num(dist_condensed, nan=1.0)
    Z = linkage(dist_condensed, method='average')

    # Dynamic tree cut (simplified: use fixed height cut then merge small)
    gene_names = expr_sub.columns.tolist()
    modules = _dynamic_tree_cut(Z, gene_names, min_module_size=min_module_size)

    # Merge similar modules
    modules = _merge_close_modules(expr_sub, modules, merge_threshold)

    # Module eigengenes (PC1 of each module)
    module_eigengenes = _compute_module_eigengenes(expr_sub, modules)

    # Hub genes (highest intramodular connectivity)
    hub_genes = _find_hub_genes(adjacency, modules, gene_names, n_hubs=10)

    # Connectivity
    connectivity = pd.Series(adjacency.sum(axis=1), index=gene_names)

    # Module sizes
    module_sizes = pd.Series(modules).value_counts()
    n_modules = len([m for m in module_sizes.index if m != 'grey'])

    logging.info(f"WGCNA: {n_modules} modules detected (+ grey/unassigned)")
    for mod, size in module_sizes.items():
        logging.info(f"  Module {mod}: {size} genes")

    return {
        'modules': modules,  # dict: gene_name → module_label
        'module_eigengenes': module_eigengenes,  # DataFrame: samples × modules
        'hub_genes': hub_genes,  # dict: module → list of hub genes
        'connectivity': connectivity,
        'n_modules': n_modules,
        'soft_power': soft_power,
        'module_sizes': module_sizes.to_dict(),
        'gene_names': gene_names
    }


def _pick_soft_threshold(expr: pd.DataFrame, powers: List[int] = None) -> int:
    """Pick soft-thresholding power for scale-free topology."""
    if powers is None:
        powers = list(range(1, 21))

    cor = expr.corr().values.copy()  # .copy() to avoid read-only array
    np.fill_diagonal(cor, 0)
    n_genes = cor.shape[0]

    best_power = 6  # default
    best_r2 = 0

    for power in powers:
        adj = np.power(np.abs(cor), power)
        np.fill_diagonal(adj, 0)
        k = adj.sum(axis=1)
        k = k[k > 0]

        if len(k) < 10:
            continue

        # Fit scale-free topology: log(p(k)) vs log(k)
        hist, bin_edges = np.histogram(k, bins=min(30, len(set(k.astype(int)))))
        hist = hist[hist > 0]
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
        bin_centers = bin_centers[:len(hist)]

        if len(hist) < 3:
            continue

        log_k = np.log10(bin_centers + 1)
        log_p = np.log10(hist / hist.sum() + 1e-10)

        slope, intercept, r_value, _, _ = stats.linregress(log_k, log_p)
        r2 = r_value ** 2

        if r2 > best_r2 and slope < 0:
            best_r2 = r2
            best_power = power

        if r2 > 0.85:
            return power

    return best_power


def _compute_tom(adjacency: np.ndarray) -> np.ndarray:
    """Compute Topological Overlap Matrix."""
    n = adjacency.shape[0]
    k = adjacency.sum(axis=1)

    # TOM_ij = (sum_u(a_iu * a_uj) + a_ij) / (min(k_i, k_j) + 1 - a_ij)
    numerator = adjacency @ adjacency + adjacency
    denominator = np.minimum(k[:, None], k[None, :]) + 1 - adjacency

    tom = np.where(denominator > 0, numerator / denominator, 0)
    np.fill_diagonal(tom, 1)
    tom = np.clip(tom, 0, 1)
    return tom


def _dynamic_tree_cut(Z: np.ndarray, gene_names: List[str],
                      min_module_size: int = 30) -> Dict[str, str]:
    """Simplified dynamic tree cut for module detection."""
    from scipy.cluster.hierarchy import fcluster

    # Try multiple cut heights to find one giving reasonable module sizes
    n_genes = len(gene_names)
    best_labels = None
    best_n_modules = 0

    for height_frac in np.arange(0.90, 0.50, -0.05):
        max_d = Z[-1, 2] * height_frac
        labels = fcluster(Z, t=max_d, criterion='distance')

        # Count modules meeting min size
        unique, counts = np.unique(labels, return_counts=True)
        valid_modules = sum(1 for c in counts if c >= min_module_size)

        if valid_modules > best_n_modules and valid_modules >= 3:
            best_n_modules = valid_modules
            best_labels = labels.copy()

    if best_labels is None:
        # Fallback: fixed number of clusters
        best_labels = fcluster(Z, t=10, criterion='maxclust')

    # Map to color-like labels
    unique_labels = np.unique(best_labels)
    color_names = _generate_module_colors(len(unique_labels))

    modules = {}
    for i, gene in enumerate(gene_names):
        label = best_labels[i]
        label_idx = np.where(unique_labels == label)[0][0]

        # Check if this module meets min size
        module_size = np.sum(best_labels == label)
        if module_size >= min_module_size:
            modules[gene] = color_names[label_idx]
        else:
            modules[gene] = 'grey'  # Unassigned

    return modules


def _generate_module_colors(n: int) -> List[str]:
    """Generate distinct module color names."""
    colors = ['turquoise', 'blue', 'brown', 'yellow', 'green', 'red',
              'black', 'pink', 'magenta', 'purple', 'greenyellow', 'tan',
              'salmon', 'cyan', 'midnightblue', 'lightcyan', 'lightyellow',
              'royalblue', 'darkred', 'darkgreen', 'darkturquoise',
              'darkgrey', 'orange', 'darkorange', 'white', 'skyblue']
    while len(colors) < n:
        colors.append(f'module_{len(colors)+1}')
    return colors[:n]


def _merge_close_modules(expr: pd.DataFrame, modules: Dict[str, str],
                         merge_threshold: float = 0.25) -> Dict[str, str]:
    """Merge modules whose eigengenes are highly correlated."""
    me = _compute_module_eigengenes(expr, modules)

    # Skip grey
    mod_cols = [c for c in me.columns if c != 'grey']
    if len(mod_cols) < 2:
        return modules

    # Compute distance between eigengenes
    me_cor = me[mod_cols].corr()
    me_dist = 1 - me_cor

    # Merge pairs closer than threshold
    merged = {}
    for col in mod_cols:
        merged[col] = col

    for i in range(len(mod_cols)):
        for j in range(i + 1, len(mod_cols)):
            if me_dist.iloc[i, j] < merge_threshold:
                # Merge j into i
                old = mod_cols[j]
                new = mod_cols[i]
                for k, v in merged.items():
                    if v == old:
                        merged[k] = new

    # Update module assignments
    new_modules = {}
    for gene, mod in modules.items():
        new_modules[gene] = merged.get(mod, mod)

    return new_modules


def _compute_module_eigengenes(expr: pd.DataFrame,
                                modules: Dict[str, str]) -> pd.DataFrame:
    """Compute module eigengenes (PC1 of each module)."""
    from sklearn.decomposition import PCA

    module_labels = set(modules.values())
    eigengenes = {}

    for mod in module_labels:
        genes_in_mod = [g for g, m in modules.items() if m == mod]
        if len(genes_in_mod) < 3:
            continue

        # Check that genes exist in the expression matrix columns
        available = [g for g in genes_in_mod if g in expr.columns]
        if len(available) < 3:
            continue

        mod_expr = expr[available].values
        mod_expr = np.nan_to_num(mod_expr, nan=0)

        pca = PCA(n_components=1)
        me = pca.fit_transform(mod_expr).flatten()
        eigengenes[mod] = me

    return pd.DataFrame(eigengenes, index=expr.index)


def _find_hub_genes(adjacency: np.ndarray, modules: Dict[str, str],
                    gene_names: List[str], n_hubs: int = 10) -> Dict[str, List[str]]:
    """Find hub genes (highest intramodular connectivity) per module."""
    hub_genes = {}
    module_labels = set(modules.values())

    for mod in module_labels:
        if mod == 'grey':
            continue

        gene_indices = [i for i, g in enumerate(gene_names)
                       if modules.get(g) == mod]

        if len(gene_indices) < 3:
            continue

        # Intramodular connectivity
        sub_adj = adjacency[np.ix_(gene_indices, gene_indices)]
        intra_k = sub_adj.sum(axis=1)

        # Top hubs
        top_idx = np.argsort(intra_k)[::-1][:min(n_hubs, len(gene_indices))]
        hubs = [(gene_names[gene_indices[i]], float(intra_k[i])) for i in top_idx]
        hub_genes[mod] = hubs

    return hub_genes


# ============= MACHINE LEARNING FEATURE RANKING =============

def elastic_net_classify(expr_matrix: pd.DataFrame, labels: pd.Series,
                         alpha: float = 0.5, n_cv: int = 5,
                         max_iter: int = 5000,
                         n_top_genes: int = 2000) -> Dict:
    """Elastic net logistic regression for disease classification.

    Parameters
    ----------
    expr_matrix : pd.DataFrame
        Log2-normalized expression matrix (genes × samples).
    labels : pd.Series
        Condition labels: 'disease'=1, 'control'=0.
    alpha : float
        L1 ratio (0=ridge, 1=lasso, 0.5=elastic net).
    n_cv : int
        Number of cross-validation folds.
    max_iter : int
        Maximum iterations.
    n_top_genes : int
        Use top N most variable genes.

    Returns
    -------
    dict with: 'nonzero_genes', 'coefficients', 'cv_accuracy',
    'cv_auc', 'feature_importance'
    """
    from sklearn.linear_model import LogisticRegressionCV
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import cross_val_score

    logging.info("Running elastic net classification...")

    common = labels.dropna().index.intersection(expr_matrix.columns)
    labels = labels.loc[common]
    X = expr_matrix[common].T

    # Use top variable genes
    gene_var = X.var().sort_values(ascending=False)
    top_genes = gene_var.head(min(n_top_genes, len(gene_var))).index
    X = X[top_genes]

    y = (labels == 'disease').astype(int)

    # Standardize
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X.values)

    # Fit elastic net with CV
    model = LogisticRegressionCV(
        penalty='elasticnet',
        solver='saga',
        l1_ratios=[alpha],
        cv=min(n_cv, len(y)),
        max_iter=max_iter,
        scoring='accuracy',
        random_state=42,
        n_jobs=-1
    )
    model.fit(X_scaled, y)

    # Extract results
    coef = pd.Series(model.coef_[0], index=top_genes)
    nonzero = coef[coef != 0].sort_values(key=abs, ascending=False)

    # CV accuracy
    cv_scores = cross_val_score(model, X_scaled, y, cv=min(n_cv, len(y)), scoring='accuracy')

    logging.info(f"Elastic net: {len(nonzero)} nonzero features, "
                 f"CV accuracy={cv_scores.mean():.3f} ± {cv_scores.std():.3f}")

    return {
        'nonzero_genes': nonzero.to_dict(),
        'all_coefficients': coef.to_dict(),
        'n_nonzero': len(nonzero),
        'cv_accuracy_mean': float(cv_scores.mean()),
        'cv_accuracy_std': float(cv_scores.std()),
        'feature_importance': nonzero.abs().sort_values(ascending=False).to_dict(),
        'top_genes': top_genes.tolist()
    }


def xgboost_rank(expr_matrix: pd.DataFrame, labels: pd.Series,
                 n_estimators: int = 200, max_depth: int = 6,
                 n_cv: int = 5, n_top_genes: int = 2000) -> Dict:
    """XGBoost classification with feature importance ranking.

    Parameters
    ----------
    expr_matrix : pd.DataFrame
        Log2-normalized expression matrix (genes × samples).
    labels : pd.Series
        Condition labels.
    n_estimators : int
        Number of boosting rounds.
    max_depth : int
        Max tree depth.
    n_cv : int
        CV folds.
    n_top_genes : int
        Use top N most variable genes.

    Returns
    -------
    dict with: 'feature_importance' (gain-based), 'cv_accuracy',
    'top_features', 'model_params'
    """
    import xgboost as xgb
    from sklearn.model_selection import cross_val_score
    from sklearn.preprocessing import StandardScaler

    logging.info("Running XGBoost classification...")

    common = labels.dropna().index.intersection(expr_matrix.columns)
    labels = labels.loc[common]
    X = expr_matrix[common].T

    # Top variable genes
    gene_var = X.var().sort_values(ascending=False)
    top_genes = gene_var.head(min(n_top_genes, len(gene_var))).index
    X = X[top_genes]

    y = (labels == 'disease').astype(int)

    model = xgb.XGBClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=0.1,
        objective='binary:logistic',
        eval_metric='logloss',
        random_state=42,
        n_jobs=-1,
        use_label_encoder=False,
        verbosity=0
    )

    # CV accuracy
    cv_scores = cross_val_score(model, X.values, y.values,
                                cv=min(n_cv, len(y)), scoring='accuracy')

    # Fit on full data for feature importance
    model.fit(X.values, y.values)

    # Feature importance (gain)
    importance = pd.Series(model.feature_importances_, index=top_genes)
    importance = importance.sort_values(ascending=False)
    top_features = importance.head(50)

    logging.info(f"XGBoost: CV accuracy={cv_scores.mean():.3f} ± {cv_scores.std():.3f}, "
                 f"top feature: {top_features.index[0]} (gain={top_features.iloc[0]:.4f})")

    return {
        'feature_importance': importance.to_dict(),
        'top_50_features': top_features.to_dict(),
        'cv_accuracy_mean': float(cv_scores.mean()),
        'cv_accuracy_std': float(cv_scores.std()),
        'n_features_used': len(top_genes),
        'model_params': {
            'n_estimators': n_estimators,
            'max_depth': max_depth,
            'learning_rate': 0.1
        }
    }


def plot_feature_importance(elastic_net_result: Dict, xgboost_result: Dict,
                            output_file: str, n_top: int = 20,
                            title: str = "Feature Importance Comparison"):
    """Plot side-by-side feature importance from elastic net and XGBoost.

    Parameters
    ----------
    elastic_net_result : dict
        Output of elastic_net_classify().
    xgboost_result : dict
        Output of xgboost_rank().
    output_file : str
        Path to save the plot.
    n_top : int
        Number of top features to show.
    title : str
        Plot title.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))

    # Elastic net
    en_imp = pd.Series(elastic_net_result.get('feature_importance', {}))
    en_top = en_imp.head(n_top).sort_values()
    ax1.barh(range(len(en_top)), en_top.values, color='#3498db', alpha=0.8)
    ax1.set_yticks(range(len(en_top)))
    ax1.set_yticklabels(en_top.index, fontsize=7)
    ax1.set_xlabel("|Coefficient|")
    ax1.set_title(f"Elastic Net (n={elastic_net_result.get('n_nonzero', '?')} nonzero)")

    # XGBoost
    xgb_imp = pd.Series(xgboost_result.get('top_50_features', {}))
    xgb_top = xgb_imp.head(n_top).sort_values()
    ax2.barh(range(len(xgb_top)), xgb_top.values, color='#e74c3c', alpha=0.8)
    ax2.set_yticks(range(len(xgb_top)))
    ax2.set_yticklabels(xgb_top.index, fontsize=7)
    ax2.set_xlabel("Gain")
    ax2.set_title(f"XGBoost (acc={xgboost_result.get('cv_accuracy_mean', 0):.3f})")

    plt.suptitle(title, fontsize=14)
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved feature importance plot: {output_file}")


# ============= STRUCTURED HANDOFF =============

def assemble_handoff_artifact(
    de_results: pd.DataFrame,
    wgcna_result: Dict,
    elastic_net_result: Dict,
    xgboost_result: Dict,
    phenotype_summary: Dict,
    dataset_info: Dict,
    output_path: str = None
) -> Dict:
    """Assemble structured handoff artifact from all analyses.

    Parameters
    ----------
    de_results : pd.DataFrame
        DE analysis results.
    wgcna_result : dict
        WGCNA co-expression results.
    elastic_net_result : dict
        Elastic net classification results.
    xgboost_result : dict
        XGBoost classification results.
    phenotype_summary : dict
        Summary of phenotype/condition info.
    dataset_info : dict
        Dataset metadata.
    output_path : str
        Path to save JSON. Defaults to OUTPUT_DIR/handoff_artifact.json.

    Returns
    -------
    dict — the complete handoff artifact
    """
    if output_path is None:
        output_path = os.path.join(OUTPUT_DIR, 'handoff_artifact.json')

    # Ranked DEGs
    sig_degs = de_results[de_results['significant']].copy()
    ranked_degs = []
    for gene in sig_degs.index[:200]:  # Top 200
        row = sig_degs.loc[gene]
        ranked_degs.append({
            'gene': gene,
            'log2FC': float(row['log2FC']),
            'fdr': float(row['fdr']),
            'direction': 'up' if row['log2FC'] > 0 else 'down'
        })

    # Module scores + hub genes
    module_info = []
    for mod, genes_list in wgcna_result.get('hub_genes', {}).items():
        module_info.append({
            'module': mod,
            'size': wgcna_result.get('module_sizes', {}).get(mod, 0),
            'hub_genes': [{'gene': g, 'connectivity': float(c)} for g, c in genes_list[:5]]
        })

    # Model feature importance (consensus)
    en_features = elastic_net_result.get('feature_importance', {})
    xgb_features = xgboost_result.get('feature_importance', {})

    # Rank-based consensus
    all_genes = set(list(en_features.keys())[:100] + list(xgb_features.keys())[:100])
    en_rank = {g: i for i, g in enumerate(en_features.keys())}
    xgb_rank = {g: i for i, g in enumerate(xgb_features.keys())}
    max_rank = max(len(en_features), len(xgb_features))

    consensus_scores = {}
    for gene in all_genes:
        r_en = en_rank.get(gene, max_rank)
        r_xgb = xgb_rank.get(gene, max_rank)
        consensus_scores[gene] = 2.0 / (1.0/(r_en+1) + 1.0/(r_xgb+1))  # harmonic mean of ranks

    consensus_ranked = sorted(consensus_scores.items(), key=lambda x: x[1])

    artifact = {
        'metadata': {
            'dataset': dataset_info,
            'analysis_pipeline': 'rnaseq_utils v1.0 (Microsoft Discovery)',
            'methods': ['DESeq2-style normalization', 'limma-voom DE',
                       'WGCNA co-expression', 'Elastic Net', 'XGBoost']
        },
        'phenotype_definition': phenotype_summary,
        'ranked_degs': ranked_degs,
        'de_summary': {
            'total_genes_tested': len(de_results),
            'significant_up': int((sig_degs['log2FC'] > 0).sum()),
            'significant_down': int((sig_degs['log2FC'] < 0).sum()),
            'fdr_threshold': 0.05,
            'log2fc_threshold': 1.0
        },
        'coexpression_modules': module_info,
        'module_summary': {
            'n_modules': wgcna_result.get('n_modules', 0),
            'soft_power': wgcna_result.get('soft_power', 0),
            'module_sizes': wgcna_result.get('module_sizes', {})
        },
        'model_feature_importance': {
            'elastic_net': {
                'cv_accuracy': elastic_net_result.get('cv_accuracy_mean', 0),
                'n_nonzero_features': elastic_net_result.get('n_nonzero', 0),
                'top_features': dict(list(en_features.items())[:30])
            },
            'xgboost': {
                'cv_accuracy': xgboost_result.get('cv_accuracy_mean', 0),
                'top_features': dict(list(xgb_features.items())[:30])
            },
            'consensus_ranking': [{'gene': g, 'harmonic_rank': float(r)}
                                  for g, r in consensus_ranked[:50]]
        }
    }

    with open(output_path, 'w') as f:
        json.dump(artifact, f, indent=2, default=str)
    logging.info(f"Saved handoff artifact: {output_path}")

    return artifact


# ============= CLEANUP =============

def tool_cleanup(deep: bool = False):
    """Clean tool state between analyses."""
    try:
        if deep:
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
