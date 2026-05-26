#!/usr/bin/env python3
"""GROMACS utilities library for the Microsoft Discovery platform.

Provides building blocks for GROMACS molecular-dynamics workflows:
  - Environment setup (read-only /input protection, GPU detection, line-buffered logging)
  - MDP file introspection and validation
  - grompp/mdrun helpers that encode the POSRES/MDP-dependency rules so the
    agent cannot forget the -r / -n / -t flags
  - Adaptive mdrun with MPI domain-decomposition fallback and automatic
    SETTLE -> NVT recovery
  - Analysis helpers with a single source of truth for group selections
  - Final-results JSON schema + on-failure intermediate-file copy

Designed as orthogonal building blocks, NOT a pipeline. The agent composes
these into a script appropriate to the user's request.
"""

import glob
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# =============================================================================
# CONSTANTS
# =============================================================================
INPUT_DIR = "/input"
OUTPUT_DIR = "/output"
WORK_DIR = "/app/workdir"

# Files that must be COPIED from /input/ to WORK_DIR because GROMACS modifies
# them in place (solvate/genion edit .top; grompp writes alongside .mdp). The
# /input/ mount is read-only on the container.
_COPY_PATTERNS = ("*.top", "*.itp", "*.mdp", "*.ndx", "*.gro")

# Analysis-tool interactive group selections (single source of truth).
# These are the standard GROMACS index-group numbers for the default index
# (no custom .ndx file). When a custom index is in use, override via the
# `groups=` argument to run_analysis().
ANALYSIS_GROUPS: dict[str, Optional[str]] = {
    "rmsd": "4\n4\n",   # Backbone for both reference and trajectory
    "rmsf": "3\n",      # C-alpha
    "gyrate": "1\n",    # Protein
    "sasa": "1\n",      # Protein
    "hbond": "1\n1\n",  # Protein donor + Protein acceptor
    "energy": None,     # Caller must supply explicit term indices via `groups=`
}

# Default input-structure and reference-structure conventions for grompp_for_phase().
# Each phase reads the previous phase's output and uses it as the POSRES
# reference when the MDP file declares -DPOSRES.
_PHASE_PREV_PHASE: dict[str, Optional[str]] = {
    "em":  None,      # caller supplies (usually *_ions.gro or *_solv.gro)
    "nvt": "em",
    "npt": "nvt",
    "md":  "npt",
}

# Default force field and water model. Overridable per call.
DEFAULT_FORCE_FIELD = "charmm36m"
DEFAULT_WATER_MODEL = "tip3p"


# =============================================================================
# SETUP
# =============================================================================
def quick_setup(
    input_dir: str = "/input",
    output_dir: str = "/output",
    work_dir: str = "/app/workdir",
) -> tuple[bool, int]:
    """Configure logging, make dirs, copy inputs, chdir into work_dir, detect GPU.

    Call this once at the top of every script.

    Returns:
        (has_gpu, gpu_count) so the caller can log or branch on GPU availability.
        GROMACS auto-uses GPU when present; the return is informational only.
    """
    global INPUT_DIR, OUTPUT_DIR, WORK_DIR
    INPUT_DIR, OUTPUT_DIR, WORK_DIR = input_dir, output_dir, work_dir

    # Line-buffered stdout/stderr so log lines appear in real time in container logs.
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    for d in (work_dir, output_dir):
        os.makedirs(d, exist_ok=True)

    copy_inputs_to_workdir(input_dir, work_dir)
    os.chdir(work_dir)

    has_gpu, gpu_count = detect_gpu()
    return has_gpu, gpu_count


