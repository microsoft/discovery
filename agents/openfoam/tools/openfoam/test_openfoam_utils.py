#!/usr/bin/env python3
"""Unit tests for openfoam_utils.py — run with pytest.

Tests case setup, file generation, and parsing functions.
Does NOT require OpenFOAM to be installed.
"""
import pytest
import os
import sys
import json
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(__file__))
from openfoam_utils import (
    create_case_directory,
    write_file,
    foam_header,
    write_control_dict,
    write_fv_schemes,
    write_fv_solution,
    write_transport_properties,
    write_turbulence_properties,
    write_scalar_field,
    write_vector_field,
    write_block_mesh_dict_box,
    write_block_mesh_dict_pipe,
    setup_pipe_flow,
    setup_box_flow,
    setup_heated_surface,
    parse_solver_log,
    save_final_results,
)


@pytest.fixture
def tmp_case(tmp_path):
    """Create a temporary case directory."""
    case_dir = str(tmp_path / "test_case")
    create_case_directory(case_dir)
    return case_dir


class TestCaseSetup:
    def test_create_case_directory(self, tmp_path):
        case_dir = str(tmp_path / "new_case")
        result = create_case_directory(case_dir)
        assert os.path.isdir(os.path.join(result, '0'))
        assert os.path.isdir(os.path.join(result, 'constant'))
        assert os.path.isdir(os.path.join(result, 'system'))

    def test_write_file(self, tmp_case):
        path = write_file(tmp_case, 'system/testFile', 'hello world')
        assert os.path.exists(path)
        with open(path) as f:
            assert f.read() == 'hello world'

    def test_foam_header_with_location(self):
        header = foam_header("dictionary", "controlDict", "system")
        assert "class       dictionary;" in header
        assert "object      controlDict;" in header
        assert 'location    "system"' in header

    def test_foam_header_without_location(self):
        header = foam_header("dictionary", "controlDict")
        assert 'location' not in header


class TestSystemFiles:
    def test_control_dict(self, tmp_case):
        path = write_control_dict(tmp_case, end_time=500, delta_t=1,
                                  application="simpleFoam")
        assert os.path.exists(path)
        with open(path) as f:
            content = f.read()
        assert 'simpleFoam' in content
        assert 'endTime         500' in content

    def test_control_dict_transient(self, tmp_case):
        path = write_control_dict(tmp_case, end_time=1.0, delta_t=0.001,
                                  application="icoFoam",
                                  adjustable_time_step=True, max_co=0.5)
        with open(path) as f:
            content = f.read()
        assert 'adjustTimeStep  yes' in content
        assert 'maxCo           0.5' in content

    def test_fv_schemes_steady(self, tmp_case):
        path = write_fv_schemes(tmp_case, steady=True)
        with open(path) as f:
            content = f.read()
        assert 'steadyState' in content

    def test_fv_schemes_transient(self, tmp_case):
        path = write_fv_schemes(tmp_case, steady=False)
        with open(path) as f:
            content = f.read()
        assert 'Euler' in content

    def test_fv_solution_steady(self, tmp_case):
        path = write_fv_solution(tmp_case, steady=True)
        with open(path) as f:
            content = f.read()
        assert 'SIMPLE' in content
        assert 'GAMG' in content

    def test_fv_solution_transient(self, tmp_case):
        path = write_fv_solution(tmp_case, steady=False)
        with open(path) as f:
            content = f.read()
        assert 'PIMPLE' in content


class TestConstantFiles:
    def test_transport_properties(self, tmp_case):
        path = write_transport_properties(tmp_case, nu=1.5e-5)
        with open(path) as f:
            content = f.read()
        assert '1.5e-05' in content
        assert 'Newtonian' in content

    def test_turbulence_properties_rans(self, tmp_case):
        path = write_turbulence_properties(tmp_case, model_type="kOmegaSST")
        with open(path) as f:
            content = f.read()
        assert 'kOmegaSST' in content
        assert 'RAS' in content

    def test_turbulence_properties_laminar(self, tmp_case):
        path = write_turbulence_properties(tmp_case, model_type="laminar")
        with open(path) as f:
            content = f.read()
        assert 'laminar' in content
        assert 'RAS' not in content


class TestBoundaryConditions:
    def test_scalar_field(self, tmp_case):
        path = write_scalar_field(
            tmp_case, 'p', '[0 2 -2 0 0 0 0]', 'uniform 0',
            {'inlet': {'type': 'zeroGradient'},
             'outlet': {'type': 'fixedValue', 'value': 'uniform 0'}}
        )
        assert os.path.exists(path)
        with open(path) as f:
            content = f.read()
        assert 'volScalarField' in content
        assert 'zeroGradient' in content
        assert 'fixedValue' in content

    def test_vector_field(self, tmp_case):
        path = write_vector_field(
            tmp_case, 'U', '[0 1 -1 0 0 0 0]', 'uniform (1 0 0)',
            {'inlet': {'type': 'fixedValue', 'value': 'uniform (1 0 0)'},
             'outlet': {'type': 'zeroGradient'}}
        )
        with open(path) as f:
            content = f.read()
        assert 'volVectorField' in content
        assert 'uniform (1 0 0)' in content


