#!/usr/bin/env python3
"""MatterGen utilities library for Discovery platform workflows.

Wraps the MatterGen generative model for inorganic crystal structure design.
Provides functions for unconditional, property-conditioned, and composition-
constrained crystal generation with CIF/extxyz output.

Reference: Zeni et al., Nature 2025 (DOI:10.1038/s41586-025-08628-5)
"""
import os
import sys
import glob
import json
import logging
import shutil
import traceback
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Literal

# ============= CONSTANTS =============
INPUT_DIR = "/input"
OUTPUT_DIR = "/output"
WORK_DIR = "/workdir"
SCRATCH_DIR = "/tmp/mattergen_scratch"

PRETRAINED_MODELS = [
    "mattergen_base",
    "mp_20_base",
    "chemical_system",
    "space_group",
    "dft_band_gap",
    "dft_mag_density",
    "ml_bulk_modulus",
    "chemical_system_energy_above_hull",
    "dft_mag_density_hhi_score",
]

# Maps model name to the conditioning properties it supports
MODEL_PROPERTIES = {
    "mattergen_base": [],
    "mp_20_base": [],
    "chemical_system": ["chemical_system"],
    "space_group": ["space_group"],
    "dft_band_gap": ["dft_band_gap"],
    "dft_mag_density": ["dft_mag_density"],
    "ml_bulk_modulus": ["ml_bulk_modulus"],
    "chemical_system_energy_above_hull": ["chemical_system", "energy_above_hull"],
    "dft_mag_density_hhi_score": ["dft_mag_density", "hhi_score"],
}

# Property descriptions for user guidance
PROPERTY_DESCRIPTIONS = {
    "chemical_system": "Target element composition, e.g., 'Si-O' or 'Li-Fe-P-O'",
    "space_group": "Target space group number (1-230), e.g., 225 for Fm-3m",
    "dft_band_gap": "Target electronic band gap in eV, e.g., 1.5",
    "dft_mag_density": "Target magnetic density in Bohr magnetons per atom, e.g., 0.15",
    "ml_bulk_modulus": "Target bulk modulus in GPa, e.g., 200",
    "energy_above_hull": "Target energy above convex hull in eV/atom, e.g., 0.0 for stable",
    "hhi_score": "Herfindahl-Hirschman index for element supply risk (lower = more abundant)",
}