def copy_inputs_to_workdir(
    input_dir: str = "/input",
    work_dir: str = "/app/workdir",
    patterns: tuple[str, ...] = _COPY_PATTERNS,
) -> list[Path]:
    """Copy mutable input files (.top/.itp/.mdp/.ndx/.gro) into the working dir.

    /input/ is read-only on the container; commands such as `gmx solvate -p`
    and `gmx genion -p` edit the topology in place and will fail otherwise.
    """
    os.makedirs(work_dir, exist_ok=True)
    copied: list[Path] = []
    for pat in patterns:
        for src in glob.glob(os.path.join(input_dir, pat)):
            dst = Path(work_dir) / Path(src).name
            shutil.copy(src, dst)
            copied.append(dst)
            logging.info("Copied input file: %s", dst.name)
    return copied


def detect_gpu() -> tuple[bool, int]:
    """Return (has_gpu, count). Informational only - GROMACS auto-detects."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, check=True,
        )
        gpus = [ln.strip() for ln in result.stdout.strip().splitlines() if ln.strip()]
        if gpus:
            logging.info("Detected %d GPU(s):", len(gpus))
            for i, g in enumerate(gpus):
                logging.info("  GPU %d: %s", i, g)
            return True, len(gpus)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    logging.info("No GPU detected - GROMACS will run CPU-only")
    return False, 0


def detect_system_type(input_dir: str = "/input") -> str:
    """Classify the input as 'protein', 'ligand', or 'mixed'.

    Heuristics:
      - .itp present -> ligand or mixed (skip pdb2gmx, use provided topology)
      - .pdb present, no .itp -> protein (run pdb2gmx)
      - both .pdb and .itp -> mixed (protein-ligand complex)
    """
    has_itp = bool(glob.glob(os.path.join(input_dir, "*.itp")))
    has_pdb = bool(glob.glob(os.path.join(input_dir, "*.pdb")))
    if has_itp and has_pdb:
        return "mixed"
    if has_itp:
        return "ligand"
    return "protein"


# =============================================================================
# MDP INTROSPECTION
# =============================================================================
@dataclass
class MdpInfo:
    """Structured view of an MDP file. All fields are best-effort parses."""
    path: str
    has_posres: bool = False
    gen_vel: Optional[bool] = None
    continuation: bool = False
    custom_tc_grps: Optional[list[str]] = None
    custom_energygrps: Optional[list[str]] = None
    dt_fs: Optional[float] = None
    constraints: Optional[str] = None
    nstxout_compressed: Optional[int] = None
    nstxout: Optional[int] = None
    pcoupl: Optional[str] = None
    tcoupl: Optional[str] = None
    raw: dict[str, str] = field(default_factory=dict)


_STD_TC_GROUPS = {"system", "protein", "non-protein", "sol", "water", "water_and_ions"}


def scan_mdp(path: str) -> MdpInfo:
    """Parse an MDP file into a typed MdpInfo. Comments and case are normalised."""
    info = MdpInfo(path=path)
    text = Path(path).read_text()
    for raw_line in text.splitlines():
        line = raw_line.split(";", 1)[0].strip()
        if not line:
            continue
        if "=" not in line:
            # `define = -DPOSRES` may appear as `define =-DPOSRES` etc; covered below.
            continue
        key, _, val = line.partition("=")
        key = key.strip().lower().replace("_", "-")
        val = val.strip()
        info.raw[key] = val

        if key == "define" and "-DPOSRES" in val.upper():
            info.has_posres = True
        elif key == "gen-vel":
            info.gen_vel = val.lower() in ("yes", "on", "true", "1")
        elif key == "continuation":
            info.continuation = val.lower() in ("yes", "on", "true", "1")
        elif key == "tc-grps":
            grps = val.split()
            info.custom_tc_grps = [g for g in grps if g.lower() not in _STD_TC_GROUPS] or None
        elif key == "energygrps":
            info.custom_energygrps = val.split() or None
        elif key == "dt":
            try:
                info.dt_fs = float(val) * 1000.0  # ps -> fs
            except ValueError:
                pass
        elif key == "constraints":
            info.constraints = val.lower()
        elif key == "nstxout-compressed":
            info.nstxout_compressed = _safe_int(val)
        elif key == "nstxout":
            info.nstxout = _safe_int(val)
        elif key == "pcoupl":
            info.pcoupl = val
        elif key == "tcoupl":
            info.tcoupl = val
    return info


def _safe_int(val: str) -> Optional[int]:
    try:
        return int(val)
    except ValueError:
        return None


def validate_mdp(path: str) -> list[str]:
    """Return a list of human-readable warnings/errors.

    Empty list means the MDP looks consistent. The caller decides whether to
    abort or just log. Common bugs caught:
      - dt >= 2 fs without constraints=all-bonds (SETTLE failures)
      - continuation=yes with gen_vel=yes (contradictory restart semantics)
      - Both nstxout and nstxout-compressed are 0 (no trajectory output)
    """
    info = scan_mdp(path)
    issues: list[str] = []

    if info.dt_fs is not None and info.dt_fs >= 2.0:
        if info.constraints not in ("all-bonds", "hbonds-and-heavy-h", "h-angles", "all-angles"):
            issues.append(
                f"dt={info.dt_fs:.2f} fs requires constraints=all-bonds "
                f"(got constraints={info.constraints!r}); reduce dt to 1 fs "
                "or set 'constraints = all-bonds'."
            )

    if info.continuation and info.gen_vel:
        issues.append(
            "continuation=yes AND gen_vel=yes are contradictory; "
            "set gen_vel=no for continuation runs."
        )

    if (info.nstxout_compressed or 0) == 0 and (info.nstxout or 0) == 0:
        issues.append(
            "Both nstxout and nstxout-compressed are 0 - no trajectory will be written. "
            "Set nstxout-compressed>0 (recommended) to produce .xtc output."
        )

    return issues


# =============================================================================
# SUBPROCESS
# =============================================================================
def run_command(
    cmd: list[str],
    input_text: Optional[str] = None,
    cwd: Optional[str] = None,
    description: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Run a subprocess command with logging and error capture.

    Raises subprocess.CalledProcessError on non-zero exit, with stderr logged.
    On known GROMACS failure modes (pdb2gmx residue mismatches, grompp atom
    ordering issues, mdrun LINCS warnings) an extra translated hint is logged
    to spare the agent from parsing cryptic GROMACS stderr.
    """
    label = description or " ".join(cmd)
    logging.info("Executing: %s", label)
    try:
        if input_text is not None:
            result = subprocess.run(
                cmd, input=input_text, text=True, check=True,
                capture_output=True, cwd=cwd,
            )
        else:
            result = subprocess.run(
                cmd, check=True, capture_output=True, text=True, cwd=cwd,
            )
        logging.info("OK: %s", label)
        return result
    except subprocess.CalledProcessError as e:
        logging.error("FAILED: %s", label)
        if e.stderr:
            logging.error("STDERR: %s", e.stderr.strip())
        hint = _translate_gromacs_error(cmd, e.stderr or "")
        if hint:
            logging.error("HINT: %s", hint)
        raise


