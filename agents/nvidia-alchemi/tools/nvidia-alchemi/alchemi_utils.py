#!/usr/bin/env python3
"""NVIDIA ALCHEMI Toolkit utilities library for Discovery platform workflows.

Wraps `nvalchemi` (https://github.com/NVIDIA/nvalchemi-toolkit) for GPU-first,
batched AI atomic simulation: machine-learned interatomic potential (MLIP)
relaxation, molecular dynamics, multi-stage pipelines, high-throughput screening
with inflight batching, Zarr trajectory capture, training / fine-tuning, and
multi-GPU execution.

Every call pattern here was validated against nvalchemi 0.2.0 inside the agent
container. Gotchas this library handles for you:

* Dynamics reads and writes per-step buffers (`forces`, `energy`, `velocities`,
  and `stress` for barostats). `AtomicData.from_atoms()` does NOT allocate them,
  and a missing buffer surfaces as `AttributeError: 'Batch' has no attribute
  'forces'`. `atoms_to_batch()` allocates them up front.
* `convergence_hook` is its own constructor argument -- passing a
  `ConvergenceHook` inside `hooks=[...]` silently never converges.
* Inflight batching is Mode 2 of `FusedStage.run(None)` driven by a `sampler`,
  not a plain optimizer feature. `SizeAwareSampler` needs a dataset exposing
  `get_metadata(idx)`, so a bare list will not do -- wrap it in `InMemoryDataset`.
* Classical potentials take required physical parameters (epsilon/sigma/cutoff,
  a1/a2/s8, cutoff), so `load_model()` supplies documented defaults.

License: this wrapper is part of the Discovery catalog. See THIRD_PARTY_NOTICES.md
for the licenses of nvalchemi-toolkit, MACE, AIMNet2 and the CUDA base image.
"""
import glob
import importlib
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from alchemi_artifacts import export_artifacts, to_jsonable, write_json_atomic

HELPER_VERSION = "1.1.4"
_DECLARED_OUTPUTS: Dict[str, Any] = {}
_FINAL_DATA: Optional[Dict[str, Any]] = None

# ============= CONSTANTS =============
INPUT_DIR = "/input"
OUTPUT_DIR = "/output"
WORK_DIR = "/workdir"
SCRATCH_DIR = "/tmp/alchemi_scratch"

# Structure file extensions ASE can read, in the order globbed by load_structures().
STRUCTURE_EXTENSIONS = (
    "*.xyz", "*.extxyz", "*.cif", "*.pdb", "*.poscar", "POSCAR*", "CONTCAR*",
    "*.traj", "*.vasp",
)

# Potentials wrapped by the toolkit: name -> (module path, wrapper class name).
MODEL_REGISTRY: Dict[str, Tuple[str, str]] = {
    "mace": ("nvalchemi.models.mace", "MACEWrapper"),
    "aimnet2": ("nvalchemi.models.aimnet2", "AIMNet2Wrapper"),
    "lj": ("nvalchemi.models.lj", "LennardJonesModelWrapper"),
    "dftd3": ("nvalchemi.models.dftd3", "DFTD3ModelWrapper"),
    "ewald": ("nvalchemi.models.ewald", "EwaldModelWrapper"),
    "pme": ("nvalchemi.models.pme", "PMEModelWrapper"),
    "demo": ("nvalchemi.models.demo", "DemoModelWrapper"),
}

MODEL_DESCRIPTIONS: Dict[str, str] = {
    "mace": "MACE equivariant MLIP. Foundation checkpoints 'small-0b' and "
            "'medium-0b2' are baked into the image. Energy/forces/stress, PBC, "
            "COO neighbor list. Default choice for materials and periodic systems.",
    "aimnet2": "AIMNet2 MLIP for neutral, charged, organic and elemental-organic "
               "molecules. Predicts partial charges alongside energy/forces; "
               "MATRIX neighbor list. Checkpoint name: 'aimnet2'.",
    "lj": "Lennard-Jones analytical force field. Cheap; smoke tests, toy systems "
          "and validation. Requires epsilon, sigma and cutoff.",
    "dftd3": "DFT-D3(BJ) dispersion correction. Additive term -- compose onto an "
             "MLIP with compose_models(). Requires the a1/a2/s8 damping "
             "parameters of the target functional.",
    "ewald": "Ewald summation for long-range electrostatics. Needs per-atom "
             "`charges` and periodic cells.",
    "pme": "Particle Mesh Ewald electrostatics; O(N log N) alternative to Ewald "
           "for large periodic systems.",
    "demo": "Trivial non-invariant demo potential. Testing and tutorials only -- "
            "not physically meaningful.",
}

# Documented default parameters for the classical potentials, which take
# required physical arguments rather than having built-in defaults.
# LJ defaults are argon; DFT-D3(BJ) defaults are the PBE damping set.
MODEL_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "lj": {"epsilon": 0.0104, "sigma": 3.4, "cutoff": 8.5},
    "dftd3": {"a1": 0.4289, "a2": 4.4407, "s8": 0.7875, "cutoff": 15.0},
    "ewald": {"cutoff": 10.0},
    "pme": {"cutoff": 10.0},
}

# Optimizers and integrators, resolved from `nvalchemi.dynamics`.
OPTIMIZERS: Dict[str, str] = {
    "fire": "FIRE",
    "fire2": "FIRE2",
    "fire_variable_cell": "FIREVariableCell",
    "fire2_variable_cell": "FIRE2VariableCell",
}
ENSEMBLES: Dict[str, str] = {
    "nve": "NVE",
    "nvt": "NVTLangevin",
    "nvt_langevin": "NVTLangevin",
    "nvt_nose_hoover": "NVTNoseHoover",
    "npt": "NPT",
    "nph": "NPH",
}

# Runs whose integrator or optimizer needs the stress tensor from the model.
STRESS_REQUIRING = frozenset({"npt", "nph", "fire_variable_cell",
                              "fire2_variable_cell"})


# ============= SETUP FUNCTIONS =============
def quick_setup(input_dir: str = "/input", output_dir: str = "/output",
                work_dir: str = "/workdir") -> None:
    """Initialize logging, create directories, copy input files.

    Args:
        input_dir: Path to input directory (read-only by convention).
        output_dir: Path to output directory.
        work_dir: Path to working directory; becomes the process CWD.
    """
    global INPUT_DIR, OUTPUT_DIR, WORK_DIR, _DECLARED_OUTPUTS, _FINAL_DATA
    INPUT_DIR, OUTPUT_DIR, WORK_DIR = input_dir, output_dir, work_dir
    _DECLARED_OUTPUTS, _FINAL_DATA = {}, None

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(SCRATCH_DIR, exist_ok=True)
    os.chdir(WORK_DIR)
    _copy_input_files()
    logging.info(f"Working directory: {WORK_DIR}")
    logging.info(
        f"Input files: {os.listdir(INPUT_DIR) if os.path.exists(INPUT_DIR) else 'none'}"
    )
    log_gpu_info()


def _copy_input_files() -> None:
    """Copy input files to working directory."""
    if os.path.realpath(INPUT_DIR) == os.path.realpath(WORK_DIR):
        return
    if os.path.exists(INPUT_DIR):
        for f in glob.glob(os.path.join(INPUT_DIR, "*")):
            if os.path.isfile(f):
                shutil.copy(f, WORK_DIR)