# ============= SETUP FUNCTIONS =============
def quick_setup(input_dir='/input', output_dir='/output', work_dir='/workdir'):
    """Initialize logging, create directories, copy input files.

    Args:
        input_dir: Path to input directory
        output_dir: Path to output directory
        work_dir: Path to working directory
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
    logging.info(f"Input files: {os.listdir(INPUT_DIR) if os.path.exists(INPUT_DIR) else 'none'}")


def _copy_input_files():
    """Copy input files to working directory."""
    if os.path.realpath(INPUT_DIR) == os.path.realpath(WORK_DIR):
        return
    if os.path.exists(INPUT_DIR):
        for f in glob.glob(os.path.join(INPUT_DIR, '*')):
            if os.path.isfile(f):
                shutil.copy(f, WORK_DIR)


def copy_outputs():
    """Copy output files to output directory."""
    if os.path.realpath(WORK_DIR) == os.path.realpath(OUTPUT_DIR):
        return
    patterns = ['*.cif', '*.extxyz', '*.zip', '*.json', '*.png', '*.csv', '*.log']
    for pattern in patterns:
        for f in glob.glob(os.path.join(WORK_DIR, pattern)):
            shutil.copy(f, OUTPUT_DIR)
    logging.info("Outputs copied to /output")


def quick_finish():
    """Copy output files to output directory."""
    copy_outputs()


def save_final_results(
    results: Dict,
    output_files: Dict = None,
    file_descriptions: Dict = None,
    status: str = "completed"
):
    """Save final results to JSON file (MANDATORY for every script).

    Args:
        results: Summary dict with key metrics
        output_files: Dict mapping label to file path
        file_descriptions: Dict mapping label to description
        status: Overall status string
    """
    final_data = {"status": status, "summary": results}
    if output_files:
        final_data["output_files"] = output_files
    if file_descriptions:
        final_data["file_descriptions"] = file_descriptions
    out_path = os.path.join(OUTPUT_DIR, 'final_results.json')
    with open(out_path, 'w') as f:
        json.dump(final_data, f, indent=2, default=str)
    logging.info(f"Saved final_results.json to {out_path}")


# ============= MODEL LOADING =============
def load_generator(
    model_name: str = "mattergen_base",
    batch_size: int = 16,
    num_batches: int = 1,
    properties_to_condition_on: Optional[Dict[str, Any]] = None,
    diffusion_guidance_factor: float = 2.0,
    target_compositions: Optional[List[Dict[str, int]]] = None,
):
    """Load a MatterGen CrystalGenerator from a pretrained model.

    Args:
        model_name: Name of the pretrained model (see PRETRAINED_MODELS).
        batch_size: Number of structures per batch.
        num_batches: Number of batches to generate.
        properties_to_condition_on: Dict of property name to target value
            for conditional generation (e.g., {'dft_band_gap': 1.5}).
        diffusion_guidance_factor: Classifier-free guidance strength.
            Higher values enforce conditioning more strongly. Default 2.0
            for conditional, 0.0 for unconditional.
        target_compositions: List of composition dicts for composition-
            constrained generation, e.g., [{'Si': 2, 'O': 4}].

    Returns:
        CrystalGenerator instance ready to call .generate()
    """
    from mattergen.common.utils.data_classes import MatterGenCheckpointInfo
    from mattergen.generator import CrystalGenerator

    if model_name not in PRETRAINED_MODELS:
        raise ValueError(
            f"Unknown model '{model_name}'. Valid models: {PRETRAINED_MODELS}"
        )

    logging.info(f"Loading model '{model_name}' from HuggingFace Hub...")
    checkpoint_info = MatterGenCheckpointInfo.from_hf_hub(model_name)

    # If no conditioning requested for a base model, set guidance to 0
    if properties_to_condition_on is None or len(properties_to_condition_on) == 0:
        if model_name in ("mattergen_base", "mp_20_base"):
            diffusion_guidance_factor = 0.0

    generator = CrystalGenerator(
        checkpoint_info=checkpoint_info,
        batch_size=batch_size,
        num_batches=num_batches,
        properties_to_condition_on=properties_to_condition_on,
        diffusion_guidance_factor=diffusion_guidance_factor,
        target_compositions_dict=target_compositions,
    )

    logging.info(f"Generator loaded: model={model_name}, "
                 f"batch_size={batch_size}, num_batches={num_batches}, "
                 f"guidance={diffusion_guidance_factor}")
    return generator


def generate_structures(
    model_name: str = "mattergen_base",
    batch_size: int = 16,
    num_batches: int = 1,
    properties_to_condition_on: Optional[Dict[str, Any]] = None,
    diffusion_guidance_factor: float = 2.0,
    target_compositions: Optional[List[Dict[str, int]]] = None,
    output_dir: Optional[str] = None,
) -> List:
    """Generate crystal structures using MatterGen.

    This is the main high-level function. It loads the model, runs generation,
    and returns a list of pymatgen Structure objects.

    Args:
        model_name: Pretrained model name (see PRETRAINED_MODELS).
        batch_size: Structures per batch. Increase for better GPU utilization.
        num_batches: Number of batches. Total structures = batch_size * num_batches.
        properties_to_condition_on: Property conditioning dict.
        diffusion_guidance_factor: Guidance strength (default 2.0 for conditional).
        target_compositions: Composition constraints.
        output_dir: Where to save CIF/extxyz files. Defaults to WORK_DIR.

    Returns:
        List of pymatgen.core.structure.Structure objects.
    """
    if output_dir is None:
        output_dir = WORK_DIR

    generator = load_generator(
        model_name=model_name,
        batch_size=batch_size,
        num_batches=num_batches,
        properties_to_condition_on=properties_to_condition_on,
        diffusion_guidance_factor=diffusion_guidance_factor,
        target_compositions=target_compositions,
    )

    logging.info(f"Generating {batch_size * num_batches} structures...")
    structures = generator.generate(
        batch_size=batch_size,
        num_batches=num_batches,
        target_compositions_dict=target_compositions,
        output_dir=output_dir,
    )
    logging.info(f"Generated {len(structures)} structures")
    return structures


# ============= OUTPUT FUNCTIONS =============
def structures_to_cif(
    structures: List,
    output_dir: Optional[str] = None,
    prefix: str = "gen",
) -> List[str]:
    """Save structures as individual CIF files.

    Args:
        structures: List of pymatgen Structure objects.
        output_dir: Output directory. Defaults to OUTPUT_DIR.
        prefix: Filename prefix (e.g., 'gen' -> gen_000.cif).

    Returns:
        List of paths to saved CIF files.
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)

    cif_paths = []
    for i, struct in enumerate(structures):
        cif_path = os.path.join(output_dir, f"{prefix}_{i:03d}.cif")
        struct.to(filename=cif_path, fmt="cif")
        cif_paths.append(cif_path)
    logging.info(f"Saved {len(cif_paths)} CIF files to {output_dir}")
    return cif_paths