# Known GROMACS failure patterns -> human-readable hint. Order matters: the
# first match wins, so more specific patterns must come before generic ones.
# Each entry is (regex, gmx-subcommand-or-None, hint-template). Templates may
# reference one named group: {match}. Keep this list short -- only add
# patterns that have actually bitten a real job.
_GMX_ERROR_PATTERNS: list[tuple[re.Pattern, Optional[str], str]] = [
    (
        re.compile(r"Residue '(?P<match>[A-Z0-9]{2,4})' not found in residue topology database", re.IGNORECASE),
        "pdb2gmx",
        "Residue '{match}' is missing from the selected force field's .rtp database. "
        "If it's a ligand, supply an .itp and skip prepare_protein(). "
        "If it's a cap residue (ACE/NME/NHE) or non-standard amino acid, you may need a different force field.",
    ),
    (
        re.compile(r"Atom (?P<match>\S+) in residue (?:ACE|NME|NHE|NH2)", re.IGNORECASE),
        "pdb2gmx",
        "Cap residue atom '{match}' name does not match the force field's .rtp entry. "
        "Check your PDB's terminal residue naming conventions -- ACE/NME often have FF-specific atom names.",
    ),
    (
        re.compile(r"(?:Sort error|sort error|atoms .* not sorted|atom .* not found in residue)", re.IGNORECASE),
        "pdb2gmx",
        "pdb2gmx atom-sort failure usually means a residue's atom names in the PDB don't match the force field's .rtp entry. "
        "Most common cause: cap residues (ACE/NME), non-standard protonation states (HIE/HID/HIP), or hydrogen names. "
        "Try `gmx pdb2gmx -ignh` to let GROMACS rebuild hydrogens.",
    ),
    (
        re.compile(r"Long bonds, possibly due to wrong PDB or GRO file", re.IGNORECASE),
        "grompp",
        "Atom ordering in the structure file does not match the topology. "
        "Common causes: edited PDB out of pdb2gmx's expected order, or topology was generated from a different structure.",
    ),
    (
        re.compile(r"number of coordinates in coordinate file .* does not match topology", re.IGNORECASE),
        "grompp",
        "Coordinate file and topology disagree on atom count -- usually a stale .gro vs. .top mismatch. "
        "Re-run the previous step (solvate/genion) and ensure you pass the matching .top.",
    ),
    (
        re.compile(r"Water molecule .* can not be settled", re.IGNORECASE),
        "mdrun",
        "SETTLE failure on a water molecule means an atom moved too far in one step -- the system is unstable. "
        "If this happens in NVT/NPT after EM, re-run EM with tighter convergence; "
        "if during EM, your starting geometry has overlapping atoms (check pdb2gmx output and box size).",
    ),
    (
        re.compile(r"(?:1 particles communicated to PME rank|domain decomposition does not work)", re.IGNORECASE),
        "mdrun",
        "Domain-decomposition / PME mismatch -- the system is too small for the requested rank count. "
        "Try fewer MPI ranks or `mdrun -dd 1 1 1` for a serial run.",
    ),
]