def copy_outputs() -> Dict[str, str]:
    """Re-export and verify declared artifacts, including any updated files.

    If no result has been saved, retain legacy discovery of common artifacts.
    Explicit declarations accept ANY extension and are never filtered. Once
    save_final_results() is used, declare everything to be delivered; unlisted
    scratch files are intentionally not exported. Destination paths and hashes
    are recorded in artifact_manifest.json, not working-directory paths.
    """
    if _FINAL_DATA is not None:
        return _publish_results(_FINAL_DATA, _DECLARED_OUTPUTS)
    patterns = ("*.xyz", "*.extxyz", "*.cif", "*.csv", "*.json", "*.png",
                "*.log", "*.pt", "*.zip", "*.npz", "*.npy", "*.py", "*.txt",
                "*.zarr", "checkpoints*")
    files = {}
    for pattern in patterns:
        for f in glob.glob(os.path.join(WORK_DIR, pattern)):
            if Path(f).name not in {"final_results.json", "artifact_manifest.json"}:
                files[Path(f).name] = f
    mapped, manifest = export_artifacts(files, WORK_DIR, OUTPUT_DIR)
    write_json_atomic(Path(OUTPUT_DIR) / "artifact_manifest.json", manifest)
    return mapped


def quick_finish() -> None:
    """Finalize artifact delivery. Raises on missing/corrupt declared evidence."""
    copy_outputs()


def save_final_results(results: Dict, output_files: Optional[Dict] = None,
                       file_descriptions: Optional[Dict] = None,
                       status: str = "completed") -> Dict[str, str]:
    """Export declared evidence, verify it, and save strict JSON results.

    Args:
        results: Summary dict with key metrics.
        output_files: Labels mapped to existing source paths, relative to WORK_DIR
            or absolute. All extensions and directories are supported. Returns
            mapped destination paths under OUTPUT_DIR. A later save with None
            retains the declarations; an explicit empty dict clears them.
        file_descriptions: Dict mapping label to description.
        status: Overall status string ("completed" or "failed").

    Nonfinite floats become explicit diagnostic objects, never invalid JSON.
    Export/serialization failures publish a failed result and raise; merely
    listing a source path never counts as evidence delivery. quick_finish()
    re-verifies declared evidence after final log/trajectory writes.
    """
    global _DECLARED_OUTPUTS, _FINAL_DATA
    if status not in {"completed", "failed"}:
        raise ValueError("status must be 'completed' or 'failed'")
    if output_files is not None:
        _DECLARED_OUTPUTS = dict(output_files)
    _FINAL_DATA = {"status": status, "summary": results,
                   "helper_version": HELPER_VERSION,
                   "file_descriptions": file_descriptions or {}}
    return _publish_results(_FINAL_DATA, _DECLARED_OUTPUTS)


def _publish_results(final_data: Dict, declarations: Dict) -> Dict[str, str]:
    try:
        clean = to_jsonable(final_data)
        mapped, manifest = export_artifacts(declarations, WORK_DIR, OUTPUT_DIR)
        clean["output_files"] = mapped
        clean["artifact_manifest"] = str(Path(OUTPUT_DIR).resolve() / "artifact_manifest.json")
        write_json_atomic(Path(OUTPUT_DIR) / "artifact_manifest.json", manifest)
        write_json_atomic(Path(OUTPUT_DIR) / "final_results.json", clean)
        # Logging here could mutate an already-hashed, still-open declared log.
        return mapped
    except Exception as exc:
        final_data["status"] = "failed"
        failure = {"status": "failed", "helper_version": HELPER_VERSION,
                   "summary": {"artifact_or_serialization_error": str(exc)},
                   "output_files": {}}
        write_json_atomic(Path(OUTPUT_DIR) / "artifact_manifest.json",
                          {"schema_version": 1, "artifacts": [], "error": str(exc)})
        write_json_atomic(Path(OUTPUT_DIR) / "final_results.json", failure)
        raise


# ============= SYMBOL RESOLUTION =============
def _resolve(module_path: str, name: str) -> Any:
    """Return `name` from `module_path` with an actionable error on failure.

    The toolkit is a public beta, so a moved symbol should produce a message
    naming the installed version rather than a bare ImportError.
    """
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ImportError(
            f"Could not import '{module_path}' ({exc}). Check the installed "
            'version with `python -c "import nvalchemi; '
            'print(nvalchemi.__version__)"`.'
        ) from exc
    if not hasattr(module, name):
        available = [n for n in dir(module) if not n.startswith("_")]
        raise ImportError(
            f"'{module_path}' has no attribute '{name}'. Available: {available}"
        )
    return getattr(module, name)


def log_gpu_info() -> Dict[str, Any]:
    """Log and return CUDA device information. Warns loudly if no GPU is present."""
    import torch

    info = {
        "cuda_available": torch.cuda.is_available(),
        "device_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
        "torch_version": torch.__version__,
    }
    if info["cuda_available"]:
        info["devices"] = [
            torch.cuda.get_device_name(i) for i in range(info["device_count"])
        ]
        logging.info(f"CUDA devices: {info['devices']}")
    else:
        logging.warning(
            "No CUDA device detected. The ALCHEMI Toolkit is GPU-first and has no "
            "CPU fallback for its accelerated kernels -- request a GPU nodepool."
        )
    return info


def default_device() -> str:
    """Return 'cuda' when a GPU is present, otherwise 'cpu'."""
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def gpu_count() -> int:
    """Number of visible CUDA devices."""
    import torch

    return torch.cuda.device_count() if torch.cuda.is_available() else 0


# ============= STRUCTURE I/O =============
def load_structures(path: Optional[str] = None, index: str = ":") -> List[Any]:
    """Read structures from a file, glob pattern, or directory into `ase.Atoms`.

    Args:
        path: File, glob pattern, or directory. Defaults to the working directory.
        index: ASE slice string; ':' reads every frame of multi-frame files.

    Returns:
        List of `ase.Atoms`.
    """
    from ase.io import read

    target = path or WORK_DIR
    if os.path.isdir(target):
        files: List[str] = []
        for pattern in STRUCTURE_EXTENSIONS:
            files.extend(sorted(glob.glob(os.path.join(target, pattern))))
    else:
        files = sorted(glob.glob(target)) or [target]

    atoms_list: List[Any] = []
    for f in files:
        if not os.path.isfile(f):
            continue
        frames = read(f, index=index)
        atoms_list.extend(frames if isinstance(frames, list) else [frames])

    if not atoms_list:
        raise FileNotFoundError(f"No readable structures found at '{target}'.")
    logging.info(f"Loaded {len(atoms_list)} structure(s) from {len(files)} file(s)")
    return atoms_list