def structures_to_summary(structures: List) -> List[Dict]:
    """Extract summary information from generated structures.

    Args:
        structures: List of pymatgen Structure objects.

    Returns:
        List of dicts with formula, space_group, num_atoms, volume,
        density, lattice parameters.
    """
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    summaries = []
    for i, struct in enumerate(structures):
        try:
            sga = SpacegroupAnalyzer(struct, symprec=0.1)
            sg_symbol = sga.get_space_group_symbol()
            sg_number = sga.get_space_group_number()
        except Exception:
            sg_symbol = "unknown"
            sg_number = -1

        summaries.append({
            "index": i,
            "formula": struct.composition.reduced_formula,
            "num_atoms": len(struct),
            "space_group_symbol": sg_symbol,
            "space_group_number": sg_number,
            "volume_A3": round(struct.volume, 2),
            "density_g_cm3": round(struct.density, 4),
            "a": round(struct.lattice.a, 4),
            "b": round(struct.lattice.b, 4),
            "c": round(struct.lattice.c, 4),
            "alpha": round(struct.lattice.alpha, 2),
            "beta": round(struct.lattice.beta, 2),
            "gamma": round(struct.lattice.gamma, 2),
        })
    return summaries


def save_summary_csv(summaries: List[Dict], output_path: Optional[str] = None) -> str:
    """Save structure summaries to a CSV file.

    Args:
        summaries: List of summary dicts from structures_to_summary().
        output_path: Path for CSV file. Defaults to OUTPUT_DIR/summary.csv.

    Returns:
        Path to the saved CSV file.
    """
    import pandas as pd

    if output_path is None:
        output_path = os.path.join(OUTPUT_DIR, "summary.csv")
    df = pd.DataFrame(summaries)
    df.to_csv(output_path, index=False)
    logging.info(f"Saved summary CSV to {output_path}")
    return output_path


# ============= ANALYSIS FUNCTIONS =============
def analyze_composition_diversity(structures: List) -> Dict:
    """Analyze the chemical diversity of generated structures.

    Args:
        structures: List of pymatgen Structure objects.

    Returns:
        Dict with unique_formulas, unique_elements, element_counts,
        formula_counts, average_num_elements.
    """
    from collections import Counter

    formulas = [s.composition.reduced_formula for s in structures]
    elements = set()
    num_elements_list = []
    for s in structures:
        elems = [str(e) for e in s.composition.elements]
        elements.update(elems)
        num_elements_list.append(len(elems))

    element_counts = Counter()
    for s in structures:
        for e in s.composition.elements:
            element_counts[str(e)] += 1

    return {
        "num_structures": len(structures),
        "unique_formulas": len(set(formulas)),
        "unique_elements": len(elements),
        "elements": sorted(list(elements)),
        "top_formulas": dict(Counter(formulas).most_common(10)),
        "top_elements": dict(element_counts.most_common(10)),
        "avg_num_elements": round(sum(num_elements_list) / len(num_elements_list), 2)
            if num_elements_list else 0,
    }


def analyze_lattice_statistics(structures: List) -> Dict:
    """Compute lattice parameter statistics for generated structures.

    Args:
        structures: List of pymatgen Structure objects.

    Returns:
        Dict with statistics for volume, density, lattice parameters.
    """
    import numpy as np

    volumes = [s.volume for s in structures]
    densities = [s.density for s in structures]
    a_vals = [s.lattice.a for s in structures]
    b_vals = [s.lattice.b for s in structures]
    c_vals = [s.lattice.c for s in structures]
    num_atoms = [len(s) for s in structures]

    def _stats(values, name):
        arr = np.array(values)
        return {
            f"{name}_mean": round(float(np.mean(arr)), 4),
            f"{name}_std": round(float(np.std(arr)), 4),
            f"{name}_min": round(float(np.min(arr)), 4),
            f"{name}_max": round(float(np.max(arr)), 4),
        }

    result = {}
    result.update(_stats(volumes, "volume_A3"))
    result.update(_stats(densities, "density_g_cm3"))
    result.update(_stats(a_vals, "a"))
    result.update(_stats(b_vals, "b"))
    result.update(_stats(c_vals, "c"))
    result.update(_stats(num_atoms, "num_atoms"))
    return result