def _translate_gromacs_error(cmd: list[str], stderr: str) -> Optional[str]:
    """Map a GROMACS stderr blob to a human-readable hint string, or None.

    Robust to FF / GROMACS version drift -- we match on stable error phrases,
    not on internal data structures.
    """
    if not stderr:
        return None
    # Identify the gmx subcommand (e.g. 'pdb2gmx') so we can scope patterns.
    gmx_sub: Optional[str] = None
    try:
        gmx_idx = cmd.index("gmx")
        if gmx_idx + 1 < len(cmd):
            gmx_sub = cmd[gmx_idx + 1]
    except ValueError:
        pass
    for pat, scope, template in _GMX_ERROR_PATTERNS:
        if scope is not None and scope != gmx_sub:
            continue
        m = pat.search(stderr)
        if m:
            try:
                return template.format(match=m.group("match"))
            except IndexError:
                return template
    return None


# =============================================================================
# GROMPP + MDRUN
# =============================================================================
def grompp(
    mdp: str,
    structure: str,
    topology: str,
    output_tpr: str,
    *,
    reference: Optional[str] = "auto",
    index: Optional[str] = None,
    checkpoint: Optional[str] = None,
    maxwarn: int = 1,
) -> None:
    """Run `gmx grompp` with required flags inferred from the MDP file.

    Args:
        reference: Position-restraint reference structure.
            - "auto" (default): inspect mdp; if -DPOSRES is defined, use `structure`.
            - None: do not pass -r even if -DPOSRES is defined (caller knows best).
            - explicit path: pass -r <path>.
        index: .ndx file. Auto-required-check: if mdp declares custom tc-grps and
            no index is supplied, raises ValueError.
        checkpoint: state.cpt for continuation runs. Auto-required-check: if
            mdp has continuation=yes and no checkpoint is supplied, raises.
    """
    info = scan_mdp(mdp)

    if reference == "auto":
        reference = structure if info.has_posres else None

    if info.custom_tc_grps and not index:
        raise ValueError(
            f"{mdp} declares custom tc-grps {info.custom_tc_grps}; "
            "pass index=<ndx_file> to grompp()."
        )
    if info.continuation and not checkpoint:
        raise ValueError(
            f"{mdp} has continuation=yes; pass checkpoint=<state.cpt> to grompp()."
        )

    cmd = [
        "gmx", "grompp",
        "-f", mdp,
        "-c", structure,
        "-p", topology,
        "-o", output_tpr,
        "-maxwarn", str(maxwarn),
    ]
    if reference:
        cmd += ["-r", reference]
    if index:
        cmd += ["-n", index]
    if checkpoint:
        cmd += ["-t", checkpoint]

    run_command(cmd, description=f"grompp ({Path(mdp).name} -> {Path(output_tpr).name})")


