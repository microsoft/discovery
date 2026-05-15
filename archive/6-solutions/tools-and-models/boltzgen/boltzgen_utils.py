#!/usr/bin/env python3
"""BoltzGen utilities library for Discovery platform workflows.

Wraps the BoltzGen protein binder design CLI (HannesStark/boltzgen) for use
on the Microsoft Discovery platform. BoltzGen uses diffusion models to generate,
fold, score, and rank protein/peptide/antibody binder designs.

Reference: https://github.com/HannesStark/boltzgen
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

try:
    import yaml
except ImportError:
    yaml = None

# ============= CONSTANTS (defaults — overridden by quick_setup params) =============
INPUT_DIR = "/input"
OUTPUT_DIR = "/output"
WORK_DIR = "/workdir"
SCRATCH_DIR = "/tmp/boltzgen_scratch"

PROTOCOLS = [
    "protein-anything",
    "peptide-anything",
    "protein-small_molecule",
    "antibody-anything",
    "nanobody-anything",
    "protein-redesign",
]

PIPELINE_STEPS = [
    "design",
    "inverse_folding",
    "folding",
    "design_folding",
    "affinity",
    "analysis",
    "filtering",
]


# ============= SETUP FUNCTIONS =============

def quick_setup(input_dir='/input', output_dir='/output', work_dir='/workdir'):
    """Initialize logging, create directories, copy input files.

    ALL THREE parameters should be passed explicitly in every script.

    Args:
        input_dir: Path to input directory (mounted by Discovery platform).
        output_dir: Path to output directory (persisted after job).
        work_dir: Path to working directory for intermediate files.
    """
    global INPUT_DIR, OUTPUT_DIR, WORK_DIR
    INPUT_DIR, OUTPUT_DIR, WORK_DIR = input_dir, output_dir, work_dir

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Suppress noisy upstream warnings (boltzgen writer.py unclosed files,
    # cuequivariance SM100f kernel cast) — these are cosmetic, not actionable.
    warnings.filterwarnings("ignore", category=ResourceWarning, module=r"boltzgen\.task\.predict\.writer")
    warnings.filterwarnings("ignore", message=r"Non-SM100f kernel expects bias", module=r"cuequivariance_ops_torch")

    for d in [WORK_DIR, OUTPUT_DIR, SCRATCH_DIR]:
        os.makedirs(d, exist_ok=True)
    os.chdir(WORK_DIR)
    copy_input_files()
    logging.info(f"Working directory: {WORK_DIR}")
    logging.info(f"Input files: {os.listdir(INPUT_DIR) if os.path.exists(INPUT_DIR) else 'none'}")
    logging.info(f"Working files: {os.listdir(WORK_DIR)}")

    # Check GPU availability
    try:
        import torch
        if torch.cuda.is_available():
            num_gpus = torch.cuda.device_count()
            for i in range(num_gpus):
                name = torch.cuda.get_device_name(i)
                props = torch.cuda.get_device_properties(i)
                mem = getattr(props, 'total_memory', None) or getattr(props, 'total_mem', 0)
                logging.info(f"GPU {i}: {name} ({mem / (1024**3):.1f} GB)")
            logging.info(f"Total GPUs: {num_gpus}")
        else:
            logging.warning("No CUDA GPU detected — BoltzGen requires GPU for diffusion inference")
    except ImportError:
        logging.warning("PyTorch not available — cannot check GPU")

    # Check boltzgen CLI
    try:
        result = subprocess.run(['boltzgen', '--help'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            logging.info("BoltzGen CLI available")
        else:
            logging.warning("BoltzGen CLI returned non-zero")
    except Exception as e:
        logging.error(f"BoltzGen CLI not found: {e}")


def copy_input_files():
    """Copy input files to working directory (with same-directory guard)."""
    if os.path.realpath(INPUT_DIR) == os.path.realpath(WORK_DIR):
        return
    if os.path.exists(INPUT_DIR):
        for item in os.listdir(INPUT_DIR):
            src = os.path.join(INPUT_DIR, item)
            dst = os.path.join(WORK_DIR, item)
            if os.path.isfile(src):
                shutil.copy2(src, dst)
            elif os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)


def copy_outputs():
    """Copy important output files to output directory (with same-directory guard)."""
    if os.path.realpath(WORK_DIR) == os.path.realpath(OUTPUT_DIR):
        return
    patterns = ['*.csv', '*.json', '*.yaml', '*.yml', '*.png', '*.pdf', '*.cif', '*.pdb', '*.log']
    for pattern in patterns:
        for f in glob.glob(os.path.join(WORK_DIR, '**', pattern), recursive=True):
            rel = os.path.relpath(f, WORK_DIR)
            dst = os.path.join(OUTPUT_DIR, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                shutil.copy2(f, dst)
            except shutil.SameFileError:
                pass
    logging.info("Outputs copied to /output")


def quick_finish():
    """Copy output files to output directory."""
    copy_outputs()


def save_final_results(results: Dict, output_files: Dict = None,
                       file_descriptions: Dict = None, status: str = "completed"):
    """Save final results to JSON file (MANDATORY for every script).

    Args:
        results: Dictionary of result metrics and summary data.
        output_files: Dictionary mapping name → file path for generated files.
        file_descriptions: Dictionary mapping name → description of each file.
        status: Job status — 'completed' or 'failed'.
    """
    final_data = {"status": status, "summary": results}
    if output_files:
        final_data["output_files"] = output_files
    if file_descriptions:
        final_data["file_descriptions"] = file_descriptions

    def make_serializable(obj):
        """Convert numpy/pandas types to JSON-serializable Python types."""
        if isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, pd.DataFrame):
            return obj.to_dict('records')
        elif isinstance(obj, pd.Series):
            return obj.to_dict()
        elif isinstance(obj, Path):
            return str(obj)
        elif isinstance(obj, np.bool_):
            return bool(obj)
        return str(obj)

    out_path = os.path.join(OUTPUT_DIR, 'final_results.json')
    with open(out_path, 'w') as f:
        json.dump(final_data, f, indent=2, default=make_serializable)
    logging.info(f"Saved final_results.json → {out_path}")


# ============= COMMAND EXECUTION =============

def run_command(cmd: List[str], input_text: str = None,
                timeout: int = None, cwd: str = None) -> subprocess.CompletedProcess:
    """Execute a command with error handling and logging.

    Args:
        cmd: Command and arguments as a list of strings.
        input_text: Optional stdin input.
        timeout: Optional timeout in seconds.
        cwd: Optional working directory.

    Returns:
        subprocess.CompletedProcess with stdout/stderr.

    Raises:
        subprocess.CalledProcessError: If command returns non-zero exit code.
        subprocess.TimeoutExpired: If command exceeds timeout.
    """
    cmd_preview = ' '.join(cmd[:6]) + ('...' if len(cmd) > 6 else '')
    logging.info(f"Running: {cmd_preview}")
    try:
        result = subprocess.run(
            cmd,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            cwd=cwd,
        )
        if result.stdout:
            # Log last 500 chars of stdout
            logging.info(f"STDOUT (tail): ...{result.stdout[-500:]}")
        if result.returncode != 0:
            logging.error(f"Command failed (rc={result.returncode})")
            if result.stderr:
                logging.error(f"STDERR: {result.stderr[-1000:]}")
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr)
        return result
    except subprocess.TimeoutExpired:
        logging.error(f"Command timed out after {timeout}s")
        raise


def run_command_streaming(cmd: List[str], timeout: int = None,
                          cwd: str = None, log_file: str = None) -> int:
    """Execute a command with real-time stdout/stderr streaming.

    Args:
        cmd: Command and arguments as a list of strings.
        timeout: Optional timeout in seconds.
        cwd: Optional working directory.
        log_file: Optional path to save full output log.

    Returns:
        int: Process return code.
    """
    cmd_preview = ' '.join(cmd[:6]) + ('...' if len(cmd) > 6 else '')
    logging.info(f"Running (streaming): {cmd_preview}")

    log_fh = None
    if log_file:
        log_fh = open(log_file, 'w')

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=cwd,
    )
    try:
        for line in process.stdout:
            print(line, end='', flush=True)
            if log_fh:
                log_fh.write(line)
        process.wait(timeout=timeout)
        return process.returncode
    except subprocess.TimeoutExpired:
        process.kill()
        logging.error(f"Command timed out after {timeout}s")
        raise
    finally:
        if log_fh:
            log_fh.close()


# ============= DESIGN SPECIFICATION =============

def create_design_spec(
    entities: List[Dict],
    constraints: List[Dict] = None,
    output_path: str = None,
) -> str:
    """Create a BoltzGen design specification YAML file.

    Args:
        entities: List of entity specifications. Each entity is a dict with one key:
            - 'protein': {'id': str, 'sequence': str} — designed or fixed protein chain
            - 'file': {'path': str, 'include': list, ...} — target from structure file
            - 'ligand': {'id': str, 'ccd': str} — small molecule ligand
        constraints: Optional list of bond constraints for cross-linking.
        output_path: Path to save the YAML file. Defaults to 'design_spec.yaml' in WORK_DIR.

    Returns:
        str: Absolute path to the saved YAML file.

    Example:
        spec_path = create_design_spec(
            entities=[
                {'protein': {'id': 'B', 'sequence': '80..140'}},
                {'file': {
                    'path': 'target.cif',
                    'include': [{'chain': {'id': 'A'}}],
                }},
            ],
        )
    """
    if yaml is None:
        raise ImportError("pyyaml is required for YAML operations: pip install pyyaml")

    spec = {'entities': entities}
    if constraints:
        spec['constraints'] = constraints

    if output_path is None:
        output_path = os.path.join(WORK_DIR, 'design_spec.yaml')

    with open(output_path, 'w') as f:
        yaml.dump(spec, f, default_flow_style=False, sort_keys=False)

    logging.info(f"Design spec saved to {output_path}")
    return os.path.abspath(output_path)


def load_design_spec(path: str) -> Dict:
    """Load and return a design specification YAML file.

    Args:
        path: Path to design specification YAML.

    Returns:
        Dict: Parsed YAML content.
    """
    if yaml is None:
        raise ImportError("pyyaml is required for YAML operations")
    with open(path) as f:
        spec = yaml.safe_load(f)
    logging.info(f"Loaded design spec from {path}")
    return spec


def validate_design_spec(spec_path: str) -> Dict:
    """Run 'boltzgen check' to validate a design specification.

    Args:
        spec_path: Path to the design specification YAML file.

    Returns:
        Dict with keys:
            - valid (bool): Whether the spec passed validation.
            - output_file (str or None): Path to generated CIF for visualization.
            - message (str): Validation output or error message.
    """
    try:
        result = run_command(['boltzgen', 'check', spec_path])
        # boltzgen check produces a CIF file for visualization
        spec_dir = os.path.dirname(os.path.abspath(spec_path))
        cif_files = glob.glob(os.path.join(spec_dir, '*.cif'))
        return {
            'valid': True,
            'output_file': cif_files[0] if cif_files else None,
            'message': result.stdout,
        }
    except subprocess.CalledProcessError as e:
        return {
            'valid': False,
            'output_file': None,
            'message': e.stderr or str(e),
        }


# ============= PIPELINE EXECUTION =============

def run_design_pipeline(
    spec_path: str,
    output_dir: str = None,
    protocol: str = "protein-anything",
    num_designs: int = 10,
    budget: int = 2,
    devices: int = None,
    steps: List[str] = None,
    reuse: bool = False,
    extra_args: List[str] = None,
    timeout: int = None,
    cache_dir: str = None,
) -> Dict:
    """Run the BoltzGen design pipeline.

    Args:
        spec_path: Path to design specification YAML.
        output_dir: Output directory. Defaults to /output/boltzgen_run.
        protocol: Design protocol. One of PROTOCOLS.
        num_designs: Number of intermediate designs to generate.
        budget: Number of final diversity-optimized designs.
        devices: Number of GPU devices. None = auto-detect.
        steps: Specific pipeline steps to run. None = all steps.
        reuse: If True, reuse existing intermediate results.
        extra_args: Additional CLI arguments as list of strings.
        timeout: Timeout in seconds for the entire pipeline.
        cache_dir: Model weights cache directory.

    Returns:
        Dict with pipeline results including metrics and output paths.

    Raises:
        ValueError: If protocol is invalid.
        RuntimeError: If pipeline fails.
    """
    if protocol not in PROTOCOLS:
        raise ValueError(f"Invalid protocol '{protocol}'. Must be one of: {PROTOCOLS}")

    # Auto-validate the design spec before starting the pipeline
    validation = validate_design_spec(spec_path)
    if not validation['valid']:
        raise ValueError(
            f"Invalid design spec '{spec_path}': {validation['message']}"
        )
    logging.info(f"Design spec validated: {spec_path}")

    if output_dir is None:
        output_dir = os.path.join(OUTPUT_DIR, 'boltzgen_run')

    cmd = [
        'boltzgen', 'run', spec_path,
        '--output', output_dir,
        '--protocol', protocol,
        '--num_designs', str(num_designs),
        '--budget', str(budget),
    ]

    if devices is not None:
        cmd.extend(['--devices', str(devices)])

    if steps:
        for s in steps:
            if s not in PIPELINE_STEPS:
                raise ValueError(f"Invalid step '{s}'. Must be one of: {PIPELINE_STEPS}")
        cmd.extend(['--steps'] + steps)

    if reuse:
        cmd.append('--reuse')

    if cache_dir:
        cmd.extend(['--cache', cache_dir])

    if extra_args:
        cmd.extend(extra_args)

    logging.info(f"Running BoltzGen pipeline: protocol={protocol}, "
                 f"num_designs={num_designs}, budget={budget}")

    log_file = os.path.join(OUTPUT_DIR, 'boltzgen_pipeline.log')
    returncode = run_command_streaming(cmd, timeout=timeout, log_file=log_file)

    if returncode != 0:
        raise RuntimeError(
            f"BoltzGen pipeline failed with return code {returncode}. "
            f"Check log at {log_file}")

    # Parse results
    results = parse_pipeline_output(output_dir)
    results['protocol'] = protocol
    results['num_designs_requested'] = num_designs
    results['budget'] = budget
    results['log_file'] = log_file

    logging.info(f"Pipeline completed. Intermediate: {results.get('n_intermediate_designs', 0)}, "
                 f"Final: {results.get('n_final_designs', 0)}")
    return results


def run_filtering(
    spec_path: str,
    output_dir: str,
    protocol: str = "protein-anything",
    budget: int = None,
    alpha: float = None,
    filter_biased: bool = None,
    additional_filters: List[str] = None,
    metrics_override: List[str] = None,
    refolding_rmsd_threshold: float = None,
) -> Dict:
    """Re-run only the filtering step with adjusted parameters.

    This is fast (~15 seconds) and useful for tuning filter criteria
    after the computationally expensive design/folding steps.

    Args:
        spec_path: Path to design specification YAML.
        output_dir: Existing output directory from a previous run.
        protocol: Design protocol used in the original run.
        budget: Number of final designs in the diversity-optimized set.
        alpha: Diversity trade-off (0.0=quality, 1.0=diversity).
        filter_biased: Remove amino-acid composition outliers.
        additional_filters: Hard filters like ['ALA_fraction<0.3'].
        metrics_override: Per-metric weights like ['plip_hbonds_refolded=4'].
        refolding_rmsd_threshold: RMSD threshold for filtering.

    Returns:
        Dict with updated filtering results.
    """
    cmd = [
        'boltzgen', 'run', spec_path,
        '--output', output_dir,
        '--protocol', protocol,
        '--steps', 'filtering',
    ]

    if budget is not None:
        cmd.extend(['--budget', str(budget)])
    if alpha is not None:
        cmd.extend(['--alpha', str(alpha)])
    if filter_biased is not None:
        cmd.extend(['--filter_biased', str(filter_biased).lower()])
    if additional_filters:
        cmd.extend(['--additional_filters'] + additional_filters)
    if metrics_override:
        cmd.extend(['--metrics_override'] + metrics_override)
    if refolding_rmsd_threshold is not None:
        cmd.extend(['--refolding_rmsd_threshold', str(refolding_rmsd_threshold)])

    logging.info(f"Re-running filtering: budget={budget}, alpha={alpha}")
    returncode = run_command_streaming(cmd)

    if returncode != 0:
        raise RuntimeError(f"Filtering step failed with return code {returncode}")

    return parse_pipeline_output(output_dir)


def merge_runs(source_dirs: List[str], output_dir: str) -> str:
    """Merge designs from multiple pipeline runs.

    After merging, re-run filtering on the merged directory.

    Args:
        source_dirs: List of output directories from previous runs.
        output_dir: Destination directory for merged results.

    Returns:
        str: Path to merged output directory.
    """
    cmd = ['boltzgen', 'merge'] + source_dirs + ['--output', output_dir]

    logging.info(f"Merging {len(source_dirs)} runs into {output_dir}")
    result = run_command(cmd)
    logging.info(f"Merge complete: {output_dir}")
    return output_dir


def download_models(artifacts: str = 'all', cache_dir: str = None,
                    force: bool = False):
    """Download BoltzGen model weights.

    Args:
        artifacts: What to download — 'all', 'design-adherence', 'design-diverse',
                   'folding', 'inverse-fold', 'affinity', 'moldir'.
        cache_dir: Cache directory for weights.
        force: Force re-download.
    """
    cmd = ['boltzgen', 'download', artifacts]
    if cache_dir:
        cmd.extend(['--cache', cache_dir])
    if force:
        cmd.append('--force_download')

    logging.info(f"Downloading BoltzGen models: {artifacts}")
    run_command_streaming(cmd)
    logging.info("Model download complete")


# ============= OUTPUT PARSING =============

def parse_pipeline_output(output_dir: str) -> Dict:
    """Parse BoltzGen pipeline output directory into structured results.

    Args:
        output_dir: Path to BoltzGen output directory.

    Returns:
        Dict with parsed metrics, design counts, and file paths.
    """
    results = {
        'output_dir': output_dir,
        'n_intermediate_designs': 0,
        'n_final_designs': 0,
        'metrics': None,
        'final_metrics': None,
        'design_files': [],
        'final_design_files': [],
    }

    # Count intermediate designs
    intermediate_dir = os.path.join(output_dir, 'intermediate_designs')
    if os.path.exists(intermediate_dir):
        cif_files = glob.glob(os.path.join(intermediate_dir, '*.cif'))
        results['n_intermediate_designs'] = len(cif_files)
        results['design_files'] = [os.path.basename(f) for f in cif_files]

    # Parse aggregate metrics
    metrics_path = os.path.join(
        output_dir, 'intermediate_designs_inverse_folded',
        'aggregate_metrics_analyze.csv')
    if os.path.exists(metrics_path):
        results['metrics'] = pd.read_csv(metrics_path)
        logging.info(f"Loaded aggregate metrics: {len(results['metrics'])} designs")

    # Parse final ranked designs
    final_dir = os.path.join(output_dir, 'final_ranked_designs')
    if os.path.exists(final_dir):
        # Find final designs directory
        final_subdirs = glob.glob(os.path.join(final_dir, 'final_*_designs'))
        if final_subdirs:
            final_cifs = glob.glob(os.path.join(final_subdirs[0], '*.cif'))
            results['n_final_designs'] = len(final_cifs)
            results['final_design_files'] = [os.path.basename(f) for f in final_cifs]

        # Parse final metrics CSV
        final_metrics_files = glob.glob(
            os.path.join(final_dir, 'final_designs_metrics_*.csv'))
        if final_metrics_files:
            results['final_metrics'] = pd.read_csv(final_metrics_files[0])

        # All designs metrics
        all_metrics_path = os.path.join(final_dir, 'all_designs_metrics.csv')
        if os.path.exists(all_metrics_path):
            results['all_designs_metrics'] = pd.read_csv(all_metrics_path)

        # Overview PDF
        pdf_path = os.path.join(final_dir, 'results_overview.pdf')
        if os.path.exists(pdf_path):
            results['overview_pdf'] = pdf_path

    return results


def get_design_metrics(output_dir: str, design_id: str = None) -> pd.DataFrame:
    """Get metrics for specific or all designs.

    Args:
        output_dir: BoltzGen output directory.
        design_id: Optional specific design ID to filter.

    Returns:
        DataFrame with design metrics.

    Raises:
        FileNotFoundError: If no metrics CSV is found.
    """
    for pattern in [
        'final_ranked_designs/all_designs_metrics.csv',
        'intermediate_designs_inverse_folded/aggregate_metrics_analyze.csv',
    ]:
        csv_path = os.path.join(output_dir, pattern)
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            if design_id and 'design_id' in df.columns:
                df = df[df['design_id'] == design_id]
            logging.info(f"Loaded {len(df)} designs from {os.path.basename(csv_path)}")
            return df

    raise FileNotFoundError(f"No metrics CSV found in {output_dir}")


def get_top_designs(output_dir: str, n: int = 10,
                    sort_by: str = None) -> pd.DataFrame:
    """Get the top N designs ranked by quality metrics.

    Args:
        output_dir: BoltzGen output directory.
        n: Number of top designs to return.
        sort_by: Column to sort by. None uses default ranking order.

    Returns:
        DataFrame with top designs and their metrics.
    """
    df = get_design_metrics(output_dir)
    if sort_by and sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=True)
    return df.head(n)


# ============= VISUALIZATION =============

def plot_design_metrics(output_dir: str, output_file: str = None,
                        metrics: List[str] = None) -> Optional[str]:
    """Create summary visualization of design metrics.

    Args:
        output_dir: BoltzGen output directory.
        output_file: Path for output PNG. Defaults to /output/design_metrics.png.
        metrics: Specific metric columns to plot.

    Returns:
        str: Path to saved plot, or None if no metrics available.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    if output_file is None:
        output_file = os.path.join(OUTPUT_DIR, 'design_metrics.png')

    try:
        df = get_design_metrics(output_dir)
    except FileNotFoundError:
        logging.warning("No metrics file found — skipping plot")
        return None

    if metrics is None:
        # Auto-detect available quality metrics
        default_metrics = [
            'filter_rmsd_design', 'iptm_refolded', 'plddt_refolded',
            'delta_sasa_refolded', 'plip_hbonds_refolded',
            'shape_complementarity', 'pae_interaction_refolded',
        ]
        metrics = [m for m in default_metrics if m in df.columns]

    if not metrics:
        # Fall back to any numeric columns
        metrics = [c for c in df.select_dtypes(include=[np.number]).columns
                   if c not in ('Unnamed: 0', 'index')][:6]

    if not metrics:
        logging.warning("No plottable metrics found")
        return None

    n_metrics = len(metrics)
    n_cols = min(n_metrics, 3)
    n_rows = (n_metrics + n_cols - 1) // n_cols
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(5 * n_cols, 4 * n_rows))
    if n_metrics == 1:
        axes = np.array([axes])
    axes = axes.flatten()

    for i, metric in enumerate(metrics):
        ax = axes[i]
        data = df[metric].dropna()
        ax.hist(data, bins=30, edgecolor='black', alpha=0.7, color='steelblue')
        ax.set_xlabel(metric.replace('_', ' '))
        ax.set_ylabel('Count')
        ax.set_title(metric.replace('_', ' ').title(), fontsize=10)
        ax.axvline(data.median(), color='red', linestyle='--', alpha=0.7,
                   label=f'median={data.median():.3f}')
        ax.legend(fontsize=8)

    # Hide unused subplots
    for j in range(n_metrics, len(axes)):
        axes[j].set_visible(False)

    plt.suptitle(f'BoltzGen Design Metrics (n={len(df)})', fontsize=12, y=1.02)
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved metrics plot: {output_file}")
    return output_file