# ============= VISUALIZATION =============
def plot_lattice_distribution(
    structures: List,
    output_file: Optional[str] = None,
    title: str = "Generated Structure Lattice Parameters",
) -> str:
    """Plot distributions of lattice parameters for generated structures.

    Args:
        structures: List of pymatgen Structure objects.
        output_file: Path for output PNG. Defaults to OUTPUT_DIR/lattice_dist.png.
        title: Plot title.

    Returns:
        Path to saved plot.
    """
    import matplotlib.pyplot as plt
    import numpy as np

    if output_file is None:
        output_file = os.path.join(OUTPUT_DIR, "lattice_dist.png")

    volumes = [s.volume for s in structures]
    densities = [s.density for s in structures]
    num_atoms = [len(s) for s in structures]

    fig, axes = plt.subplots(1, 3, figsize=(15, 4))

    axes[0].hist(volumes, bins=20, color='steelblue', edgecolor='white')
    axes[0].set_xlabel('Volume (A^3)')
    axes[0].set_ylabel('Count')
    axes[0].set_title('Volume Distribution')

    axes[1].hist(densities, bins=20, color='coral', edgecolor='white')
    axes[1].set_xlabel('Density (g/cm^3)')
    axes[1].set_title('Density Distribution')

    axes[2].hist(num_atoms, bins=range(1, max(num_atoms) + 2),
                 color='seagreen', edgecolor='white')
    axes[2].set_xlabel('Number of Atoms')
    axes[2].set_title('Atom Count Distribution')

    fig.suptitle(title, fontsize=14)
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved lattice distribution plot to {output_file}")
    return output_file


def plot_element_frequency(
    structures: List,
    output_file: Optional[str] = None,
    top_n: int = 20,
) -> str:
    """Plot element frequency bar chart for generated structures.

    Args:
        structures: List of pymatgen Structure objects.
        output_file: Output path. Defaults to OUTPUT_DIR/element_freq.png.
        top_n: Number of top elements to show.

    Returns:
        Path to saved plot.
    """
    import matplotlib.pyplot as plt
    from collections import Counter

    if output_file is None:
        output_file = os.path.join(OUTPUT_DIR, "element_freq.png")

    element_counts = Counter()
    for s in structures:
        for e in s.composition.elements:
            element_counts[str(e)] += 1

    top_elements = element_counts.most_common(top_n)
    if not top_elements:
        logging.warning("No elements found in structures")
        return output_file

    elems, counts = zip(*top_elements)

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(elems, counts, color='steelblue', edgecolor='white')
    ax.set_xlabel('Element')
    ax.set_ylabel('Frequency')
    ax.set_title(f'Top {top_n} Element Frequencies ({len(structures)} structures)')
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()
    logging.info(f"Saved element frequency plot to {output_file}")
    return output_file


# ============= UTILITY HELPERS =============
def select_model_for_property(property_name: str) -> str:
    """Given a property name, return the best pretrained model.

    Args:
        property_name: One of the supported property names.

    Returns:
        Model name string.

    Raises:
        ValueError: If no model supports the given property.
    """
    for model, props in MODEL_PROPERTIES.items():
        if property_name in props and len(props) == 1:
            return model
    # Check multi-property models
    for model, props in MODEL_PROPERTIES.items():
        if property_name in props:
            return model
    raise ValueError(
        f"No model supports property '{property_name}'. "
        f"Supported properties: {list(PROPERTY_DESCRIPTIONS.keys())}"
    )


def validate_model_name(model_name: str) -> bool:
    """Check if a model name is valid.

    Args:
        model_name: Name to check.

    Returns:
        True if valid.

    Raises:
        ValueError: If invalid.
    """
    if model_name not in PRETRAINED_MODELS:
        raise ValueError(
            f"Unknown model '{model_name}'. Valid: {PRETRAINED_MODELS}"
        )
    return True


def list_models() -> List[Dict[str, Any]]:
    """List all available pretrained models with their properties.

    Returns:
        List of dicts with model name, supported properties, and descriptions.
    """
    result = []
    for model in PRETRAINED_MODELS:
        props = MODEL_PROPERTIES.get(model, [])
        result.append({
            "model_name": model,
            "conditioning_properties": props,
            "property_descriptions": {
                p: PROPERTY_DESCRIPTIONS.get(p, "") for p in props
            },
            "is_base_model": len(props) == 0,
        })
    return result


def tool_cleanup(deep: bool = False):
    """Clean up temporary files and state.

    Args:
        deep: If True, also clear scratch files.
    """
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
