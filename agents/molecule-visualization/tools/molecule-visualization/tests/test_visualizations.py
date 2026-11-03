"""Container regressions; build molecule-visualizations:1.1.3 before running."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


IMAGE = os.environ.get("MOLECULE_VISUALIZATION_IMAGE", "molecule-visualizations:1.1.3")


class VisualizationTests(unittest.TestCase):
    def run_container(self, *arguments, mounts=(), python=False):
        command = [
            "docker", "run", "--rm", "--network", "none",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        ]
        for mount in mounts:
            command.extend(["--mount", mount])
        if python:
            command.extend(["--entrypoint", "python"])
        command.extend([IMAGE, *arguments])
        return subprocess.run(command, capture_output=True, text=True, timeout=120)

    def assert_files(self, directory, names):
        for name in names:
            path = Path(directory) / name
            self.assertTrue(path.is_file(), str(path))
            self.assertGreater(path.stat().st_size, 0)
            if path.suffix == ".png":
                self.assertTrue(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
            if path.suffix == ".svg":
                self.assertIn("<svg", path.read_text(encoding="utf-8"))

    def test_structure_helper_defaults_use_supported_formats(self):
        result = self.run_container("-c", """
import sys, tempfile
from pathlib import Path
sys.path.insert(0, '/app')
from visualizations import smiles_to_structures
from rdkit import Chem
with tempfile.TemporaryDirectory(dir='/output') as directory:
    outputs = smiles_to_structures('CCO', 'ethanol', directory)
    assert set(outputs) == {'smi', 'sdf', 'pdb', 'xyz'}, outputs
    assert all(path.is_file() and path.stat().st_size > 0 for path in outputs.values())
    assert Chem.SDMolSupplier(str(outputs['sdf']), removeHs=False)[0] is not None
with tempfile.TemporaryDirectory(dir='/output') as directory:
    try:
        smiles_to_structures('CCO', 'ethanol', directory, formats=('pdb', 'cif'))
    except ValueError as error:
        assert 'Unsupported structure formats: cif' in str(error), str(error)
    else:
        raise AssertionError('Unsupported CIF format was silently accepted')
    assert not list(Path(directory).iterdir())
""", python=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_runtime_and_dependencies(self):
        result = self.run_container("-c", """
import os, sys, tempfile
from pathlib import Path
import numpy, rdkit, plotly, PIL
assert sys.version_info[:2] == (3, 12)
assert os.getuid() == 10001
assert numpy.__version__ == '1.26.4'
assert rdkit.__version__ == '2026.09.1'
assert plotly.__version__ == '7.0.0'
assert PIL.__version__ == '13.0.0'
assert not Path('/etc/pip.conf').exists()
for directory in ['/output', '/workdir', os.environ['HOME']]:
    with tempfile.TemporaryFile(dir=directory): pass
""", python=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_single_molecule_file_inputs_preserve_quoted_names(self):
        with tempfile.TemporaryDirectory() as inputs, tempfile.TemporaryDirectory() as output:
            (Path(inputs) / "molecule.smiles").write_text("CCO", encoding="utf-8")
            (Path(inputs) / "molecule.name").write_text("O'Brien $(touch /output/injected)", encoding="utf-8")
            result = self.run_container(
                "--smiles-file", "/input/molecule.smiles",
                "--name-file", "/input/molecule.name",
                mounts=(
                    f"type=bind,source={inputs},target=/input,readonly",
                    f"type=bind,source={output},target=/output",
                ),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(set(payload), {"2d_png", "2d_svg"})
            self.assert_files(output, [Path(p).name for p in payload.values()])
            self.assertFalse((Path(output) / "injected").exists())

    def test_empty_optional_name_file_uses_default(self):
        with tempfile.TemporaryDirectory() as inputs, tempfile.TemporaryDirectory() as output:
            (Path(inputs) / "smiles").write_text("CCO", encoding="utf-8")
            (Path(inputs) / "name").write_text("", encoding="utf-8")
            result = self.run_container(
                "--smiles-file", "/input/smiles", "--name-file", "/input/name",
                mounts=(
                    f"type=bind,source={inputs},target=/input,readonly",
                    f"type=bind,source={output},target=/output",
                ),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assert_files(output, ["molecule_2d.png", "molecule_2d.svg"])

    def test_gallery_file_preserves_duplicates_and_reports_partial_failure(self):
        with tempfile.TemporaryDirectory() as inputs, tempfile.TemporaryDirectory() as output:
            (Path(inputs) / "gallery").write_text("CCO\n\ninvalid\nCCO\n", encoding="utf-8")
            result = self.run_container(
                "--gallery-smiles-file", "/input/gallery", "--gallery-columns", "2",
                mounts=(
                    f"type=bind,source={inputs},target=/input,readonly",
                    f"type=bind,source={output},target=/output",
                ),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual((payload["status"], payload["requested"], payload["successful"], payload["failed"]),
                             ("partial", 3, 2, 1))
            self.assertEqual(list(payload["molecules"]), ["Compound 1", "Compound 3"])
            self.assertEqual(list(payload["errors"]), ["Compound 2"])
            self.assert_files(output, ["Compound_1_2d.png", "Compound_3_2d.svg", "molecule-contact-sheet.png"])

    def test_three_dimensional_files_are_valid(self):
        result = self.run_container("-c", """