def grompp_for_phase(
    phase: str,
    basename: str,
    *,
    mdp: Optional[str] = None,
    input_gro: Optional[str] = None,
    topology: Optional[str] = None,
    reference: Optional[str] = "auto",
    index: Optional[str] = None,
    checkpoint: Optional[str] = None,
    maxwarn: int = 1,
) -> str:
    """Run grompp for a standard phase ('em', 'nvt', 'npt', 'md').

    Conventions (overridable):
      - mdp:       f'{phase}.mdp'  (or 'minim.mdp' / 'ions.mdp' historically)
      - input_gro: output of previous phase, e.g. '{basename}_em.gro' for nvt
      - topology:  f'{basename}.top'
      - output:    f'{basename}_{phase}.tpr'

    Returns the produced TPR path.
    """
    if phase not in _PHASE_PREV_PHASE:
        raise ValueError(f"Unknown phase {phase!r}; expected em/nvt/npt/md")

    if mdp is None:
        # Look for the conventional names; fall back to '{phase}.mdp'.
        for candidate in (f"{phase}.mdp", f"eq{phase}.mdp", f"{phase}_*.mdp"):
            hits = glob.glob(candidate)
            if hits:
                mdp = hits[0]
                break
        if mdp is None:
            mdp = f"{phase}.mdp"

    if topology is None:
        topology = f"{basename}.top"

    if input_gro is None:
        prev = _PHASE_PREV_PHASE[phase]
        if prev is None:
            raise ValueError(
                f"phase={phase!r} has no default input structure; "
                "pass input_gro=<file> explicitly."
            )
        input_gro = f"{basename}_{prev}.gro"

    output_tpr = f"{basename}_{phase}.tpr"

    grompp(
        mdp=mdp, structure=input_gro, topology=topology, output_tpr=output_tpr,
        reference=reference, index=index, checkpoint=checkpoint, maxwarn=maxwarn,
    )
    return output_tpr