def prepare_data(atoms: Any, device: Optional[str] = None,
                 need_stress: bool = False, dtype: Optional[Any] = None) -> Any:
    """Convert one `ase.Atoms` to `AtomicData` WITH the per-step buffers allocated.

    Dynamics reads and writes `forces`, `energy` and `velocities` in place, and
    barostats additionally need `stress`. `AtomicData.from_atoms()` leaves these
    unset, which fails at the first step with
    `AttributeError: 'Batch' has no attribute 'forces'`.
    """
    import torch

    AtomicData = _resolve("nvalchemi.data", "AtomicData")
    device = device or default_device()
    dtype = dtype or torch.float32

    data = AtomicData.from_atoms(atoms, device=device, dtype=dtype)
    n = len(atoms)
    if getattr(data, "forces", None) is None:
        data.forces = torch.zeros(n, 3, device=device, dtype=dtype)
    if getattr(data, "energy", None) is None:
        data.energy = torch.zeros(1, 1, device=device, dtype=dtype)
    if getattr(data, "velocities", None) is None:
        data.velocities = torch.zeros(n, 3, device=device, dtype=dtype)
    if need_stress and getattr(data, "stress", None) is None:
        data.stress = torch.zeros(1, 3, 3, device=device, dtype=dtype)
    for key in ("system_id", "input_index"):
        if key in atoms.info:
            value = atoms.info[key]
            import numbers
            if isinstance(value, bool) or not isinstance(value, numbers.Integral) or value < 0:
                raise ValueError(f"atoms.info[{key!r}] must be a nonnegative integer")
            data.add_system_property(key, torch.tensor([[int(value)]], device=device, dtype=torch.long))
    return data


def atoms_to_batch(atoms_list: Sequence[Any], device: Optional[str] = None,
                   need_stress: bool = False, dtype: Optional[Any] = None) -> Any:
    """Convert `ase.Atoms` objects into a single GPU-resident `Batch`.

    Buffers required by dynamics are allocated for you -- see `prepare_data`.

    Args:
        atoms_list: Structures to batch. A single Atoms object is accepted.
        device: Target device; defaults to 'cuda' when available.
        need_stress: Allocate the stress buffer (required for NPT/NPH and
            variable-cell relaxation).
        dtype: Torch dtype for the tensors.

    Returns:
        `nvalchemi.data.Batch`
    """
    Batch = _resolve("nvalchemi.data", "Batch")

    if not isinstance(atoms_list, (list, tuple)):
        atoms_list = [atoms_list]
    device = device or default_device()
    data_list = [prepare_data(a, device=device, need_stress=need_stress, dtype=dtype)
                 for a in atoms_list]
    batch = Batch.from_data_list(data_list)
    logging.info(
        f"Built batch: {batch.num_graphs} structures, {batch.num_nodes} atoms "
        f"on {device}"
    )
    return batch


def batch_to_atoms(batch: Any) -> List[Any]:
    """Convert a `Batch` (or `AtomicData`) back to `ase.Atoms`.

    The toolkit has no upstream `to_atoms`, because which fields to carry back is
    application-specific. This helper restores positions, numbers, cell and pbc,
    and attaches energy / forces / stress to `info` and `arrays` when present.
    system_id and input_index are preserved in atoms.info. Toolkit velocities
    are retained as atoms.arrays['alchemi_velocities'] in toolkit native units;
    they are NOT silently interpreted as ASE velocity units.
    """
    from ase import Atoms

    data_list = batch.to_data_list() if hasattr(batch, "to_data_list") else [batch]
    identities = {}
    for key in ("system_id", "input_index"):
        values = getattr(batch, key, None)
        if values is not None:
            import torch
            if values.dtype not in (torch.int32, torch.int64) or values.numel() != len(data_list):
                raise ValueError(f"Expected one integer {key} per graph")
            identities[key] = values.detach().cpu().reshape(-1).tolist()
    out: List[Any] = []
    for index, data in enumerate(data_list):
        cell_value = getattr(data, "cell", None)
        pbc_value = getattr(data, "pbc", None)
        cell = cell_value.squeeze(0).detach().cpu().numpy() if cell_value is not None else None
        pbc = pbc_value.squeeze(0).detach().cpu().numpy() if pbc_value is not None else False
        atoms = Atoms(
            numbers=data.atomic_numbers.cpu().numpy(),
            positions=data.positions.detach().cpu().numpy(),
            cell=cell,
            pbc=pbc,
        )
        if getattr(data, "energy", None) is not None:
            atoms.info["energy"] = float(data.energy.detach().cpu().reshape(-1)[0])
        if getattr(data, "forces", None) is not None:
            atoms.arrays["forces"] = data.forces.detach().cpu().numpy()
        if getattr(data, "stress", None) is not None:
            atoms.info["stress"] = data.stress.detach().cpu().numpy().reshape(3, 3)
        if getattr(data, "atomic_masses", None) is not None:
            atoms.set_masses(data.atomic_masses.detach().cpu().numpy())
        if getattr(data, "velocities", None) is not None:
            atoms.arrays["alchemi_velocities"] = data.velocities.detach().cpu().numpy().copy()
        for key, values in identities.items():
            atoms.info[key] = int(values[index])
        out.append(atoms)
    return out


