import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


MODULE_NAME = "ligandmpnn_utils"
SPEC = importlib.util.spec_from_file_location(
    MODULE_NAME, Path(__file__).with_name(MODULE_NAME + ".py")
)
assert SPEC is not None and SPEC.loader is not None
utils = importlib.util.module_from_spec(SPEC)
sys.modules[MODULE_NAME] = utils
SPEC.loader.exec_module(utils)


@pytest.fixture
def workspace(tmp_path):
    inputs = tmp_path / "input"
    inputs.mkdir()
    return utils.quick_setup(inputs, tmp_path / "output", tmp_path / "workdir")


def test_setup_rejects_missing_inputs(tmp_path):
    with pytest.raises(FileNotFoundError, match="not mounted"):
        utils.quick_setup(tmp_path / "absent", tmp_path / "output", tmp_path / "workdir")


def test_setup_does_not_copy_inputs(workspace):
    (workspace.input_dir / "large.dat").write_text("input", encoding="utf-8")
    assert not list(workspace.work_dir.iterdir())


def test_setup_rejects_stale_manifest(workspace):
    utils.save_final_results({}, workspace=workspace)
    with pytest.raises(FileExistsError, match="fresh output"):
        utils.quick_setup(workspace.input_dir, workspace.output_dir, workspace.work_dir)


def test_input_mount_is_not_used_as_workdir(workspace):
    with pytest.raises(ValueError, match="input directory"):
        utils.quick_setup(workspace.input_dir, workspace.output_dir, workspace.input_dir)


def test_command_and_artifact_manifest(workspace):
    result = utils.run_command(
        [sys.executable, "-c", "from pathlib import Path; Path('result.txt').write_text('ok')"],
        workspace=workspace, expected_output_files=["result.txt"],
    )
    manifest = utils.save_final_results(
        {"returncode": result["returncode"]},
        {"result": result["output_files"][0]},
        {"result": "Scientific result"},
        workspace=workspace,
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert set(payload) == {"status", "summary", "output_files", "file_descriptions"}
    assert payload["status"] == "completed"
    assert Path(payload["output_files"]["result"]).read_text(encoding="utf-8") == "ok"
    assert utils.quick_finish(workspace=workspace) == manifest


def test_command_failure_propagates_and_retains_log(workspace):
    with pytest.raises(subprocess.CalledProcessError) as error:
        utils.run_command(
            [sys.executable, "-c", "print('diagnostic', flush=True); raise SystemExit(7)"],
            workspace=workspace, expected_output_files=["result.txt"],
        )
    assert error.value.returncode == 7
    assert "diagnostic" in (workspace.output_dir / "tool.log").read_text(encoding="utf-8")
    assert not (workspace.output_dir / "final_results.json").exists()


def test_missing_scientific_output_is_not_success(workspace):
    with pytest.raises(FileNotFoundError):
        utils.run_command(
            [sys.executable, "-c", "pass"],
            workspace=workspace, expected_output_files=["missing.txt"],
        )


def test_stale_output_does_not_count_as_success(workspace):
    (workspace.work_dir / "stale.txt").write_text("old", encoding="utf-8")
    with pytest.raises(FileExistsError, match="fresh scientific output"):
        utils.run_command(
            [sys.executable, "-c", "pass"],
            workspace=workspace, expected_output_files=["stale.txt"],
        )
    assert not (workspace.output_dir / "tool.log").exists()


def test_relative_artifacts_resolve_against_workdir(workspace):
    (workspace.work_dir / "result.txt").write_text("result", encoding="utf-8")
    path = utils.save_final_results({}, {"result": "result.txt"}, workspace=workspace)
    assert Path(json.loads(path.read_text(encoding="utf-8"))["output_files"]["result"]).is_file()


def test_timeout_propagates(workspace):
    with pytest.raises(subprocess.TimeoutExpired):
        utils.run_command(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            workspace=workspace, timeout=0.05, expected_output_files=["result.txt"],
        )


def test_missing_artifact_cannot_publish_success(workspace):
    with pytest.raises(FileNotFoundError):
        utils.save_final_results({}, {"missing": "absent.dat"}, workspace=workspace)
    assert not (workspace.output_dir / "final_results.json").exists()


def test_empty_file_is_rejected(workspace):
    empty = workspace.work_dir / "empty.txt"
    empty.touch()
    with pytest.raises(ValueError, match="empty"):
        utils.require_files([empty])


def test_failed_result_has_explicit_status(workspace):
    path = utils.save_final_results({"error": "inference failed"}, status="failed", workspace=workspace)
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "failed"
    with pytest.raises(ValueError, match="completed"):
        utils.save_final_results({"error": "inference failed"}, workspace=workspace)


def test_invalid_labels_and_descriptions_are_rejected(workspace):
    with pytest.raises(ValueError, match="Invalid artifact name"):
        utils.save_final_results({}, {"../bad": "result.txt"}, workspace=workspace)
    with pytest.raises(ValueError, match="declared output"):
        utils.save_final_results({}, {}, {"missing": "description"}, workspace=workspace)


def test_invalid_json_does_not_publish_manifest(workspace):
    with pytest.raises(ValueError):
        utils.save_final_results({"score": float("nan")}, workspace=workspace)
    assert not (workspace.output_dir / "final_results.json").exists()


def test_gpu_visibility_and_absence(monkeypatch):
    monkeypatch.setattr(utils.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="missing"):
        utils.require_gpu()
    monkeypatch.setattr(utils.shutil, "which", lambda _: "nvidia-smi")
    monkeypatch.setattr(
        utils.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "NVIDIA GPU\n", ""),
    )
    assert utils.require_gpu() == "NVIDIA GPU"
    monkeypatch.setattr(
        utils.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", ""),
    )
    with pytest.raises(RuntimeError, match="no NVIDIA GPU"):
        utils.require_gpu()


@pytest.mark.parametrize("argv,log_name,timeout,outputs", [
    ("python -c pass", "tool.log", 1, ["result.txt"]),
    ([], "tool.log", 1, ["result.txt"]),
    ([sys.executable], "../escape.log", 1, ["result.txt"]),
    ([sys.executable], "tool.log", 0, ["result.txt"]),
    ([sys.executable], "tool.log", 1, []),
])
def test_invalid_execution_arguments(workspace, argv, log_name, timeout, outputs):
    with pytest.raises(ValueError):
        utils.run_command(
            argv, workspace=workspace, log_name=log_name, timeout=timeout,
            expected_output_files=outputs,
        )
