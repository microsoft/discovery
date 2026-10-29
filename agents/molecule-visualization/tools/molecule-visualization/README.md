# Molecule Visualization Tool

## Architecture

The [tool definition](tool.yaml) exposes two CPU-only actions implemented by
[app/visualizations.py](app/visualizations.py):

| Action | Inputs | Outputs |
| --- | --- | --- |
| `visualize_molecule` | `smiles`, optional `name` and `include_3d` | PNG, SVG; optional self-contained HTML, SDF, PDB, XYZ |
| `visualize_molecule_gallery` | Newline-separated `smiles_list`, optional positive integer `columns` | Per-molecule PNG/SVG and `molecule-contact-sheet.png` |

Action commands supply arguments to the image's
`python /app/visualizations.py` entrypoint. SMILES and names are rendered into
inline UTF-8 files mounted under `/input`, not embedded in command strings.
The CLI accepts `--smiles-file`, `--name-file`, and `--gallery-smiles-file`;
the original direct-value CLI arguments remain available for local use.
An empty name file uses the default label. The CLI defaults to 2D-only output
and four gallery columns. Defaults are documented in input descriptions because
the catalog parameter schema does not accept a `default` keyword.

## Image and dependencies

The [Dockerfile](Dockerfile) uses a digest-pinned Python 3.12 Debian Bookworm
slim image. [requirements.txt](requirements.txt) pins NumPy 1.26.4,
RDKit 2026.9.1, Plotly 7.0.0, and Pillow 13.0.0. Dependencies are installed as
binary wheels at build time and checked with `pip check`; transitive
dependencies and OS packages are not fully locked.

The image runs as UID/GID `10001:10001`, with writable `/input`, `/output`,
`/workdir`, and home directory. Configure mounted inputs read-only and mounted
outputs writable at deployment. Non-root identity alone is not a security
sandbox. No external API credentials or runtime package installation are needed.
Only the Dockerfile, requirements, and application source enter the build context.

The registry is substituted using `{name}`; the image repository and version
are `molecule-visualizations:1.1.3`. Review base-image and package updates,
scan the image, and rerun validation before publication.

## Build and local smoke tests

Run from the repository root in PowerShell with Docker Linux containers:

```powershell
docker build --tag molecule-visualizations:1.1.3 .\agents\molecule-visualization\tools\molecule-visualization
docker run --rm --network none molecule-visualizations:1.1.3 --help
docker run --rm --network none molecule-visualizations:1.1.3 CCO --name ethanol
docker run --rm --network none molecule-visualizations:1.1.3 CCO --name ethanol --with-3d
docker run --rm --network none molecule-visualizations:1.1.3 --gallery-smiles "CCO`nc1ccccc1" --gallery-columns 2
```

These commands print JSON output paths and diagnostic logs. Files in an
unmounted container disappear when it exits. To retain artifacts:

```powershell
New-Item -ItemType Directory -Force .\molecule-visualization-output | Out-Null
$OutputPath = (Resolve-Path .\molecule-visualization-output).Path
docker run --rm --network none --mount "type=bind,source=$OutputPath,target=/output" molecule-visualizations:1.1.3 CCO --name ethanol --with-3d
```

The mount must be writable by the non-root user. Keep generated files out of
the catalog contribution. Check file contents as well as exit codes.

The Dockerfile uses standard build instructions compatible with ACR Tasks'
classic builder and local Docker; it does not require BuildKit secret mounts.
Package downloads require access to PyPI. Never commit package-feed credentials
or disable TLS verification to work around connectivity problems.

## Outputs and errors

For label `ethanol`, expect `ethanol_2d.png` and `ethanol_2d.svg`.
With `--with-3d`, also expect `ethanol_3d.html`, `ethanol.sdf`, `ethanol.pdb`,
and `ethanol.xyz`. Plotly JavaScript is embedded in the HTML, so it opens
offline as a single file with no sibling JavaScript file or CDN dependency.
Interactive plots require JavaScript and WebGL. If Studio's artifact preview
restricts them, download the HTML and open it in a compatible browser.
Names are sanitized for filenames; use unique names to avoid
overwriting outputs.

For Python callers, `smiles_to_structures` defaults to SMI, SDF, PDB, and XYZ.
CIF is not supported; unsupported formats are rejected before files are written.
The deployed action explicitly requests SDF, PDB, and XYZ, so its outputs are
unchanged.

Gallery labels follow non-empty input-line order as `Compound 1`, `Compound 2`,
and so on. JSON includes status, counts, per-molecule outputs, errors, and the
contact-sheet path. Partial galleries can exit zero; callers must inspect
status and failed counts. Fully failed galleries and single-molecule errors
return a nonzero exit code.
3D output requires MMFF optimization status zero, with up to 2,000 MMFF
iterations. Unsupported force-field parameters, nonconvergence, and unexpected
optimizer statuses fail explicitly.
Previously written 2D files may remain after a 3D failure; they are partial
outputs, not evidence that the full request succeeded.

No persistent cross-call filesystem state is assumed. The platform must promote
the `/output` mount into user-visible resources; local file paths are not
download URLs. Validate live command-template rendering, confirmation, mounted
permissions, and output promotion separately after deployment.

## Validation performed

Run the [container regressions](tests/test_visualizations.py) from the repository root:

```powershell
python -B -m unittest discover -s .\agents\molecule-visualization\tools\molecule-visualization\tests -p "test_*.py" -v
```

Set `MOLECULE_VISUALIZATION_IMAGE` to test a different image tag. Tests require
Docker and an already built image; missing prerequisites fail explicitly.
They run offline with Linux capabilities dropped and `no-new-privileges`,
covering runtime versions, UID, writable directories, file-based quoted names,
2D and 3D artifacts, extended-MMFF-budget regressions for CSV molecules,
partial galleries and duplicate order, optimizer failures,
invalid inputs, and legacy CLI compatibility. Live Discovery template rendering,
inline-file mounting, and artifact promotion require separate deployment tests.