def run_mdrun_adaptive(
    deffnm: str,
    *,
    phase: str = "md",
    extra_flags: Optional[list[str]] = None,
    input_gro: Optional[str] = None,
    topology: Optional[str] = None,
    cpo_to_output: bool = True,
    cwd: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Run `gmx mdrun -deffnm <deffnm>` with two layers of error recovery.

    Recovery #1: MPI domain decomposition failure -> retry with -ntmpi 1.
      Triggered when stderr contains 'domain decomposition'.

    Recovery #2 (NPT phase only): SETTLE failure -> insert NVT equilibration
      and retry NPT from the NVT-equilibrated structure.
      Requires `input_gro` and `topology` to be supplied so the recovery NVT
      can be set up. Will not recurse: if the recovery NVT itself crashes,
      the original NPT error is re-raised.

    GPU is auto-detected by GROMACS; no explicit GPU flags are needed.

    Args:
        cpo_to_output: If True, append `-cpo /output/<deffnm>.cpt` so the
            checkpoint survives container OOM/cancellation. Trajectory and
            energy files stay in the work dir (copied at end of run).
    """
    base_cmd = ["gmx", "mdrun", "-v", "-deffnm", deffnm]
    if cpo_to_output:
        base_cmd += ["-cpo", os.path.join(OUTPUT_DIR, f"{deffnm}.cpt")]
    if extra_flags:
        base_cmd += list(extra_flags)

    try:
        return run_command(base_cmd, cwd=cwd, description=f"mdrun {deffnm} ({phase})")
    except subprocess.CalledProcessError as first_err:
        stderr_lc = (first_err.stderr or "").lower()
        stdout_lc = (first_err.stdout or "").lower()

        # ----- Recovery #1: MPI domain decomposition -----
        if "domain decomposition" in stderr_lc:
            logging.warning(
                "MPI domain decomposition failed; retrying with -ntmpi 1 (single rank)"
            )
            try:
                return run_command(
                    base_cmd + ["-ntmpi", "1"], cwd=cwd,
                    description=f"mdrun {deffnm} ({phase}, -ntmpi 1 fallback)",
                )
            except subprocess.CalledProcessError as second_err:
                first_err = second_err
                stderr_lc = (second_err.stderr or "").lower()
                stdout_lc = (second_err.stdout or "").lower()

        # ----- Recovery #2: SETTLE in NPT -> insert NVT -----
        settle_signal = (
            "settle" in stderr_lc or "settle" in stdout_lc
            or "can not be settled" in stdout_lc
        )
        if settle_signal and phase == "npt" and input_gro and topology:
            return _settle_recovery_via_nvt(
                deffnm=deffnm, base_cmd=base_cmd, input_gro=input_gro,
                topology=topology, cwd=cwd, original_error=first_err,
            )

        if settle_signal:
            logging.error(
                "SETTLE error in %s phase. Likely causes: dt too large (use 1 fs); "
                "missing NVT equilibration before NPT; energy minimisation did not converge.",
                phase,
            )
        raise


def _settle_recovery_via_nvt(
    *,
    deffnm: str,
    base_cmd: list[str],
    input_gro: str,
    topology: str,
    cwd: Optional[str],
    original_error: subprocess.CalledProcessError,
) -> subprocess.CompletedProcess:
    """Insert an NVT equilibration step and retry the original NPT mdrun."""
    nvt_mdp = next(
        (m for m in ("nvt.mdp", "eqnvt.mdp") if os.path.exists(m)),
        None,
    )
    if not nvt_mdp:
        logging.error("SETTLE recovery: no nvt.mdp found; cannot auto-insert NVT step.")
        raise original_error

    logging.warning("SETTLE error in NPT; inserting recovery NVT equilibration step.")
    recovery_basename = deffnm.replace("_npt", "_nvt_recovery")
    try:
        grompp(
            mdp=nvt_mdp, structure=input_gro, topology=topology,
            output_tpr=f"{recovery_basename}.tpr", reference="auto",
        )
        run_mdrun_adaptive(recovery_basename, phase="nvt", cwd=cwd, cpo_to_output=False)
        new_input = f"{recovery_basename}.gro"

        npt_mdp = f"{deffnm}.mdp" if os.path.exists(f"{deffnm}.mdp") else "npt.mdp"
        grompp(
            mdp=npt_mdp, structure=new_input, topology=topology,
            output_tpr=f"{deffnm}.tpr", reference=new_input,
        )
        logging.info("Retrying NPT mdrun after NVT recovery.")
        return run_command(
            base_cmd, cwd=cwd,
            description=f"mdrun {deffnm} (npt, post-NVT-recovery)",
        )
    except Exception as recovery_err:
        logging.error("SETTLE recovery failed: %s", recovery_err)
        raise original_error


# =============================================================================
# ANALYSIS
# =============================================================================
def ensure_xtc(deffnm: str, tpr: Optional[str] = None) -> str:
    """Return a usable .xtc path for the given deffnm, converting from .trr if needed."""
    xtc = f"{deffnm}.xtc"
    if os.path.exists(xtc):
        return xtc
    trr = f"{deffnm}.trr"
    if not os.path.exists(trr):
        raise FileNotFoundError(
            f"Neither {xtc} nor {trr} exists; cannot produce a trajectory for analysis."
        )
    logging.info("Converting %s -> %s for analysis", trr, xtc)
    s = tpr or f"{deffnm}.tpr"
    run_command(
        ["gmx", "trjconv", "-s", s, "-f", trr, "-o", xtc],
        input_text="0\n",
        description=f"trjconv {trr} -> {xtc}",
    )
    return xtc


def run_analysis(
    kind: str,
    tpr: str,
    xtc: str,
    output_xvg: str,
    *,
    groups: Optional[str] = None,
    extra_flags: Optional[list[str]] = None,
    tu: Optional[str] = "ns",
) -> str:
    """Run a standard GROMACS analysis tool with the canonical group selection.

    Args:
        kind: One of 'rmsd', 'rmsf', 'gyrate', 'sasa', 'hbond', 'energy'.
        groups: Override the default group-selection input_text. For 'energy'
            you MUST supply this (e.g. '11\\n12\\n0\\n' for Potential+Total).

    Returns the output_xvg path.
    """
    tool_map = {
        "rmsd": "rms", "rmsf": "rmsf", "gyrate": "gyrate",
        "sasa": "sasa", "hbond": "hbond", "energy": "energy",
    }
    if kind not in tool_map:
        raise ValueError(f"Unknown analysis kind {kind!r}; expected one of {list(tool_map)}")

    if groups is None:
        groups = ANALYSIS_GROUPS[kind]
    if groups is None:
        raise ValueError(
            f"Analysis '{kind}' has no default group selection; "
            "pass groups=<input_text> explicitly."
        )

    tool = tool_map[kind]
    cmd = ["gmx", tool]
    if kind == "energy":
        cmd += ["-f", xtc.replace(".xtc", ".edr"), "-o", output_xvg]
    elif kind == "hbond":
        cmd += ["-s", tpr, "-f", xtc, "-num", output_xvg]
    else:
        cmd += ["-s", tpr, "-f", xtc, "-o", output_xvg]
        if tu:
            cmd += ["-tu", tu]
    if extra_flags:
        cmd += list(extra_flags)

    run_command(cmd, input_text=groups, description=f"{tool} -> {output_xvg}")
    return output_xvg


# =============================================================================
# RESULTS + FAILURE HANDLING
# =============================================================================
def make_results_skeleton() -> dict[str, Any]:
    """Return the canonical final_results.json skeleton.

    The agent fills in keys under 'results' (per-system metrics) and
    'output_files' (artefact paths) as the workflow progresses.
    """
    return {
        "summary": {
            "status": "in_progress",
            "systems_processed": 0,
            "total_simulation_time_ps": 0.0,
        },
        "results": {},
        "output_files": {
            "trajectories": [],
            "structures": [],
            "analysis": [],
            "checkpoints": [],
        },
    }


def save_final_results(
    results: dict[str, Any],
    output_dir: str = "/output",
    filename: str = "final_results.json",
) -> str:
    """Write results to <output_dir>/<filename> and return the path."""
    if results.get("summary", {}).get("status") == "in_progress":
        results.setdefault("summary", {})["status"] = "completed"
    path = os.path.join(output_dir, filename)
    with open(path, "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    logging.info("Final results written to %s", path)
    return path


def copy_intermediates_on_failure(
    work_dir: str = "/app/workdir",
    output_dir: str = "/output",
    patterns: tuple[str, ...] = ("*.gro", "*.tpr", "*.edr", "*.log", "*.mdp", "*.top", "*.cpt"),
) -> list[str]:
    """Copy debug-relevant intermediates from work_dir to output_dir.

    Call from an `except:` block so failed runs leave behind everything needed
    to diagnose the failure. Never raises - best-effort.
    """
    copied: list[str] = []
    os.makedirs(output_dir, exist_ok=True)
    for pat in patterns:
        for src in glob.glob(os.path.join(work_dir, pat)):
            try:
                dst = os.path.join(output_dir, os.path.basename(src))
                shutil.copy(src, dst)
                copied.append(dst)
            except Exception as e:
                logging.warning("Could not copy %s: %s", src, e)
    if copied:
        logging.info("Copied %d intermediate file(s) to %s for debugging", len(copied), output_dir)
    return copied


# =============================================================================
# CONVENIENCE: standard pdb2gmx -> editconf -> solvate -> ions sequence
# (Optional building block - the agent may compose these by hand instead.)
# =============================================================================
def prepare_protein(
    pdb: str,
    basename: str,
    *,
    force_field: str = DEFAULT_FORCE_FIELD,
    water_model: str = DEFAULT_WATER_MODEL,
    box_distance: float = 1.0,
    box_type: str = "cubic",
    ions_mdp: str = "ions.mdp",
    pname: str = "NA",
    nname: str = "CL",
) -> str:
    """Run the standard protein preparation pipeline.

    Produces: {basename}_processed.gro -> {basename}_box.gro -> {basename}_solv.gro
              -> {basename}_ions.gro (with topology at {basename}.top).

    Returns the ion-containing structure path, ready for energy minimisation.

    NOTE: This is for protein-only systems. Ligand/surfactant systems (with
    .itp files supplied) should NOT call this - build topology manually and
    start with editconf + solvate.
    """
    run_command(
        [
            "gmx", "pdb2gmx", "-f", pdb,
            "-o", f"{basename}_processed.gro",
            "-p", f"{basename}.top",
            "-ff", force_field, "-water", water_model, "-ignh",
        ],
        description=f"pdb2gmx {Path(pdb).name}",
    )
    run_command(
        [
            "gmx", "editconf", "-f", f"{basename}_processed.gro",
            "-o", f"{basename}_box.gro",
            "-c", "-d", str(box_distance), "-bt", box_type,
        ],
        description=f"editconf -> {basename}_box.gro",
    )
    run_command(
        [
            "gmx", "solvate", "-cp", f"{basename}_box.gro",
            "-cs", "spc216.gro", "-o", f"{basename}_solv.gro",
            "-p", f"{basename}.top",
        ],
        description=f"solvate -> {basename}_solv.gro",
    )
    # Ions: grompp then genion.
    # If the caller left ions_mdp at its default and no file is present, write
    # a minimal MDP. genion only needs a valid TPR -- the four lines below are
    # standard GROMACS-tutorial boilerplate with no scientific content. We
    # ONLY auto-generate when the default name is in use: if the caller passed
    # a custom path that doesn't exist, that's a real error and must surface.
    if ions_mdp == "ions.mdp" and not Path(ions_mdp).exists():
        Path(ions_mdp).write_text(
            "; Auto-generated by prepare_protein() -- preflight for genion only.\n"
            "integrator    = steep\n"
            "emtol         = 1000.0\n"
            "nsteps        = 0\n"
            "cutoff-scheme = Verlet\n"
        )
        logging.info("Wrote default ions.mdp (genion preflight; no scientific impact)")
    grompp(
        mdp=ions_mdp, structure=f"{basename}_solv.gro",
        topology=f"{basename}.top", output_tpr=f"{basename}_ions.tpr",
        reference=None,  # ions step never needs POSRES reference
    )
    run_command(
        [
            "gmx", "genion", "-s", f"{basename}_ions.tpr",
            "-o", f"{basename}_ions.gro",
            "-p", f"{basename}.top",
            "-pname", pname, "-nname", nname, "-neutral",
        ],
        input_text="13\n",  # SOL group
        description=f"genion -> {basename}_ions.gro",
    )
    return f"{basename}_ions.gro"