def plot_rmsd_vs_confidence(output_dir: str,
                            output_file: str = None) -> Optional[str]:
    """Plot RMSD vs confidence scatter for designs.

    Args:
        output_dir: BoltzGen output directory.
        output_file: Path for output PNG.

    Returns:
        str: Path to saved plot, or None if data not available.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    if output_file is None:
        output_file = os.path.join(OUTPUT_DIR, 'rmsd_vs_confidence.png')

    try:
        df = get_design_metrics(output_dir)
    except FileNotFoundError:
        logging.warning("No metrics file found — skipping scatter plot")
        return None

    # Find RMSD and confidence columns
    rmsd_col = None
    conf_col = None
    for col in df.columns:
        if 'rmsd' in col.lower() and rmsd_col is None:
            rmsd_col = col
        if ('iptm' in col.lower() or 'plddt' in col.lower()) and conf_col is None:
            conf_col = col

    if rmsd_col is None or conf_col is None:
        logging.warning(f"Cannot create scatter: rmsd_col={rmsd_col}, conf_col={conf_col}")
        return None

    fig, ax = plt.subplots(figsize=(8, 6))
    scatter = ax.scatter(
        df[rmsd_col], df[conf_col],
        alpha=0.5, s=20, c='steelblue', edgecolors='none')
    ax.set_xlabel(rmsd_col.replace('_', ' ').title())
    ax.set_ylabel(conf_col.replace('_', ' ').title())
    ax.set_title(f'Design Quality: {rmsd_col} vs {conf_col} (n={len(df)})')

    # Add quadrant guides
    if len(df) > 0:
        rmsd_med = df[rmsd_col].median()
        conf_med = df[conf_col].median()
        ax.axvline(rmsd_med, color='gray', linestyle=':', alpha=0.5)
        ax.axhline(conf_med, color='gray', linestyle=':', alpha=0.5)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved scatter plot: {output_file}")
    return output_file


def plot_amino_acid_composition(output_dir: str,
                                output_file: str = None) -> Optional[str]:
    """Plot amino acid composition of designs.

    Args:
        output_dir: BoltzGen output directory.
        output_file: Path for output PNG.

    Returns:
        str: Path to saved plot, or None if data not available.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    if output_file is None:
        output_file = os.path.join(OUTPUT_DIR, 'aa_composition.png')

    try:
        df = get_design_metrics(output_dir)
    except FileNotFoundError:
        logging.warning("No metrics file found — skipping AA plot")
        return None

    # Find amino acid fraction columns
    aa_cols = [col for col in df.columns
               if col.startswith('design_') and col.endswith(('_fraction', '_ALA', '_GLY',
                                                               '_VAL', '_LEU', '_ILE'))]
    if not aa_cols:
        # Try pattern: single AA codes
        one_letter = list('ACDEFGHIKLMNPQRSTVWY')
        aa_cols = [f'design_{aa}' for aa in one_letter if f'design_{aa}' in df.columns]

    if not aa_cols:
        logging.warning("No amino acid composition columns found")
        return None

    fig, ax = plt.subplots(figsize=(12, 5))
    means = df[aa_cols].mean().sort_values(ascending=False)
    colors = plt.cm.Set3(np.linspace(0, 1, len(means)))
    means.plot(kind='bar', ax=ax, color=colors, edgecolor='black', alpha=0.8)
    ax.set_xlabel('Amino Acid Property')
    ax.set_ylabel('Mean Fraction')
    ax.set_title(f'Average Amino Acid Composition (n={len(df)} designs)')
    plt.xticks(rotation=45, ha='right')

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved AA composition plot: {output_file}")
    return output_file


