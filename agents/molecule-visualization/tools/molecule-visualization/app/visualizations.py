"""Create 2D molecule images and optional interactive 3D plots from SMILES.

Install ``rdkit`` and ``plotly``, then run:

    python visualizations.py "CCO" --name ethanol --output-dir output --with-3d

Import ``create_molecule`` to use the same functionality from Python.
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import re
import sys
from collections.abc import Iterable, Sequence

import plotly.graph_objects as go
from rdkit import Chem
from rdkit.Chem import AllChem, Draw
from rdkit.Chem.MolStandardize import rdMolStandardize

logger = logging.getLogger(__name__)

ELEMENT_COLORS = {
    "C": "#4c566a",
    "H": "#b8b8b8",
    "N": "#4c78a8",
    "O": "#e45756",
    "S": "#f2cf5b",
    "P": "#f58518",
    "F": "#54a24b",
    "Cl": "#54a24b",
    "Br": "#b279a2",
    "I": "#b279a2",
}


def _safe_stem(name: str | None) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "").strip()).strip("._-")
    if not stem:
        stem = "molecule"
    if stem.upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }:
        stem = f"_{stem}"
    return stem[:80]


def smiles_to_structures(
    smiles: str,
    name: str,
    out_dir: str | pathlib.Path,
    formats: Sequence[str] = ("smi", "sdf", "pdb", "xyz"),
    seed: int = 42,
    standardize_fragments: bool = True,
) -> dict[str, pathlib.Path]:
    """Write SMI, SDF, PDB, and XYZ formats for a SMILES string."""
    unsupported_formats = set(formats) - {"smi", "sdf", "pdb", "xyz"}
    if unsupported_formats:
        raise ValueError(f"Unsupported structure formats: {', '.join(sorted(unsupported_formats))}")
    logger.info("Starting 3D structure generation for %s", name)
    logger.debug(
        "3D settings: formats=%s seed=%d standardize_fragments=%s",
        formats,
        seed,
        standardize_fragments,
    )
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        logger.error("RDKit could not parse SMILES for %s", name)
        raise ValueError(f"Invalid SMILES: {smiles}")
    logger.info(
        "Parsed 3D input for %s: %d heavy atoms",
        name,
        mol.GetNumHeavyAtoms(),
    )
    if standardize_fragments:
        original_atom_count = mol.GetNumAtoms()
        mol = rdMolStandardize.FragmentParent(mol)
        if mol.GetNumAtoms() != original_atom_count:
            logger.info(
                "Fragment standardization changed atom count for %s: %d -> %d",
                name,
                original_atom_count,
                mol.GetNumAtoms(),
            )

    mh = Chem.AddHs(mol)
    logger.info("Added explicit hydrogens for %s: %d total atoms", name, mh.GetNumAtoms())
    p = AllChem.ETKDGv3()
    p.randomSeed = seed
    logger.info("Embedding 3D conformer for %s with seed %d", name, seed)
    if AllChem.EmbedMolecule(mh, p) != 0:
        logger.warning("Standard embedding failed for %s; retrying with random coordinates", name)
        p.useRandomCoords = True
        if AllChem.EmbedMolecule(mh, p) != 0:
            logger.error("Both 3D embedding attempts failed for %s", name)
            raise RuntimeError(f"3D embedding failed: {smiles}")
    optimization_status = AllChem.MMFFOptimizeMolecule(mh, maxIters=2000)
    logger.info(
        "MMFF optimization finished for %s with status %d",
        name,
        optimization_status,
    )
    if optimization_status == -1:
        raise RuntimeError(f"MMFF force-field parameters are unavailable for {name}")
    if optimization_status == 1:
        raise RuntimeError(f"MMFF optimization did not converge for {name}")
    if optimization_status != 0:
        raise RuntimeError(f"MMFF optimization failed for {name}: status {optimization_status}")

    counts = {}
    for a in mh.GetAtoms():
        el = a.GetSymbol()
        counts[el] = counts.get(el, 0) + 1
        nm = (f" {el}{counts[el]}" if len(el) == 1 else f"{el}{counts[el]}")[:4].ljust(4)
        info = Chem.AtomPDBResidueInfo(
            nm, residueName="LIG", residueNumber=1, chainId="A", isHeteroAtom=True
        )
        a.SetMonomerInfo(info)

    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    logger.debug("Writing 3D structure files for %s to %s", name, out)
    mh.SetProp("_Name", name)
    pdb_block = Chem.MolToPDBBlock(mh)
    written: dict[str, pathlib.Path] = {}
    if "smi" in formats:
        written["smi"] = out / f"{name}.smi"
        written["smi"].write_text(
            f"{Chem.MolToSmiles(mol)}\t{name}\n", encoding="utf-8"
        )
        logger.info("Wrote SMILES file: %s", written["smi"])
    if "pdb" in formats:
        written["pdb"] = out / f"{name}.pdb"
        written["pdb"].write_text(pdb_block, encoding="utf-8")
        logger.info("Wrote PDB file: %s", written["pdb"])
    if "xyz" in formats:
        written["xyz"] = out / f"{name}.xyz"
        written["xyz"].write_text(Chem.MolToXYZBlock(mh), encoding="utf-8")
        logger.info("Wrote XYZ file: %s", written["xyz"])
    if "sdf" in formats:
        written["sdf"] = out / f"{name}.sdf"
        with Chem.SDWriter(str(written["sdf"])) as writer:
            writer.write(mh)
        logger.info("Wrote SDF file: %s", written["sdf"])
    logger.info("Completed 3D structure generation for %s", name)
    return written


def _plot_3d_html(pdb_path: pathlib.Path, name: str, html_path: pathlib.Path) -> None:
    logger.info("Loading generated PDB for interactive 3D plot: %s", pdb_path)
    molecule = Chem.MolFromPDBFile(str(pdb_path), removeHs=False, sanitize=False)
    if molecule is None or molecule.GetNumConformers() == 0:
        logger.error("Generated PDB has no readable conformer: %s", pdb_path)
        raise RuntimeError(f"Could not read generated 3D structure: {pdb_path}")
    coordinates = molecule.GetConformer().GetPositions()
    logger.info(
        "Preparing 3D plot for %s: %d atoms, %d bonds",
        name,
        molecule.GetNumAtoms(),
        molecule.GetNumBonds(),
    )
    bond_coordinates = [[], [], []]
    for bond in molecule.GetBonds():
        start, end = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
        for axis, values in enumerate(bond_coordinates):
            values.extend([coordinates[start, axis], coordinates[end, axis], None])

    atoms = list(molecule.GetAtoms())
    figure = go.Figure(
        [
            go.Scatter3d(
                x=bond_coordinates[0],
                y=bond_coordinates[1],
                z=bond_coordinates[2],
                mode="lines",
                line={"color": "#64748b", "width": 4},
                hoverinfo="skip",
            ),
            go.Scatter3d(
                x=coordinates[:, 0],
                y=coordinates[:, 1],
                z=coordinates[:, 2],
                mode="markers",
                marker={
                    "size": 6,
                    "color": [
                        ELEMENT_COLORS.get(atom.GetSymbol(), "#8c8c8c")
                        for atom in atoms
                    ],
                },
                customdata=[[atom.GetIdx(), atom.GetSymbol()] for atom in atoms],
                hovertemplate="Atom %{customdata[0]}: %{customdata[1]}<extra></extra>",
            ),
        ]
    )
    figure.update_layout(
        title=name,
        scene={
            "xaxis_visible": False,
            "yaxis_visible": False,
            "zaxis_visible": False,
            "aspectmode": "data",
        },
        margin={"l": 0, "r": 0, "t": 50, "b": 0},
        showlegend=False,
    )
    logger.info("Writing interactive 3D HTML plot: %s", html_path)
    figure.write_html(html_path, include_plotlyjs=True, full_html=True)
    logger.info("Completed interactive 3D plot: %s", html_path)


def create_molecule(
    smiles: str,
    name: str | None = None,
    out_dir: str | pathlib.Path = "output",
    include_3d: bool = False,
    seed: int = 42,
    image_size: tuple[int, int] = (600, 450),
) -> dict[str, pathlib.Path]:
    """Create 2D molecule images and optionally an interactive 3D plot.

    Args:
        smiles: A valid SMILES string.
        name: Optional molecule name used for labels and output filenames.
        out_dir: Directory where generated files are saved.
        include_3d: Generate a 3D conformer, interactive HTML plot, and
            SDF/PDB/XYZ files when true.
        seed: Random seed for reproducible conformer generation.
        image_size: Width and height in pixels for the 2D images.

    Returns:
        Mapping of output format names to generated file paths.

    Raises:
        TypeError: If input values have unsupported types.
        ValueError: If the SMILES or image size is invalid.
        RuntimeError: If RDKit cannot generate or read the 3D conformer.
        OSError: If an output file cannot be written.
    """
    if not isinstance(smiles, str):
        raise TypeError("smiles must be a string")
    smiles = smiles.strip()
    if not smiles:
        raise ValueError("smiles must not be empty")
    if name is not None and not isinstance(name, str):
        raise TypeError("name must be a string or None")
    if not isinstance(seed, int):
        raise TypeError("seed must be an integer")
    if (
        not isinstance(image_size, tuple)
        or len(image_size) != 2
        or any(not isinstance(size, int) or size <= 0 for size in image_size)
    ):
        raise ValueError("image_size must be a pair of positive integers")

    label = (name or "").strip() or "molecule"
    stem = _safe_stem(label)
    out = pathlib.Path(out_dir)
    logger.info(
        "Starting visualization for %s (3D enabled=%s)",
        label,
        include_3d,
    )
    logger.debug("Output directory: %s; random seed: %d", out, seed)
    out.mkdir(parents=True, exist_ok=True)
    logger.info("Parsing SMILES for %s", label)
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        logger.error("RDKit could not parse SMILES for %s", label)
        raise ValueError(f"Invalid SMILES: {smiles}")
    logger.info(
        "Parsed %s: %d atoms, %d bonds",
        label,
        molecule.GetNumAtoms(),
        molecule.GetNumBonds(),
    )
    logger.info("Computing 2D coordinates for %s", label)
    Chem.rdDepictor.Compute2DCoords(molecule)

    png_path = out / f"{stem}_2d.png"
    svg_path = out / f"{stem}_2d.svg"
    logger.info("Writing 2D PNG image: %s", png_path)
    Draw.MolToFile(molecule, str(png_path), size=image_size)
    logger.info("Writing 2D SVG image: %s", svg_path)
    Draw.MolToFile(molecule, str(svg_path), size=image_size)
    written = {"2d_png": png_path, "2d_svg": svg_path}
    logger.info("Completed 2D images for %s", label)
    if include_3d:
        logger.info("Starting optional 3D outputs for %s", label)
        structures = smiles_to_structures(
            smiles,
            stem,
            out,
            formats=("sdf", "pdb", "xyz"),
            seed=seed,
            standardize_fragments=False,
        )
        written.update({f"3d_{key}": value for key, value in structures.items()})
        html_path = out / f"{stem}_3d.html"
        _plot_3d_html(structures["pdb"], label, html_path)
        written["3d_html"] = html_path
    logger.info(
        "Visualization completed for %s; %d files created",
        label,
        len(written),
    )
    for output_path in written.values():
        logger.info("Output file: %s (%d bytes)", output_path, output_path.stat().st_size)
    return written


def create_molecule_contact_sheet(
    image_paths: Iterable[str | pathlib.Path],
    output_path: str | pathlib.Path,
    columns: int = 4,
    image_size: tuple[int, int] = (300, 225),
    padding: int = 16,
    caption_height: int = 36,
) -> pathlib.Path:
    """Combine molecule PNGs into one labeled contact-sheet PNG.

    Args:
        image_paths: Paths to PNG images created by ``create_molecule``.
        output_path: Destination PNG path. Its parent directory is created.
        columns: Number of image tiles per row.
        image_size: Maximum width and height of each image tile.
        padding: Space in pixels between tiles and around the sheet.
        caption_height: Height reserved for each image's filename caption.

    Returns:
        Path to the combined PNG image.

    Raises:
        TypeError: If paths or layout values have unsupported types.
        ValueError: If no images are provided or layout values are invalid.
        OSError: If an input image cannot be read or the output cannot be written.
    """
    if isinstance(image_paths, (str, pathlib.Path)):
        raise TypeError("image_paths must be an iterable of paths, not a single path")
    if not isinstance(columns, int) or isinstance(columns, bool):
        raise TypeError("columns must be an integer")
    if columns <= 0:
        raise ValueError("columns must be greater than zero")
    if (
        not isinstance(image_size, tuple)
        or len(image_size) != 2
        or any(not isinstance(size, int) or isinstance(size, bool) or size <= 0
               for size in image_size)
    ):
        raise ValueError("image_size must be a pair of positive integers")
    if not isinstance(padding, int) or isinstance(padding, bool):
        raise TypeError("padding must be an integer")
    if padding < 0:
        raise ValueError("padding must not be negative")
    if not isinstance(caption_height, int) or isinstance(caption_height, bool):
        raise TypeError("caption_height must be an integer")
    if caption_height <= 0:
        raise ValueError("caption_height must be greater than zero")

    paths = [pathlib.Path(path) for path in image_paths]
    if not paths:
        raise ValueError("At least one molecule PNG is required")
    destination = pathlib.Path(output_path)
    if destination.suffix.casefold() != ".png":
        raise ValueError("output_path must have a .png extension")
    if destination.resolve() in {path.resolve() for path in paths}:
        raise ValueError("output_path must not overwrite an input image")

    from PIL import Image, ImageDraw, ImageOps

    logger.info("Creating molecule contact sheet from %d PNG images", len(paths))
    thumbnails = []
    for path in paths:
        with Image.open(path) as source:
            if source.format != "PNG":
                raise ValueError(f"Input image is not a PNG: {path}")
            image = source.convert("RGBA")
            background = Image.new("RGBA", image.size, "white")
            background.alpha_composite(image)
            thumbnails.append(ImageOps.contain(background.convert("RGB"), image_size))

    rows = (len(paths) + columns - 1) // columns
    tile_height = image_size[1] + caption_height
    sheet = Image.new(
        "RGB",
        (
            columns * image_size[0] + (columns + 1) * padding,
            rows * tile_height + (rows + 1) * padding,
        ),
        "white",
    )
    draw = ImageDraw.Draw(sheet)
    for index, (path, thumbnail) in enumerate(zip(paths, thumbnails)):
        row, column = divmod(index, columns)
        tile_x = padding + column * (image_size[0] + padding)
        tile_y = padding + row * (tile_height + padding)
        image_x = tile_x + (image_size[0] - thumbnail.width) // 2
        image_y = tile_y + (image_size[1] - thumbnail.height) // 2
        sheet.paste(thumbnail, (image_x, image_y))

        caption = path.stem.removesuffix("_2d").replace("_", " ")
        while caption and draw.textbbox((0, 0), caption)[2] > image_size[0]:
            caption = caption[:-4] + "..." if len(caption) > 3 else caption[:-1]
        text_width = draw.textbbox((0, 0), caption)[2]
        draw.text(
            (tile_x + (image_size[0] - text_width) // 2, tile_y + image_size[1] + 4),
            caption,
            fill="black",
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, format="PNG")
    logger.info("Wrote molecule contact sheet: %s", destination)
    return destination


def create_molecule_gallery(
    smiles_list: Iterable[str],
    out_dir: str | pathlib.Path = "output",
    columns: int = 4,
) -> dict[str, object]:
    """Create individual 2D files and a combined contact sheet for SMILES.

    Args:
        smiles_list: SMILES strings to render, in the order shown in the gallery.
        out_dir: Directory where molecule images and the contact sheet are saved.
        columns: Number of molecule images per contact-sheet row.

    Returns:
        Mapping with status counts, per-molecule outputs, errors, and the
        contact-sheet path when at least one molecule is rendered.

    Raises:
        TypeError: If the input collection or its values have unsupported types.
        ValueError: If no non-empty SMILES strings are provided or columns is
            less than one.
        OSError: If generated images cannot be written.
    """
    if isinstance(smiles_list, str):
        raise TypeError("smiles_list must be an iterable of SMILES strings")
    if not isinstance(columns, int) or isinstance(columns, bool):
        raise TypeError("columns must be an integer")
    if columns <= 0:
        raise ValueError("columns must be greater than zero")

    smiles_values = list(smiles_list)
    if any(not isinstance(smiles, str) for smiles in smiles_values):
        raise TypeError("every smiles_list item must be a string")
    smiles_values = [smiles.strip() for smiles in smiles_values if smiles.strip()]
    if not smiles_values:
        raise ValueError("At least one non-empty SMILES string is required")

    out = pathlib.Path(out_dir)
    molecule_outputs: dict[str, dict[str, pathlib.Path]] = {}
    errors: dict[str, str] = {}
    image_paths = []
    logger.info("Creating 2D gallery for %d molecules", len(smiles_values))
    for index, smiles in enumerate(smiles_values, start=1):
        name = f"Compound {index}"
        try:
            outputs = create_molecule(smiles, name=name, out_dir=out)
        except (ImportError, OSError, TypeError, ValueError, RuntimeError) as error:
            errors[name] = str(error)
            logger.exception("Gallery molecule %s failed", name)
            continue
        molecule_outputs[name] = outputs
        image_paths.append(outputs["2d_png"])

    contact_sheet = None
    if image_paths:
        contact_sheet = create_molecule_contact_sheet(
            image_paths,
            out / "molecule-contact-sheet.png",
            columns=columns,
        )

    successful = len(molecule_outputs)
    failed = len(errors)
    status = "success" if failed == 0 else "partial" if successful else "failed"
    return {
        "status": status,
        "requested": len(smiles_values),
        "successful": successful,
        "failed": failed,
        "molecules": molecule_outputs,
        "errors": errors,
        "contact_sheet": contact_sheet,
    }


def batch(smiles_list, out_dir, **kw):
    """Generate structures for a batch while retaining per-molecule failures."""
    results, errors = {}, {}
    logger.info("Starting batch of molecule visualizations")
    for i, s in enumerate(smiles_list):
        name = f"mol_{i:04d}"
        try:
            results[name] = smiles_to_structures(s, name, out_dir, **kw)
        except (TypeError, ValueError, RuntimeError, OSError, ImportError) as e:
            errors[name] = str(e)                        # one bad SMILES doesn't stop the batch
            logger.exception("Batch item %s failed", name)
    logger.info(
        "Batch completed: %d succeeded, %d failed",
        len(results),
        len(errors),
    )
    return results, errors


def create_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("smiles", nargs="?", help="SMILES string for the molecule")
    parser.add_argument("--smiles-file", type=pathlib.Path, help="UTF-8 file containing one SMILES string")
    parser.add_argument("--name", help="Optional molecule name")
    parser.add_argument("--name-file", type=pathlib.Path, help="UTF-8 file containing an optional molecule name")
    parser.add_argument(
        "--gallery-smiles",
        help="Newline-separated SMILES strings for a combined 2D gallery",
    )
    parser.add_argument(
        "--gallery-smiles-file",
        type=pathlib.Path,
        help="UTF-8 file with one SMILES string per line for a combined 2D gallery",
    )
    parser.add_argument(
        "--gallery-columns",
        type=int,
        help="Number of molecules per contact-sheet row (default: 4)",
    )
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=pathlib.Path("/output"),
        help="Directory for generated structure files",
    )
    parser.add_argument(
        "--with-3d",
        action="store_true",
        help="Also generate a 3D HTML plot and SDF, PDB, and XYZ files",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include debug-level diagnostic messages",
    )
    return parser


def configure_logging(verbose: bool = False) -> None:
    """Configure timestamped progress logging to stderr."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the single-molecule or multi-molecule gallery command-line interface."""
    parser = create_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    logger.info("Visualization command started")
    try:
        if args.smiles_file is not None:
            if args.smiles is not None:
                raise ValueError("provide either positional SMILES or --smiles-file, not both")
            args.smiles = args.smiles_file.read_text(encoding="utf-8")
        if args.name_file is not None:
            if args.name is not None:
                raise ValueError("provide either --name or --name-file, not both")
            args.name = args.name_file.read_text(encoding="utf-8").strip() or None
        if args.gallery_smiles_file is not None:
            if args.gallery_smiles is not None:
                raise ValueError("provide either --gallery-smiles or --gallery-smiles-file, not both")
            args.gallery_smiles = args.gallery_smiles_file.read_text(encoding="utf-8")
        if args.gallery_smiles is not None:
            if args.smiles is not None or args.name is not None or args.with_3d:
                raise ValueError(
                    "--gallery-smiles cannot be combined with positional SMILES, "
                    "--name, or --with-3d"
                )
            gallery = create_molecule_gallery(
                args.gallery_smiles.splitlines(),
                out_dir=args.output_dir,
                columns=(
                    args.gallery_columns
                    if args.gallery_columns is not None
                    else 4
                ),
            )
            payload = {
                **gallery,
                "molecules": {
                    name: {key: str(path) for key, path in outputs.items()}
                    for name, outputs in gallery["molecules"].items()
                },
                "contact_sheet": (
                    str(gallery["contact_sheet"])
                    if gallery["contact_sheet"] is not None
                    else None
                ),
            }
            print(json.dumps(payload, indent=2))
            logger.info("Gallery command completed with status %s", gallery["status"])
            return 1 if gallery["status"] == "failed" else 0

        if args.smiles is None:
            parser.error("provide a SMILES string or --gallery-smiles")
        if args.gallery_columns is not None:
            raise ValueError("--gallery-columns can only be used with --gallery-smiles")
        outputs = create_molecule(
            args.smiles,
            name=args.name,
            out_dir=args.output_dir,
            include_3d=args.with_3d,
            seed=args.seed,
        )
    except (OSError, TypeError, ValueError, RuntimeError):
        logger.exception("Visualization command failed")
        return 1
    print(json.dumps({key: str(path) for key, path in outputs.items()}, indent=2))
    logger.info("Visualization command completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())