class TestMeshGeneration:
    def test_box_mesh(self, tmp_case):
        path = write_block_mesh_dict_box(
            tmp_case, 0, 1, 0, 0.5, 0, 0.1, 20, 10, 1
        )
        with open(path) as f:
            content = f.read()
        assert 'hex' in content
        assert '(20 10 1)' in content

    def test_pipe_mesh(self, tmp_case):
        path = write_block_mesh_dict_pipe(
            tmp_case, length=1.0, radius=0.05, nx=50, nr=10
        )
        with open(path) as f:
            content = f.read()
        assert 'wedge' in content
        assert 'hex' in content


class TestScenarioPresets:
    def test_pipe_flow_laminar(self, tmp_case):
        params = setup_pipe_flow(tmp_case, velocity=0.01, diameter=0.01,
                                 length=0.1, nu=1e-6)
        assert params['reynolds_number'] == pytest.approx(100.0)
        assert params['turbulence_model'] == 'laminar'
        assert params['solver'] == 'icoFoam'
        # Verify all files exist
        assert os.path.exists(os.path.join(tmp_case, 'system/controlDict'))
        assert os.path.exists(os.path.join(tmp_case, 'system/blockMeshDict'))
        assert os.path.exists(os.path.join(tmp_case, '0/U'))
        assert os.path.exists(os.path.join(tmp_case, '0/p'))

    def test_pipe_flow_turbulent(self, tmp_case):
        params = setup_pipe_flow(tmp_case, velocity=1.0, diameter=0.1,
                                 length=1.0, nu=1e-6)
        assert params['reynolds_number'] == pytest.approx(100000.0)
        assert params['turbulence_model'] == 'kOmegaSST'
        assert params['solver'] == 'simpleFoam'
        assert os.path.exists(os.path.join(tmp_case, '0/k'))
        assert os.path.exists(os.path.join(tmp_case, '0/omega'))
        assert os.path.exists(os.path.join(tmp_case, '0/nut'))

    def test_box_flow(self, tmp_case):
        params = setup_box_flow(tmp_case, velocity=1.0, domain_x=2.0,
                                domain_y=1.0, nu=1e-6)
        assert params['solver'] == 'simpleFoam'
        assert os.path.exists(os.path.join(tmp_case, 'system/controlDict'))

    def test_heated_surface(self, tmp_case):
        params = setup_heated_surface(tmp_case, velocity=1.0,
                                      T_inlet=300, T_wall=400)
        assert params['T_inlet'] == 300
        assert params['T_wall'] == 400
        assert os.path.exists(os.path.join(tmp_case, '0/T'))


class TestLogParsing:
    def test_parse_solver_log(self, tmp_path):
        # Create a fake solver log
        log_content = """
Time = 1

smoothSolver:  Solving for Ux, Initial residual = 1, Final residual = 0.1, No Iterations 5
smoothSolver:  Solving for Uy, Initial residual = 0.5, Final residual = 0.05, No Iterations 3
GAMG:  Solving for p, Initial residual = 1, Final residual = 0.01, No Iterations 10
ExecutionTime = 0.5 s

Time = 2

smoothSolver:  Solving for Ux, Initial residual = 0.1, Final residual = 0.001, No Iterations 5
smoothSolver:  Solving for Uy, Initial residual = 0.05, Final residual = 0.0005, No Iterations 3
GAMG:  Solving for p, Initial residual = 0.01, Final residual = 0.0001, No Iterations 8
ExecutionTime = 1.0 s

End
"""
        log_file = str(tmp_path / "log.simpleFoam")
        with open(log_file, 'w') as f:
            f.write(log_content)

        result = parse_solver_log(log_file)
        assert result['n_iterations'] == 2
        assert abs(result['final_residuals']['Ux'] - 0.001) < 1e-10
        assert abs(result['final_residuals']['p'] - 0.0001) < 1e-10
        assert result['execution_time'] == 1.0

    def test_parse_missing_log(self, tmp_path):
        result = parse_solver_log(str(tmp_path / "nonexistent.log"))
        assert 'error' in result


class TestResultsSaving:
    def test_save_final_results(self, tmp_path):
        global OUTPUT_DIR
        import openfoam_utils
        orig = openfoam_utils.OUTPUT_DIR
        openfoam_utils.OUTPUT_DIR = str(tmp_path)

        save_final_results(
            {'pressure_drop': 150.3, 'reynolds': 50000},
            output_files={'log': '/output/log.simpleFoam'},
            file_descriptions={'log': 'Solver log'}
        )

        result_file = tmp_path / 'final_results.json'
        assert result_file.exists()
        data = json.loads(result_file.read_text())
        assert data['status'] == 'completed'
        assert data['summary']['pressure_drop'] == 150.3

        openfoam_utils.OUTPUT_DIR = orig


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
