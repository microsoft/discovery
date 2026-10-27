"""Targeted stdlib unittest suite; Psi4 is mocked, NumPy is the existing dependency."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import psi4_utils as utils
import run_psi4_job as launcher


class Molecule:
    def __init__(self, charge=0, mult=1, x=0.0):
        self.charge, self.mult, self.position = charge, mult, x

    def multiplicity(self):
        return self.mult

    def molecular_charge(self):
        return self.charge

    def set_molecular_charge(self, value):
        self.charge = value

    def set_multiplicity(self, value):
        self.mult = value

    def clone(self):
        return copy.copy(self)

    def natom(self):
        return 1

    def symbol(self, index):
        return 'He'

    def x(self, index):
        return self.position

    def y(self, index):
        return 0.0

    def z(self, index):
        return 0.0


class OptimizationError(Exception):
    def __init__(self, wfn=None):
        self.wfn = wfn


class UtilityTests(unittest.TestCase):
    def setUp(self):
        self.psi4 = MagicMock()
        self.psi4.OptimizationConvergenceError = OptimizationError
        self.patch = patch.dict(sys.modules, {'psi4': self.psi4})
        self.patch.start()
        self.addCleanup(self.patch.stop)
        output_patch = patch.object(utils, 'OUTPUT_DIR', '')
        output_patch.start()
        self.addCleanup(output_patch.stop)
        self.molecule = Molecule()
        self.wfn = MagicMock()
        self.wfn.nirrep.return_value = 1
        self.wfn.epsilon_a.return_value = [-0.5, 0.1]
        self.wfn.nalpha.return_value = 1
        self.wfn.variable.return_value = np.array([[0.0, 0.0, 1.0]])
        self.wfn.molecule.return_value = self.molecule
        self.wfn.energy.return_value = -1.0
        self.psi4.energy.return_value = (-1.0, self.wfn)

    def test_reference_selected_for_each_energy_including_dft(self):
        for mult, reference in [(1, 'rhf'), (2, 'uhf'), (1, 'rhf')]:
            utils.compute_energy(Molecule(mult=mult), 'b3lyp', return_wfn=True)
            self.assertEqual(self.psi4.set_options.call_args.args[0]['reference'], reference)

    def test_explicit_reference_validated_before_energy(self):
        for reference in ['rhf', 'rks', 'invalid']:
            with self.assertRaises(ValueError):
                utils.compute_energy(Molecule(mult=2), reference=reference)
        self.psi4.energy.assert_not_called()
        utils.compute_energy(Molecule(mult=2), reference='ROHF', return_wfn=True)
        self.assertEqual(self.psi4.set_options.call_args.args[0]['reference'], 'rohf')

    def test_combined_properties_one_wavefunction_and_debye_conversion(self):
        result = utils.compute_electronic_properties(self.molecule)
        self.psi4.energy.assert_called_once()
        self.psi4.oeprop.assert_called_once_with(self.wfn, 'DIPOLE', title='DISCOVERY')
        self.wfn.variable.assert_called_once_with('DISCOVERY DIPOLE')
        self.assertAlmostEqual(result['dipole_moment_debye'], utils.DIPOLE_AU_TO_DEBYE)
        self.assertEqual(result['dipole_vector_debye'], [0.0, 0.0, utils.DIPOLE_AU_TO_DEBYE])
        self.assertAlmostEqual(result['gap_hartree'], 0.6)

    def test_gap_automatically_selects_uhf(self):
        result = utils.compute_homo_lumo_gap(Molecule(mult=2))
        self.assertAlmostEqual(result['gap_hartree'], 0.6)
        self.assertEqual(self.psi4.set_options.call_args.args[0]['reference'], 'uhf')

    def test_dipole_invalid_vectors_rejected(self):
        for vector in [[1, 2], [0, float('nan'), 0], [float('inf'), 0, 0]]:
            self.wfn.variable.return_value = vector
            with self.assertRaises(ValueError):
                utils.compute_dipole_moment(self.molecule)

    def test_empty_orbitals_rejected(self):
        self.wfn.nalpha.return_value = 0
        with self.assertRaises(ValueError):
            utils.compute_electronic_properties(self.molecule)

    def test_optimization_retries_once_from_last_geometry_without_weakening(self):
        self.psi4.energy.return_value = -0.9
        last = Molecule(mult=2, x=1.0)
        self.wfn.molecule.return_value = last
        self.psi4.optimize.side_effect = [OptimizationError(self.wfn), (-1.1, self.wfn)]
        result = utils.optimize_geometry(Molecule(mult=2), 'b3lyp', geom_maxiter=5,
                                         g_convergence='gau_tight')
        self.assertTrue(result['converged'])
        self.assertEqual(result['optimization_attempts'], 2)
        self.assertIs(self.psi4.optimize.call_args.kwargs['molecule'], last)
        settings = [call.args[0] for call in self.psi4.set_options.call_args_list]
        self.assertEqual(settings[-2:], [{'geom_maxiter': 5}, {'geom_maxiter': 10}])
        self.assertEqual(settings[0]['g_convergence'], 'gau_tight')
        self.assertEqual(settings[0]['reference'], 'uhf')

    def test_optimization_exhaustion_is_not_success(self):
        self.psi4.energy.return_value = -0.9
        self.psi4.optimize.side_effect = OptimizationError(self.wfn)
        result = utils.optimize_geometry(self.molecule)
        self.assertFalse(result['converged'])
        self.assertEqual(self.psi4.optimize.call_count, 2)

    def test_optimization_without_last_wavefunction_does_not_retry_initial_geometry(self):
        self.psi4.energy.return_value = -0.9
        self.psi4.optimize.side_effect = OptimizationError()
        self.assertFalse(utils.optimize_geometry(self.molecule)['converged'])
        self.assertEqual(self.psi4.optimize.call_count, 1)

    def test_scf_failure_not_swallowed(self):
        self.psi4.energy.side_effect = RuntimeError('SCF failed')
        with self.assertRaisesRegex(RuntimeError, 'SCF failed'):
            utils.compute_electronic_properties(self.molecule)

    def test_nonfinite_energy_and_unconverged_acceptance_rejected(self):
        self.psi4.energy.return_value = float('nan')
        with self.assertRaises(ValueError):
            utils.compute_energy(self.molecule)
        with self.assertRaises(ValueError):
            utils.compute_energy(self.molecule, fail_on_maxiter=False)

    def test_uppercase_restricted_override_cannot_bypass_validation(self):
        with self.assertRaises(ValueError):
            utils.compute_energy(Molecule(mult=2), REFERENCE='RHF')

    def test_setup_binds_iomanager_scratch(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            with patch.dict(os.environ, {'PSI_SCRATCH': directory}):
                utils.setup_psi4()
            self.psi4.core.IOManager.shared_object().set_default_path.assert_called_with(
                os.path.abspath(directory))


class ReorganizationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.directory.cleanup)
        self.patch = patch.object(utils, 'WORK_DIR', self.directory.name)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        output_patch = patch.object(utils, 'OUTPUT_DIR', '')
        output_patch.start()
        self.addCleanup(output_patch.stop)

    @staticmethod
    def state_result(directory, name, request):
        energies = {'opt_neutral': -10.0, 'opt_cation': -9.0, 'opt_anion': -10.2,
                    'cation_at_neutral': -8.9, 'neutral_at_cation': -9.95,
                    'anion_at_neutral': -10.1, 'neutral_at_anion': -9.97}
        return {'status': 'success', 'converged': True, 'energy_hartree': energies[name],
                'optimized_geometry': 'He 0 0 0', 'optimization_attempts': 1,
                'optimized_energy_hartree': energies[name]}

    def test_four_point_formulas_ids_units_states_and_seven_fresh_jobs(self):
        with patch.object(utils, '_run_reorganization_state', side_effect=self.state_result) as run:
            result = utils.compute_reorganization_energies(Molecule(), 'candidate-A')
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['candidate_id'], 'candidate-A')
        self.assertAlmostEqual(result['hole_reorganization_hartree'], 0.15)
        self.assertAlmostEqual(result['electron_reorganization_hartree'], 0.13)
        self.assertAlmostEqual(result['electron_reorganization_eV'], 0.13 * utils.HARTREE_TO_EV)
        self.assertEqual(result['energy_units'], 'hartree')
        self.assertEqual(run.call_count, 7)
        self.assertEqual([call.args[2]['charge'] for call in run.call_args_list],
                         [0, 1, -1, 1, 0, -1, 0])
        self.assertEqual([call.args[2]['multiplicity'] for call in run.call_args_list],
                         [1, 2, 2, 2, 1, 2, 1])
        self.assertEqual([state['reference'] for state in result['states'].values()],
                         ['rhf', 'uhf', 'uhf'])
        self.assertEqual(len(result['components']), 7)
        self.assertTrue((Path(result['artifact_directory']) / 'reorganization_result.json').exists())

    def test_failure_preserves_id_partial_components_and_json(self):
        def run(directory, name, request):
            if name == 'opt_cation':
                raise RuntimeError('unconverged')
            return self.state_result(directory, name, request)
        with patch.object(utils, '_run_reorganization_state', side_effect=run):
            result = utils.compute_reorganization_energies(Molecule(), 'candidate-B')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['components'], {'E_neutral_at_neutral': -10.0})
        self.assertNotIn('hole_reorganization_eV', result)
        self.assertIn('unconverged', result['error'])
        saved = json.loads((Path(result['artifact_directory']) / 'reorganization_result.json').read_text())
        self.assertEqual(saved['candidate_id'], 'candidate-B')

    def test_upstream_partial_neutral_never_assumed_converged(self):
        with patch.object(utils, '_run_reorganization_state',
                          return_value={'converged': False}) as run:
            result = utils.compute_reorganization_energies(Molecule(), 'candidate-C')
        self.assertEqual(run.call_args.args[1], 'opt_neutral')
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['states']['neutral']['converged'])

    def test_restricted_open_shell_rejected_before_jobs(self):
        with patch.object(utils, '_run_reorganization_state') as run:
            result = utils.compute_reorganization_energies(Molecule(), 'candidate-D', reference='rhf')
        self.assertEqual(result['status'], 'failed')
        run.assert_not_called()

    def test_worker_nonzero_exit_with_result_still_fails(self):
        directory = Path(self.directory.name)
        with patch.object(utils.subprocess, 'run', return_value=subprocess.CompletedProcess([], 7)):
            with self.assertRaisesRegex(RuntimeError, 'exit 7'):
                utils._run_reorganization_state(directory, 'bad_state', {'options': {}})
        self.assertTrue((directory / 'bad_state' / 'worker.out').exists())


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path.cwd(), prefix='launcher-tests-')
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)

    def start(self, script, output):
        return subprocess.Popen([sys.executable, str(Path(launcher.__file__)), str(script), str(output)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def test_concurrent_invocations_isolate_scratch_work_and_copy_nested_artifacts(self):
        script = self.root / 'script ; & spaces.py'
        script.write_text(
            "import json,os,time\nfrom pathlib import Path\n"
            "Path('nested').mkdir()\n"
            "Path('nested/scratch').mkdir()\n"
            "Path('nested/scratch/secret.dat').write_text('nested scratch')\n"
            "Path('logs.out').write_text('script own transcript')\n"
            "Path('nested/result.json').write_text(json.dumps(dict(work=os.getcwd(),"
            "scratch=os.environ['PSI_SCRATCH'])))\n"
            "Path(os.environ['PSI_SCRATCH'],'secret.dat').write_text('scratch')\n"
            "print('stdout evidence', flush=True)\n"
            "import sys; print('stderr evidence',file=sys.stderr,flush=True)\n"
            "time.sleep(0.1)\n", encoding='utf-8')
        outputs = [self.root / 'output one', self.root / 'output two']
        processes = [self.start(script, output) for output in outputs]
        for process in processes:
            stdout, _ = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, stdout)
        results = [json.loads((output / 'nested' / 'result.json').read_text()) for output in outputs]
        self.assertNotEqual(results[0]['work'], results[1]['work'])
        self.assertNotEqual(results[0]['scratch'], results[1]['scratch'])
        for output in outputs:
            self.assertIn('stderr evidence', (output / 'logs.out').read_text())
            self.assertEqual((output / 'script-logs.out').read_text(), 'script own transcript')
            self.assertFalse(list(output.rglob('secret.dat')))

    def test_child_exit_preserved_and_partial_artifacts_retained(self):
        script = self.root / 'fail.py'
        script.write_text("from pathlib import Path\nPath('partial.json').write_text('{}')\n"
                          "print('failing evidence')\nraise SystemExit(7)\n")
        output = self.root / 'output'
        process = self.start(script, output)
        stdout, _ = process.communicate(timeout=30)
        self.assertEqual(process.returncode, 7, stdout)
        self.assertTrue((output / 'partial.json').exists())
        self.assertEqual(json.loads((output / 'launcher_failure.json').read_text())['exit_code'], 7)

    def test_copy_failure_converts_success_to_failure_and_is_recorded(self):
        script = self.root / 'ok.py'
        script.write_text("print('ok')\n")
        output = self.root / 'output'
        with patch.object(launcher, 'copy_artifacts', side_effect=OSError('copy denied')):
            self.assertEqual(launcher.main([str(script), str(output)]), 1)
        self.assertIn('copy denied', (output / 'launcher_failure.json').read_text())

    def test_copy_failure_does_not_hide_child_exit(self):
        script = self.root / 'bad.py'
        script.write_text('raise SystemExit(7)\n')
        output = self.root / 'output'
        with patch.object(launcher, 'copy_artifacts', side_effect=OSError('copy denied')):
            self.assertEqual(launcher.main([str(script), str(output)]), 7)

    def test_setup_honors_work_env_without_replacing_input_output_paths(self):
        original = Path.cwd()
        input_dir, output_dir, work_dir = [self.root / name for name in ('input', 'out', 'work')]
        input_dir.mkdir()
        (input_dir / 'molecule.xyz').write_text('input')
        try:
            with patch.dict(os.environ, {'PSI4_WORK_DIR': str(work_dir),
                                        'PSI_SCRATCH': str(self.root / 'scratch')}):
                utils.setup_directories(str(input_dir), str(output_dir), work_dir='ignored')
            self.assertEqual(utils.INPUT_DIR, str(input_dir))
            self.assertEqual(utils.OUTPUT_DIR, str(output_dir))
            self.assertEqual(utils.WORK_DIR, str(work_dir))
            self.assertEqual((work_dir / 'molecule.xyz').read_text(), 'input')
        finally:
            os.chdir(original)


if __name__ == '__main__':
    unittest.main()