# ============= STRUCTURE FILE HELPERS =============

def download_pdb(pdb_id: str, output_dir: str = None,
                 file_format: str = 'cif') -> str:
    """Download a structure file from RCSB PDB.

    Args:
        pdb_id: 4-character PDB ID (e.g., '1G13').
        output_dir: Directory to save the file. Defaults to WORK_DIR.
        file_format: 'cif' (mmCIF) or 'pdb'.

    Returns:
        str: Path to downloaded file.
    """
    if output_dir is None:
        output_dir = WORK_DIR

    pdb_id_lower = pdb_id.lower()

    if file_format == 'cif':
        url = f"https://files.rcsb.org/download/{pdb_id_lower}.cif"
        filename = f"{pdb_id_lower}.cif"
    else:
        url = f"https://files.rcsb.org/download/{pdb_id_lower}.pdb"
        filename = f"{pdb_id_lower}.pdb"

    output_path = os.path.join(output_dir, filename)

    result = subprocess.run(
        ['curl', '-sS', '-L', '-o', output_path, url],
        capture_output=True, text=True, timeout=60)

    if result.returncode != 0 or not os.path.exists(output_path):
        raise RuntimeError(f"Failed to download PDB {pdb_id}: {result.stderr}")

    file_size = os.path.getsize(output_path)
    if file_size < 100:
        os.remove(output_path)
        raise RuntimeError(f"Downloaded file too small ({file_size} bytes) — PDB ID may be invalid")

    logging.info(f"Downloaded {pdb_id} → {output_path} ({file_size:,} bytes)")
    return output_path