def write_structures(batch_or_atoms: Any, output_path: str = "structures.extxyz",
                     fmt: Optional[str] = None) -> str:
    """Write a `Batch` or list of `ase.Atoms` to disk.

    Args:
        batch_or_atoms: A `Batch`, `AtomicData`, a single `ase.Atoms`, or a list
            of `ase.Atoms`.
        output_path: Destination path (relative paths land in the work directory).
        fmt: Explicit ASE format; inferred from the extension when omitted.

    Returns:
        Absolute path of the written file.
    """
    from ase import Atoms
    from ase.io import write

    if isinstance(batch_or_atoms, Atoms):
        atoms_list = [batch_or_atoms]
    elif isinstance(batch_or_atoms, (list, tuple)):
        atoms_list = list(batch_or_atoms)
    else:
        atoms_list = batch_to_atoms(batch_or_atoms)

    path = output_path if os.path.isabs(output_path) else os.path.join(WORK_DIR, output_path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    write(path, atoms_list, format=fmt)
    logging.info(f"Wrote {len(atoms_list)} structure(s) to {path}")
    return path


def freeze_atoms_by_tag(data_or_batch: Any, tags: Any, free_tag: int = 0) -> Any:
    """Mark atoms whose ASE tag differs from `free_tag` as frozen.

    Sets `atom_categories` to `AtomCategory.SPECIAL`, which is what
    `FreezeAtomsHook` acts on. Typical use: hold a slab fixed while an adsorbate
    relaxes. Register `FreezeAtomsHook()` on the dynamics for this to take effect.
    """
    import torch

    AtomCategory = _resolve("nvalchemi._typing", "AtomCategory")
    device = data_or_batch.positions.device
    tag_tensor = torch.as_tensor(tags, device=device)
    data_or_batch.atom_categories = torch.where(
        tag_tensor != free_tag,
        torch.tensor(AtomCategory.SPECIAL.value, device=device),
        torch.tensor(AtomCategory.GAS.value, device=device),
    )
    return data_or_batch


# ============= MODELS =============
def list_models() -> List[Dict[str, str]]:
    """Return the catalog of available potentials with their descriptions."""
    return [{"name": k, "description": MODEL_DESCRIPTIONS[k]} for k in MODEL_REGISTRY]


def load_model(name: str = "mace", checkpoint: Optional[str] = None,
               device: Optional[str] = None, dtype: Optional[Any] = None,
               enable_cueq: bool = True, **kwargs: Any) -> Any:
    """Load a wrapped interatomic potential.

    Args:
        name: One of `MODEL_REGISTRY` -- 'mace', 'aimnet2', 'lj', 'dftd3',
            'ewald', 'pme', 'demo'.
        checkpoint: Checkpoint name for the learned potentials. Defaults to
            'small-0b' for MACE ('medium-0b2' is also baked in) and 'aimnet2'
            for AIMNet2. Ignored by the classical models.
        device: Target device; defaults to 'cuda' when available.
        dtype: Torch dtype for the model weights.
        enable_cueq: Enable cuEquivariance fused convolutions for MACE. Applied
            only on CUDA, where the kernels exist.
        **kwargs: Override the physical parameters of the classical models --
            `epsilon`/`sigma`/`cutoff` for 'lj', `a1`/`a2`/`s8` for 'dftd3',
            `cutoff` for 'ewald'/'pme'. See `MODEL_DEFAULTS`.

    Returns:
        A `BaseModelMixin` wrapper ready for dynamics or composition.
    """
    import torch

    key = name.lower()
    if key not in MODEL_REGISTRY:
        raise ValueError(
            f"Unknown model '{name}'. Available: {sorted(MODEL_REGISTRY)}"
        )
    module_path, class_name = MODEL_REGISTRY[key]
    wrapper_cls = _resolve(module_path, class_name)

    device = device or default_device()
    dtype = dtype or torch.float32

    if key == "mace":
        model = wrapper_cls.from_checkpoint(
            checkpoint or "small-0b",
            device=torch.device(device),
            dtype=dtype,
            enable_cueq=enable_cueq and str(device).startswith("cuda"),
            **kwargs,
        )
    elif key == "aimnet2":
        model = wrapper_cls.from_checkpoint(
            checkpoint or "aimnet2", device=torch.device(device), **kwargs
        )
    else:
        params = dict(MODEL_DEFAULTS.get(key, {}))
        params.update(kwargs)
        model = wrapper_cls(**params)
        model = model.to(device=torch.device(device))
        if params:
            logging.info(f"'{key}' parameters: {params}")

    logging.info(f"Loaded model '{key}' on {device}")
    return model


def compose_models(*models: Any, use_autograd: bool = False,
                   neighbor_adaptation: str = "auto") -> Any:
    """Combine potentials into a single composed model.

    Args:
        *models: Two or more wrapped models, in evaluation order.
        use_autograd: When True, sum the sub-model energies and differentiate the
            total. Required when one model's output feeds another's energy (for
            example AIMNet2 charges -> Ewald electrostatics) and forces must
            backpropagate through the whole chain. When False, each model
            computes its own forces and the results are summed -- correct for
            independent additive terms such as MACE + DFT-D3.
        neighbor_adaptation: 'auto', 'always' or 'never'.

    Returns:
        A composed model exposing the same interface as a single wrapper.
    """
    if len(models) < 2:
        raise ValueError("compose_models() needs at least two models.")

    if not use_autograd:
        composed = models[0]
        for m in models[1:]:
            composed = composed + m
        logging.info(f"Composed {len(models)} models with the '+' operator")
        return composed

    PipelineModelWrapper = _resolve("nvalchemi.models.pipeline",
                                    "PipelineModelWrapper")
    PipelineGroup = _resolve("nvalchemi.models.pipeline", "PipelineGroup")
    composed = PipelineModelWrapper(
        groups=[PipelineGroup(steps=list(models), use_autograd=True)],
        neighbor_adaptation=neighbor_adaptation,
    )
    logging.info(f"Composed {len(models)} models into a shared-autograd pipeline")
    return composed


def set_active_outputs(model: Any, outputs: Iterable[str]) -> Any:
    """Set which properties the model computes on each forward pass.

    Narrow to `{'energy'}` for screening, and include `'stress'` before running
    NPT/NPH or variable-cell relaxation.
    """
    model.model_config.active_outputs = set(outputs)
    logging.info(f"active_outputs = {sorted(model.model_config.active_outputs)}")
    return model


def attach_neighbor_hooks(dynamics: Any, model: Any, **kwargs: Any) -> Any:
    """Register every neighbor-list hook the model (or pipeline) requires.

    Always use this rather than building a `NeighborListHook` by hand: a composed
    model may need several source lists at different cutoffs, and a missing hook
    shows up as NaN or zero forces rather than a clear error.
    """
    DynamicsStage = _resolve("nvalchemi.dynamics", "DynamicsStage")
    hooks = list(model.make_neighbor_hooks(**kwargs))
    for hook in hooks:
        dynamics.register_hook(hook, stage=DynamicsStage.BEFORE_COMPUTE)
    logging.info(f"Registered {len(hooks)} neighbor-list hook(s)")
    return dynamics


# ============= DYNAMICS =============
def _ensure_stress(model: Any) -> None:
    """Add 'stress' to the model's active outputs if the run needs it."""
    cfg = model.model_config
    active = set(getattr(cfg, "active_outputs", None) or cfg.outputs)
    if "stress" not in active:
        if "stress" not in set(cfg.outputs):
            raise ValueError(
                f"This run needs the stress tensor, but the model only supports "
                f"{sorted(cfg.outputs)}. Choose a potential that computes stress."
            )
        set_active_outputs(model, active | {"stress"})


def make_optimizer(model: Any, optimizer: str = "fire", dt: float = 0.1,
                   n_steps: int = 500, fmax: Optional[float] = 0.05,
                   hooks: Optional[List[Any]] = None, **kwargs: Any) -> Any:
    """Build a geometry optimizer stage (FIRE / FIRE2) without running it.

    Use this when composing multi-stage pipelines; use `relax()` for a one-shot run.
    `fmax` becomes a `ConvergenceHook` passed as the dedicated `convergence_hook`
    argument -- putting it in `hooks` would silently never converge.
    """
    key = optimizer.lower()
    if key not in OPTIMIZERS:
        raise ValueError(f"Unknown optimizer '{optimizer}'. Available: {sorted(OPTIMIZERS)}")
    opt_cls = _resolve("nvalchemi.dynamics", OPTIMIZERS[key])

    if key in STRESS_REQUIRING:
        _ensure_stress(model)

    convergence_hook = None
    if fmax is not None:
        ConvergenceHook = _resolve("nvalchemi.dynamics", "ConvergenceHook")
        convergence_hook = ConvergenceHook.from_fmax(fmax)

    return opt_cls(model=model, dt=dt, n_steps=n_steps, hooks=list(hooks or []),
                   convergence_hook=convergence_hook, **kwargs)


def make_integrator(model: Any, ensemble: str = "nvt", dt: float = 1.0,
                    n_steps: int = 5000, temperature: float = 300.0,
                    hooks: Optional[List[Any]] = None, **kwargs: Any) -> Any:
    """Build a molecular-dynamics stage without running it.

    Required parameters are filled with documented defaults when omitted:
    `friction` for Langevin, `thermostat_time` for Nose-Hoover and NPT,
    `barostat_time` and `pressure` for NPT/NPH.

    Args:
        ensemble: 'nve', 'nvt' (Langevin), 'nvt_nose_hoover', 'npt', 'nph'.
        dt: Timestep in femtoseconds.
        temperature: Target temperature in Kelvin (ignored by NVE and NPH).
        **kwargs: Ensemble-specific overrides, e.g. `friction`, `pressure`,
            `thermostat_time`, `barostat_time`, `pressure_coupling`.
    """
    key = ensemble.lower()
    if key not in ENSEMBLES:
        raise ValueError(f"Unknown ensemble '{ensemble}'. Available: {sorted(ENSEMBLES)}")
    integrator_cls = _resolve("nvalchemi.dynamics", ENSEMBLES[key])

    if key in STRESS_REQUIRING:
        _ensure_stress(model)

    params: Dict[str, Any] = {"model": model, "dt": dt, "n_steps": n_steps,
                              "hooks": list(hooks or [])}
    if key in ("nvt", "nvt_langevin"):
        params["temperature"] = temperature
        params.setdefault("friction", 0.01)
    elif key == "nvt_nose_hoover":
        params["temperature"] = temperature
        # A thermostat coupling time of ~100 steps is the usual starting point.
        params.setdefault("thermostat_time", 100.0 * dt)
    elif key == "npt":
        params["temperature"] = temperature
        params.setdefault("pressure", 0.0)
        params.setdefault("thermostat_time", 100.0 * dt)
        # The barostat must be slower than the thermostat, or the cell rings.
        params.setdefault("barostat_time", 1000.0 * dt)
    elif key == "nph":
        params.setdefault("pressure", 0.0)
        params.setdefault("barostat_time", 1000.0 * dt)

    params.update(kwargs)
    return integrator_cls(**params)


def single_point(batch: Any, model: Any) -> Dict[str, Any]:
    """Evaluate the model once on `batch` (no dynamics) and return its outputs.

    The supported way to get energies/forces for fixed geometries. Model
    wrappers have no `compute()` method, and calling `model(batch)` directly
    fails because the neighbor list is built by hooks. This builds the neighbor
    list with the same hooks the dynamics helpers use, then runs one forward
    pass. Do NOT use a zero-step `run()`: it evaluates nothing and leaves
    `batch.energy` at its zero-initialised value.

    Args:
        batch: `Batch` of structures (build it with `atoms_to_batch`).
        model: A wrapped potential; `set_active_outputs` selects what is computed.

    Returns:
        Dict of detached output tensors keyed by name (e.g. 'energy' with shape
        (num_graphs, 1), 'forces' with shape (num_atoms, 3)). The batch's output
        fields are updated in place too.

    Raises:
        RuntimeError: If the model returns no outputs or any non-finite value.
    """
    DynamicsStage = _resolve("nvalchemi.dynamics", "DynamicsStage")
    stage = make_integrator(model, ensemble="nve", dt=0.1, n_steps=1)
    attach_neighbor_hooks(stage, model)
    with stage:
        stage._call_hooks(DynamicsStage.BEFORE_COMPUTE, batch)
        outputs = stage.compute(batch)
    result = {k: v.detach() for k, v in dict(outputs).items() if v is not None}
    if not result:
        raise RuntimeError("Model returned no outputs; check set_active_outputs()")
    import torch
    bad = [k for k, v in result.items() if not bool(torch.isfinite(v).all())]
    if bad:
        raise RuntimeError(f"Non-finite model output(s): {bad}")
    return result


def relax(batch: Any, model: Any, fmax: float = 0.05, max_steps: int = 500,
          dt: float = 0.1, optimizer: str = "fire",
          hooks: Optional[List[Any]] = None, **kwargs: Any) -> Any:
    """Batched geometry relaxation of every structure in `batch`.

    All structures relax simultaneously in a shared model forward pass. Convergence
    does NOT remove a system from that forward pass: the run continues until EVERY
    structure meets `fmax` or `max_steps` is reached, so cost scales with the
    slowest system rather than the average. `ConvergenceHook` here performs no
    status migration -- there is no `status` field on a plain optimizer batch --
    so it acts purely as an all-converged stopping test. For large heterogeneous
    workloads use `screen()`, whose inflight batching genuinely evicts converged
    systems and backfills new ones.

    Args:
        batch: `Batch` of structures to relax (build it with `atoms_to_batch`).
        model: A wrapped potential.
        fmax: Force convergence threshold in eV/A.
        max_steps: Step budget.
        dt: Optimizer timestep.
        optimizer: 'fire', 'fire2', or the '*_variable_cell' variants which also
            relax the cell (these require a stress-capable potential).

    Returns:
        The relaxed `Batch`.
    """
    opt = make_optimizer(model, optimizer=optimizer, dt=dt, n_steps=max_steps,
                         fmax=fmax, hooks=hooks, **kwargs)
    attach_neighbor_hooks(opt, model)
    logging.info(
        f"Relaxing {batch.num_graphs} structure(s) with {optimizer.upper()} "
        f"(fmax={fmax}, max_steps={max_steps})"
    )
    with opt:
        return opt.run(batch)


def run_md(batch: Any, model: Any, ensemble: str = "nvt", dt: float = 1.0,
           n_steps: int = 5000, temperature: float = 300.0,
           hooks: Optional[List[Any]] = None, **kwargs: Any) -> Any:
    """Run batched molecular dynamics.

    Args:
        batch: `Batch` of structures. For NPT/NPH build it with
            `atoms_to_batch(..., need_stress=True)`.
        model: A wrapped potential.
        ensemble: 'nve', 'nvt', 'nvt_nose_hoover', 'npt', 'nph'.
        dt: Timestep in femtoseconds (use 0.5 when hydrogen is present).
        n_steps: Number of MD steps.
        temperature: Target temperature in Kelvin.

    Returns:
        The final `Batch`.
    """
    integrator = make_integrator(model, ensemble=ensemble, dt=dt, n_steps=n_steps,
                                 temperature=temperature, hooks=hooks, **kwargs)
    attach_neighbor_hooks(integrator, model)
    logging.info(
        f"Running {ensemble.upper()} MD: {batch.num_graphs} structure(s), "
        f"{n_steps} steps, dt={dt} fs, T={temperature} K"
    )
    with integrator:
        return integrator.run(batch)


def multi_stage(batch: Any, stages: Sequence[Any], model: Optional[Any] = None,
                compile_step: bool = False) -> Any:
    """Chain stages on one GPU with the `+` operator and run them.

    Systems migrate to the next stage as they converge, and every active system
    -- whichever stage it is in -- shares ONE model forward pass per step.

    Args:
        batch: `Batch` of structures.
        stages: Stages from `make_optimizer()` / `make_integrator()`, in order.
        model: The potential, used to register neighbor-list hooks.
        compile_step: Wrap the fused step in `torch.compile`. Only safe when no
            hook performs Python-side I/O.

    Returns:
        The final `Batch`.
    """
    if len(stages) < 2:
        raise ValueError("multi_stage() needs at least two stages.")

    fused = stages[0]
    for stage in stages[1:]:
        fused = fused + stage
    if compile_step:
        fused = fused.compile(fullgraph=False)
    if model is not None:
        attach_neighbor_hooks(fused, model)

    logging.info(f"Running fused pipeline of {len(stages)} stage(s)")
    with fused:
        return fused.run(batch)


def screen(atoms_list: Sequence[Any], model: Any, fmax: float = 0.05,
           max_steps: int = 500, max_batch_size: int = 64,
           max_atoms: Optional[int] = None, device: Optional[str] = None,
           optimizer: str = "fire", dt: float = 0.1,
           sink_capacity: Optional[int] = None) -> List[Any]:
    """High-throughput relaxation of many structures using inflight batching.

    A `SizeAwareSampler` feeds structures into a running `FusedStage` and
    converged systems are replaced mid-run, so the GPU never idles waiting for
    stragglers. Prefer this over `relax()` once you have more structures than
    comfortably fit in one batch.

    Args:
        atoms_list: Structures to screen.
        model: A wrapped potential.
        fmax: Force convergence threshold in eV/A.
        max_steps: Per-system step budget.
        max_batch_size: Maximum concurrent structures in the active batch.
        max_atoms: Maximum concurrent atoms; defaults to `max_batch_size` times
            the largest structure, which is the safe upper bound.
        optimizer: 'fire' or 'fire2'.
        sink_capacity: Result sink capacity; defaults to the input count.

    Returns:
        List of relaxed `ase.Atoms` collected from the converged-result sink.
        NOTE: only systems that actually reached `fmax` are returned. Structures
        still above the threshold when `max_steps` runs out are NOT collected,
        so a short return list means the step budget was too small.
        NOTE: results come back in GRADUATION order, not input order. Match them
        using atoms.info['input_index'] (the zero-based position in atoms_list).
        atoms.info['system_id'] is the sampler's admission-order ID, NOT an input
        index; mixed-size bin packing can reorder admissions. Existing caller
        metadata is restored from the corresponding input after ID validation.
    """
    import torch

    Batch = _resolve("nvalchemi.data", "Batch")
    InMemoryDataset = _resolve("nvalchemi.data", "InMemoryDataset")
    SizeAwareSampler = _resolve("nvalchemi.dynamics", "SizeAwareSampler")
    HostMemory = _resolve("nvalchemi.dynamics", "HostMemory")
    FusedStage = _resolve("nvalchemi.dynamics", "FusedStage")
    ConvergedSnapshotHook = _resolve("nvalchemi.dynamics.hooks",
                                     "ConvergedSnapshotHook")

    device = device or default_device()
    atoms_list = list(atoms_list)
    if not atoms_list:
        return []
    if max_batch_size < 1 or max_steps < 1:
        raise ValueError("max_batch_size and max_steps must be positive")
    if sink_capacity is not None and sink_capacity < len(atoms_list):
        raise ValueError("sink_capacity must cover all inputs; refusing silent result loss")
    largest = max(len(a) for a in atoms_list)
    max_atoms = max_atoms if max_atoms is not None else max_batch_size * largest
    if largest == 0 or any(len(a) == 0 for a in atoms_list) or max_atoms < largest:
        raise ValueError("Every system must contain atoms and fit max_atoms")

    data_list = [prepare_data(a, device=device) for a in atoms_list]
    for index, data in enumerate(data_list):
        # The toolkit overwrites system_id during sampling. Preserve input
        # identity as a separate system property through refill and sinks.
        data.add_system_property("input_index", torch.tensor([[index]], device=device, dtype=torch.long))
    # SizeAwareSampler needs get_metadata(idx); a bare list does not provide it.
    dataset = InMemoryDataset(Batch.from_data_list(data_list))
    sampler = SizeAwareSampler(dataset, max_atoms=max_atoms,
                               max_batch_size=max_batch_size)
    sink = HostMemory(capacity=sink_capacity or len(data_list))

    def _init_buffers(batch: Any) -> None:
        """The sampler-built batch may lack per-step buffers; fill them in place."""
        dev = batch.positions.device
        n = batch.num_nodes
        for key in ("forces", "velocities"):
            if getattr(batch, key, None) is None:
                values = [torch.zeros(int(count), 3, device=dev, dtype=batch.positions.dtype)
                          for count in batch.num_nodes_per_graph.detach().cpu().tolist()]
                batch.add_key(key, values, level="node")

    stage = make_optimizer(model, optimizer=optimizer, dt=dt, n_steps=max_steps,
                           fmax=fmax,
                           hooks=[ConvergedSnapshotHook(sink=sink)])
    # The ConvergedSnapshotHook MUST live on the sub-stage: ON_CONVERGE fires
    # there, not on the enclosing FusedStage. Registering it on the FusedStage
    # silently collects nothing.
    fused = FusedStage(
        [(0, stage)],
        sampler=sampler,
        init_fn=_init_buffers,
    )
    attach_neighbor_hooks(fused, model)

    logging.info(
        f"Screening {len(data_list)} structures with inflight batching "
        f"(max_batch_size={max_batch_size}, max_atoms={max_atoms})"
    )
    with fused:
        fused.run(None)

    out: List[Any] = []
    for item in _drain_sink(sink):
        out.extend(batch_to_atoms(item))
    _restore_screen_identity(out, atoms_list)

    # Only CONVERGED systems reach the sink. Anything still above `fmax` when
    # the step budget runs out is silently dropped, so surface the shortfall.
    if len(out) < len(data_list):
        logging.warning(
            f"Screening returned {len(out)} of {len(data_list)} structures: "
            f"{len(data_list) - len(out)} did not reach fmax={fmax} within "
            f"max_steps={max_steps} and were not collected. Raise max_steps or "
            f"loosen fmax to capture them."
        )
    else:
        logging.info(f"Screening collected all {len(out)} structures")
    return out


def _restore_screen_identity(results: List[Any], inputs: Sequence[Any]) -> None:
    """Fail closed on identity loss/duplicates; preserve input metadata by index."""
    import copy
    import numbers
    seen_inputs, seen_systems = set(), set()
    for atoms in results:
        index, system_id = atoms.info.get("input_index"), atoms.info.get("system_id")
        for label, value in (("input_index", index), ("system_id", system_id)):
            if isinstance(value, bool) or not isinstance(value, numbers.Integral) or value < 0:
                raise RuntimeError(f"Screening result missing valid {label}; cannot match inputs")
        if index >= len(inputs) or index in seen_inputs or system_id in seen_systems:
            raise RuntimeError("Screening result has out-of-range or duplicate identity")
        if list(atoms.numbers) != list(inputs[index].numbers):
            raise RuntimeError("Screening result composition does not match its input_index")
        seen_inputs.add(index)
        seen_systems.add(system_id)
        caller_info = copy.deepcopy(inputs[index].info)
        if "system_id" in caller_info:
            caller_info["source_system_id"] = caller_info.pop("system_id")
        if "input_index" in caller_info:
            caller_info["source_input_index"] = caller_info.pop("input_index")
        caller_info.update(atoms.info)
        atoms.info = caller_info


def _drain_sink(sink: Any) -> List[Any]:
    """Read every batch out of a data sink, returning [] when it is empty.

    `DataSink.drain()` raises `RuntimeError` on an empty buffer rather than
    returning nothing, so the emptiness check comes first.
    """
    try:
        if len(sink) == 0:
            logging.warning("Result sink is empty -- no systems converged.")
            return []
    except TypeError:
        pass  # Sink does not implement __len__; fall through to drain().

    for method in ("drain", "read"):
        if hasattr(sink, method):
            try:
                result = getattr(sink, method)()
            except RuntimeError as exc:
                logging.warning(f"Could not drain sink: {exc}")
                return []
            if result is None:
                return []
            return list(result) if isinstance(result, (list, tuple)) else [result]
    return []


# ============= TRAJECTORY I/O =============
def zarr_sink(path: str = "trajectory.zarr", capacity: int = 1_000_000,
              **kwargs: Any) -> Any:
    """Create a Zarr-backed data sink for persistent trajectory capture.

    Pass it to `snapshot_hook()` for periodic frames, or to a
    `ConvergedSnapshotHook` for converged results. Writes are GPU-buffered, so
    capture costs far less than host round-trips.
    """
    ZarrData = _resolve("nvalchemi.dynamics", "ZarrData")
    full = path if os.path.isabs(path) else os.path.join(WORK_DIR, path)
    logging.info(f"Zarr trajectory sink: {full}")
    return ZarrData(full, capacity=capacity, **kwargs)


def snapshot_hook(sink: Any, frequency: int = 100, **kwargs: Any) -> Any:
    """Periodically capture the running batch into a sink (trajectory writing)."""
    SnapshotHook = _resolve("nvalchemi.dynamics.hooks", "SnapshotHook")
    return SnapshotHook(sink=sink, frequency=frequency, **kwargs)


KB_EV_PER_K = 8.617333262145e-5


class StepRecorder:
    """Per-step energy/kinetic/temperature/fmax recorder (a toolkit hook).

    Build with `step_recorder()` and pass in `hooks=[...]`. Follows the toolkit
    hook protocol: `frequency` and `stage` attributes, `__call__(ctx, stage)`,
    batch read from `ctx.batch`. Runs at AFTER_STEP, where `ctx.step_count` is
    pre-increment, so `step` = `ctx.step_count + 1` (completed updates).
    `rows` holds one dict per recorded step and graph: step, graph,
    energy_eV, kinetic_energy_eV (toolkit per-graph kinetic energy),
    temperature_K (2*KE / (3*N*k_B), no constraint correction) and
    max_force_eV_per_A (largest per-atom force norm). Values are detached
    Python floats, so rows can be written directly to CSV/JSON.
    """

    def __init__(self, frequency: int = 1) -> None:
        if not isinstance(frequency, int) or frequency < 1:
            raise ValueError("frequency must be a positive integer")
        self.frequency = frequency
        self.stage = _resolve("nvalchemi.dynamics", "DynamicsStage").AFTER_STEP
        self.rows: List[Dict[str, Any]] = []
        self._kinetic = _resolve("nvalchemi.dynamics.hooks._utils", "kinetic_energy_per_graph")

    def __call__(self, ctx: Any, stage: Any) -> None:
        import torch
        batch = ctx.batch
        with torch.no_grad():
            graph = batch.batch_idx
            num_graphs = int(batch.num_graphs)
            kinetic = self._kinetic(batch.velocities, batch.atomic_masses, graph, num_graphs).reshape(-1)
            atoms = batch.num_nodes_per_graph
            norms = torch.linalg.vector_norm(batch.forces, dim=1)
            fmax = torch.zeros(num_graphs, dtype=norms.dtype, device=norms.device)
            fmax = fmax.scatter_reduce(0, graph, norms, reduce="amax", include_self=False)
            energy = batch.energy.reshape(-1)
            values = torch.stack([energy.to(kinetic.dtype), kinetic,
                                  2.0 * kinetic / (3.0 * atoms.to(kinetic.dtype) * KB_EV_PER_K),
                                  fmax.to(kinetic.dtype)], dim=1).detach().cpu().tolist()
        step = int(ctx.step_count) + 1
        for index, (e, ke, t, f) in enumerate(values):
            self.rows.append({"step": step, "graph": index, "energy_eV": e, "kinetic_energy_eV": ke,
                              "temperature_K": t, "max_force_eV_per_A": f})


def step_recorder(frequency: int = 1) -> StepRecorder:
    """Record energy, kinetic energy, temperature and fmax every `frequency` steps.

    Use this instead of writing a custom hook: toolkit hooks need `frequency`
    and `stage` attributes and a `__call__(ctx, stage)` signature, and a plain
    callable is rejected at registration. Read results from `recorder.rows`.
    """
    return StepRecorder(frequency)


def read_trajectory(path: str, batch_size: int = 32, device: Optional[str] = None,
                    shuffle: bool = False, **kwargs: Any) -> Any:
    """Open a Zarr trajectory store as a `DataLoader` with CUDA-stream prefetch.

    Use the returned loader directly as the training or analysis input pipeline.
    """
    AtomicDataZarrReader = _resolve("nvalchemi.data", "AtomicDataZarrReader")
    Dataset = _resolve("nvalchemi.data", "Dataset")
    DataLoader = _resolve("nvalchemi.data", "DataLoader")

    full = path if os.path.isabs(path) else os.path.join(WORK_DIR, path)
    reader = AtomicDataZarrReader(full)
    dataset = Dataset(reader, device=device or default_device())
    return DataLoader(dataset, batch_size=batch_size, shuffle=shuffle, **kwargs)


# ============= TRAINING & FINE-TUNING =============
def default_loss(energy_weight: float = 1.0, force_weight: float = 10.0,
                 stress_weight: float = 0.0, huber: bool = False) -> Any:
    """Build a composed energy / force / stress loss.

    Forces are weighted above energies by default because force errors dominate
    downstream dynamics quality. Set `stress_weight` when training for NPT use,
    and `huber=True` for robustness against outliers in noisy reference data.
    """
    import nvalchemi.training as T

    energy_cls = T.EnergyHuberLoss if huber else T.EnergyMSELoss
    force_cls = T.ForceHuberLoss if huber else T.ForceMSELoss

    loss = energy_weight * energy_cls() + force_weight * force_cls()
    if stress_weight:
        loss = loss + stress_weight * T.StressMSELoss()
    return loss


def train_mlip(model: Any, train_loader: Any, val_loader: Optional[Any] = None,
               loss_fn: Optional[Any] = None, num_steps: int = 10_000,
               learning_rate: float = 1e-3, checkpoint_dir: str = "checkpoints",
               ema_decay: float = 0.999, validate_every: int = 500,
               device: Optional[str] = None, model_key: str = "main",
               hooks: Optional[List[Any]] = None, **kwargs: Any) -> Any:
    """Train or fine-tune an MLIP with the ALCHEMI training stack.

    Builds a `TrainingStrategy` with an AdamW optimizer and an `EMAHook`, then
    saves a strategy checkpoint -- which preserves the model reconstruction
    recipe, weights, optimizer state and hook state together. Never save only
    `ema.state_dict()`; that cannot be restarted reliably for MACE.

    Args:
        model: A wrapped model. For MACE, build it with
            `load_model('mace', checkpoint=...)` so the reconstruction spec is
            recorded.
        train_loader: Training `DataLoader` (see `read_trajectory`).
        val_loader: Optional validation `DataLoader`.
        loss_fn: Composed loss; defaults to `default_loss()`.
        num_steps: Number of optimizer steps.
        learning_rate: AdamW learning rate.
        checkpoint_dir: Destination directory for strategy checkpoints.
        ema_decay: Exponential moving average decay.
        validate_every: Run validation every N steps when `val_loader` is given.
        model_key: Name under which the model is registered in the strategy.

    Returns:
        The `TrainingStrategy` after training.
    """
    import torch
    import nvalchemi.training as T

    device = device or default_device()
    loss = loss_fn if loss_fn is not None else default_loss()

    strategy_kwargs: Dict[str, Any] = {
        "models": {model_key: model},
        "optimizer_configs": {
            model_key: [T.OptimizerConfig(
                optimizer_cls=torch.optim.AdamW,
                optimizer_kwargs={"lr": learning_rate},
            )]
        },
        "num_steps": num_steps,
        "training_fn": T.default_training_fn,
        "loss_fn": loss,
        "devices": [torch.device(device)],
        "hooks": list(hooks or []) + [T.EMAHook(model_key=model_key, decay=ema_decay)],
    }
    if val_loader is not None:
        strategy_kwargs["validation_config"] = T.ValidationConfig(
            validation_data=val_loader,
            validation_fn=T.default_training_fn,
            loss_fn=loss,
            every_n_steps=validate_every,
        )
    strategy_kwargs.update(kwargs)

    strategy = T.TrainingStrategy(**strategy_kwargs)
    logging.info(f"Training for {num_steps} steps on {device}")
    strategy.run(train_loader)

    ckpt = checkpoint_dir if os.path.isabs(checkpoint_dir) \
        else os.path.join(WORK_DIR, checkpoint_dir)
    os.makedirs(ckpt, exist_ok=True)
    strategy.save_checkpoint(ckpt)
    logging.info(f"Saved training checkpoint to {ckpt}")
    return strategy


def load_training_checkpoint(checkpoint_dir: str, device: Optional[str] = None,
                             **kwargs: Any) -> Any:
    """Restore a `TrainingStrategy` from a checkpoint directory."""
    import torch
    import nvalchemi.training as T

    path = checkpoint_dir if os.path.isabs(checkpoint_dir) \
        else os.path.join(WORK_DIR, checkpoint_dir)
    return T.TrainingStrategy.load_checkpoint(
        path, map_location=torch.device(device or default_device()), **kwargs
    )


# ============= MULTI-GPU =============
def buffer_config(num_systems: int, max_atoms_per_system: int,
                  num_edges: int = 0) -> Any:
    """Build a `BufferConfig` for inter-rank transfers in a `DistributedPipeline`.

    NCCL point-to-point requires fixed-size tensors, so `num_nodes` must cover the
    worst case: `num_systems * max_atoms_per_system`. Every pair of communicating
    stages must share an identical config or `setup()` raises.

    `num_edges=0` is correct whenever the downstream model rebuilds its own
    neighbor list, which is the normal case.
    """
    BufferConfig = _resolve("nvalchemi.dynamics.base", "BufferConfig")
    return BufferConfig(
        num_systems=num_systems,
        num_nodes=num_systems * max_atoms_per_system,
        num_edges=num_edges,
    )


def run_distributed(script_path: str, nproc_per_node: Optional[int] = None,
                    extra_args: Optional[Sequence[str]] = None) -> int:
    """Launch a distributed script with `torchrun` and stream its output.

    `DistributedPipeline` and `DomainParallel` cannot run inline in the main
    workflow script -- they need one process per GPU. Write the pipeline to its
    own file, then launch it with this helper.

    Args:
        script_path: Path to the script to launch.
        nproc_per_node: Process count; defaults to every visible GPU.
        extra_args: Additional arguments passed through to the script.

    Returns:
        The `torchrun` exit code.
    """
    nproc = nproc_per_node or gpu_count()
    if nproc < 2:
        raise RuntimeError(
            f"Distributed execution needs at least 2 GPUs; found {nproc}. "
            "Request a multi-GPU SKU or use the single-GPU helpers instead."
        )
    path = script_path if os.path.isabs(script_path) else os.path.join(WORK_DIR, script_path)
    torchrun = os.path.join(os.path.dirname(sys.executable), "torchrun")
    if not os.path.exists(torchrun):
        torchrun = "torchrun"
    cmd = [torchrun, f"--nproc_per_node={nproc}", path]
    cmd.extend(extra_args or [])

    logging.info(f"Launching: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=WORK_DIR, check=False)
    if proc.returncode != 0:
        logging.error(f"torchrun exited with code {proc.returncode}")
    return proc.returncode


# ============= ANALYSIS & VISUALIZATION =============
def summarize_batch(batch: Any) -> List[Dict[str, Any]]:
    """Per-structure summary: formula, atom count, energy, max force, volume."""
    import numpy as np

    summaries: List[Dict[str, Any]] = []
    for i, atoms in enumerate(batch_to_atoms(batch)):
        entry: Dict[str, Any] = {
            "index": i,
            "formula": atoms.get_chemical_formula(),
            "num_atoms": len(atoms),
        }
        if "energy" in atoms.info:
            entry["energy_eV"] = atoms.info["energy"]
            entry["energy_per_atom_eV"] = atoms.info["energy"] / len(atoms)
        if "forces" in atoms.arrays:
            entry["fmax_eV_per_A"] = float(
                np.linalg.norm(atoms.arrays["forces"], axis=1).max()
            )
        if atoms.cell.rank == 3:
            entry["volume_A3"] = float(atoms.get_volume())
        summaries.append(entry)
    return summaries


def save_summary_csv(summaries: Sequence[Dict[str, Any]],
                     output_path: str = "summary.csv") -> str:
    """Write summary dictionaries to CSV."""
    import pandas as pd

    path = output_path if os.path.isabs(output_path) else os.path.join(WORK_DIR, output_path)
    pd.DataFrame(list(summaries)).to_csv(path, index=False)
    logging.info(f"Wrote summary CSV to {path}")
    return path


def plot_energy_trace(csv_path: str, output_file: str = "energy_trace.png",
                      energy_column: str = "energy",
                      step_column: str = "step") -> str:
    """Plot an energy trace from a `LoggingHook` CSV log."""
    import matplotlib.pyplot as plt
    import pandas as pd

    df = pd.read_csv(csv_path)
    path = output_file if os.path.isabs(output_file) else os.path.join(WORK_DIR, output_file)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = df[step_column] if step_column in df.columns else df.index
    ax.plot(x, df[energy_column], lw=1.2)
    ax.set_xlabel("step")
    ax.set_ylabel("energy (eV)")
    ax.set_title("Energy trace")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logging.info(f"Wrote energy trace plot to {path}")
    return path


def plot_energy_distribution(summaries: Sequence[Dict[str, Any]],
                             output_file: str = "energy_distribution.png") -> str:
    """Histogram of per-atom energies across a screened set of structures."""
    import matplotlib.pyplot as plt

    values = [s["energy_per_atom_eV"] for s in summaries if "energy_per_atom_eV" in s]
    if not values:
        raise ValueError("No per-atom energies in the supplied summaries.")

    path = output_file if os.path.isabs(output_file) else os.path.join(WORK_DIR, output_file)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.hist(values, bins=min(50, max(5, len(values) // 5)))
    ax.set_xlabel("energy per atom (eV)")
    ax.set_ylabel("count")
    ax.set_title(f"Energy distribution ({len(values)} structures)")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logging.info(f"Wrote energy distribution plot to {path}")
    return path