import sys, tempfile
from pathlib import Path
sys.path.insert(0, '/app')
from visualizations import create_molecule
from rdkit import Chem
from html.parser import HTMLParser
class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []
    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.sources.extend(value for key, value in attrs if key == 'src')
for smiles, name, atom_count in [('CCO', 'ethanol', 9), ('c1ccccc1', 'benzene', 12)]:
    with tempfile.TemporaryDirectory(dir='/output') as directory:
        outputs = create_molecule(smiles, name=name, out_dir=directory, include_3d=True)
        assert set(outputs) == {'2d_png','2d_svg','3d_html','3d_sdf','3d_pdb','3d_xyz'}
        assert all(p.is_file() and p.stat().st_size > 0 for p in outputs.values())
        molecule = Chem.SDMolSupplier(str(outputs['3d_sdf']), removeHs=False)[0]
        assert molecule is not None and molecule.GetNumAtoms() == atom_count
        html = outputs['3d_html'].read_text()
        scripts = Scripts()
        scripts.feed(html)
        assert not scripts.sources, scripts.sources
        assert 'Plotly.newPlot' in html
        assert len(html) > 1_000_000
        assert not (Path(directory) / 'plotly.min.js').exists()
""", python=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_large_csv_molecules_converge_with_extended_mmff_budget(self):
        result = self.run_container("-c", """
import sys, tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, '/app')
import visualizations as v
molecules = [
    ('O[C@H]([C@H]([C@H](OC1=C(C(CCC2=CC=C(OC)C(O)=C2)=O)C(O)=CC(O)=C1)O3)O)[C@H](O)[C@H]3CO', 'Compound_2'),
    ('OC1=C(C(OC(C2=CC=C(OC)C(O[C@@H]3O[C@H](CO)[C@@H](O)[C@H](O)[C@H]3O)=C2)C4)=O)C4=CC=C1', 'glycosylated_phyllodulcin'),
]
for smiles, name in molecules:
    with tempfile.TemporaryDirectory(dir='/output') as directory:
        with patch.object(v.AllChem, 'MMFFOptimizeMolecule', wraps=v.AllChem.MMFFOptimizeMolecule) as optimize:
            outputs = v.create_molecule(smiles, name=name, out_dir=directory, include_3d=True)
        assert optimize.call_args.kwargs['maxIters'] == 2000, optimize.call_args
        assert set(outputs) == {'2d_png','2d_svg','3d_html','3d_sdf','3d_pdb','3d_xyz'}
        assert all(path.is_file() and path.stat().st_size > 0 for path in outputs.values())
""", python=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_optimization_failures_do_not_return_success(self):
        result = self.run_container("-c", """
import sys, tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, '/app')
import visualizations as v
for status, message in [(-1, 'parameters are unavailable'), (1, 'did not converge'), (2, 'status 2')]:
    with tempfile.TemporaryDirectory(dir='/output') as directory:
        with patch.object(v.AllChem, 'MMFFOptimizeMolecule', return_value=status):
            try:
                v.create_molecule('CCO', out_dir=directory, include_3d=True)
            except RuntimeError as error:
                assert message in str(error), str(error)
            else:
                raise AssertionError('Optimization failure returned success')
            assert v.main(['CCO', '--with-3d', '--output-dir', directory]) == 1
            assert not list(Path(directory).glob('*.sdf'))
            assert not list(Path(directory).glob('*.html'))
""", python=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_invalid_cli_inputs_fail_explicitly(self):
        for arguments in [
            ("invalid",),
            ("--smiles-file", "/input/missing"),
            ("CCO", "--smiles-file", "/input/missing"),
            ("--gallery-smiles", "invalid"),
            ("--gallery-smiles", "CCO", "--gallery-columns", "0"),
            ("--gallery-smiles", "CCO", "--gallery-smiles-file", "/input/missing"),
        ]:
            with self.subTest(arguments=arguments):
                result = self.run_container(*arguments)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_legacy_cli_remains_available(self):
        result = self.run_container("CCO", "--name", "ethanol")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(set(json.loads(result.stdout)), {"2d_png", "2d_svg"})


if __name__ == "__main__":
    unittest.main()