def list_chains(cif_path: str) -> List[Dict]:
    """List chains in a CIF/PDB file using gemmi.

    Args:
        cif_path: Path to CIF or PDB file.

    Returns:
        List of dicts with chain info: {id, n_residues, entity_type}.
    """
    try:
        import gemmi
        if cif_path.endswith('.cif'):
            doc = gemmi.cif.read(cif_path)
            st = gemmi.make_structure_from_block(doc[0])
        else:
            st = gemmi.read_structure(cif_path)

        chains = []
        for model in st:
            for chain in model:
                n_res = sum(1 for res in chain if res.entity_type == gemmi.EntityType.Polymer
                            or True)
                chains.append({
                    'id': chain.name,
                    'n_residues': len(list(chain)),
                })
        return chains
    except ImportError:
        logging.warning("gemmi not available — cannot list chains")
        return []
    except Exception as e:
        logging.error(f"Error reading {cif_path}: {e}")
        return []


# ============= CLEANUP =============

def boltzgen_cleanup(deep: bool = False):
    """Clean BoltzGen state.

    Args:
        deep: If True, also clear scratch files and GPU cache.
    """
    try:
        if deep:
            _clear_scratch_files()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    logging.info("Cleared CUDA cache")
            except ImportError:
                pass
            logging.info("Deep cleanup completed")
    except Exception as e:
        logging.warning(f"Cleanup warning: {e}")


def _clear_scratch_files():
    """Remove scratch files to recover from I/O corruption."""
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
