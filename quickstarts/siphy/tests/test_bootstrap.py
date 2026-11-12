"""Standard-library tests; fixtures stay under this project, never a temp directory."""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import time
import unittest
from unittest import mock
import uuid


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("siphy_bootstrap", HERE / "bootstrap.py")
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)

EXPECTED_PROMPT = """First, use hardware-spec-dev agent to create the CoreSPI specification document.
Next, create a specification markdown document in knowledge directory for the CORESPI_HB device.
Then use these three agents in order to implement and verify the design described in knowledge/CORESPI_HB.md:

chip-rtl-design: Read the specification, create synthesizable veirlog, and run the design checks.
chip-rtl-lint: Check the RTL with the default lint rules and canonical formatting check. Fix any issues before continuing.
chip-functional-verification: Create an independent, self-checking testbench from the specification, run simulation, and produce a VCD waveform.
If the RTL changes, repeat all checks on the final version. Report PASS only when design checks, lint, formatting, and simulation all pass. Otherwise, report the actual failure.

Save the RTL, testbench, waveform, and a short results summary, and provide links to them. Save all generated files—including RTL, testbench, logs, waveform, and results summaries—under results/<unique-run-id>/ in this project, rather than under sessions/.
""".encode()


class ProjectTest(unittest.TestCase):
    def setUp(self):
        self.work = bootstrap.filesystem_path(
            HERE / "tests" / (".bootstrap-test-work-" + uuid.uuid4().hex))
        self.work.mkdir()
        self.addCleanup(self.remove_work)

    def remove_work(self):
        # Windows scanners can briefly retain handles to newly created fixture trees.
        for attempt in range(6):
            try:
                shutil.rmtree(self.work)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.1 * (2 ** attempt))

    def fixture_archive(self, members):
        path = self.work / "fixture.tar"
        with tarfile.open(path, "w", format=tarfile.PAX_FORMAT) as archive:
            for entry in members:
                if isinstance(entry, tuple):
                    name, content = entry
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    archive.addfile(info, io.BytesIO(content))
                else:
                    archive.addfile(entry)
        data = path.read_bytes()
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(bootstrap, "ARCHIVE_SIZE", len(data)))
        stack.enter_context(mock.patch.object(bootstrap, "ARCHIVE_SHA256", hashlib.sha256(data).hexdigest()))
        self.addCleanup(stack.close)
        return path


class ArchiveSafetyTests(ProjectTest):
    def test_pinned_original_checksum_and_complete_inventory(self):
        original = HERE / "files" / "ship.tar"
        self.assertEqual(original.stat().st_size, 40992256)
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),
                         "f06834009e5e28b0c2cb18f3b7ff5227d1cb8ee2ecbd84f41eda157f8907159c")
        files, inventory = bootstrap.read_archive(original)
        self.assertEqual(len(inventory), 351)
        self.assertEqual(len(files), 314)
        self.assertEqual(sum(entry["size"] for entry in inventory), 40717812)
        self.assertEqual(set(files), {entry["path"] for entry in inventory if entry["kind"] == "file"})
        self.assertTrue(all(entry["sha256"] == bootstrap.digest(files[entry["path"]])
                            for entry in inventory if entry["kind"] == "file"))

    def test_wrong_checksum(self):
        path = self.work / "wrong.tar"
        path.write_bytes(b"not the original")
        with self.assertRaisesRegex(bootstrap.BootstrapError, "SHA-256 mismatch"):
            bootstrap.read_archive(path)

    def test_same_size_corruption(self):
        path = self.work / "wrong.tar"
        content = bytearray((HERE / "files" / "ship.tar").read_bytes())
        content[-1] ^= 1
        path.write_bytes(content)
        with self.assertRaisesRegex(bootstrap.BootstrapError, "SHA-256 mismatch"):
            bootstrap.read_archive(path)

    def test_rejects_all_unsafe_paths_even_unselected(self):
        names = [
            "../escape", "/absolute", "C:/escape", "ship/../escape",
            "ship/knowledge/bs_data/../../../../escape", "ship\\escape",
            "ship//escape", "ship/./escape", "ship/file:stream",
            "ship/NUL.txt", "ship/COM1", "ship/trailing.", "ship/trailing ",
            "ship/line\nbreak", "ship/question?", "other/file",
        ]
        for name in names:
            with self.subTest(name=name):
                archive = self.fixture_archive([(name, b"bad")])
                with self.assertRaisesRegex(bootstrap.BootstrapError, "path|root"):
                    bootstrap.read_archive(archive)
        self.assertFalse((self.work / "escape").exists())

    def test_rejects_symlink_hardlink_devices_fifo_and_sparse(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE,
                     tarfile.BLKTYPE, tarfile.FIFOTYPE, tarfile.GNUTYPE_SPARSE):
            with self.subTest(kind=kind):
                info = tarfile.TarInfo("ship/knowledge/bs_data/unsafe")
                info.type = kind
                info.linkname = "../../escape"
                archive = self.fixture_archive([info])
                with self.assertRaisesRegex(bootstrap.BootstrapError, "Unsupported"):
                    bootstrap.read_archive(archive)

    def test_rejects_duplicate_case_and_unicode_collisions(self):
        for first, second in (
            ("ship/file", "ship/file"), ("ship/File", "ship/file"),
            ("ship/caf\u00e9", "ship/cafe\u0301"),
        ):
            with self.subTest(first=first):
                archive = self.fixture_archive([(first, b"1"), (second, b"2")])
                with self.assertRaisesRegex(bootstrap.BootstrapError, "Duplicate"):
                    bootstrap.read_archive(archive)

    def test_rejects_file_directory_prefix_collision_in_any_order(self):
        for members in (
            [("ship/foo", b"1"), ("ship/foo/bar", b"2")],
            [("ship/foo/bar", b"2"), ("ship/foo", b"1")],
        ):
            archive = self.fixture_archive(members)
            with self.assertRaisesRegex(bootstrap.BootstrapError, "collision"):
                bootstrap.read_archive(archive)

    def test_incomplete_selected_layout_is_not_accepted(self):
        archive = self.fixture_archive([("ship/README.md", b"legacy")])
        with self.assertRaisesRegex(bootstrap.BootstrapError, "Incomplete selected archive layout"):
            bootstrap.read_archive(archive)

    def test_symlink_in_excluded_research_cannot_hide_behind_selection(self):
        info = tarfile.TarInfo("ship/knowledge/bs_data/paper.pdf")
        info.type = tarfile.SYMTYPE
        info.linkname = "/outside"
        archive = self.fixture_archive([info])
        with self.assertRaisesRegex(bootstrap.BootstrapError, "Unsupported"):
            bootstrap.make_payload(archive, HERE / bootstrap.GUIDE)


class PreparationTests(ProjectTest):
    @classmethod
    def setUpClass(cls):
        cls.payload, cls.manifest = bootstrap.make_payload(
            HERE / "files" / "ship.tar", HERE / bootstrap.GUIDE)

    def test_default_selection_is_minimal_and_complete(self):
        self.assertFalse(any("bs_data" in path or path.endswith(".pdf") for path in self.payload))
        self.assertFalse(any("discovery-add-agents" in path for path in self.payload))
        self.assertFalse(any("__pycache__" in path or ".pytest_cache" in path for path in self.payload))
        self.assertEqual(
            {Path(path).name for path in self.payload if path.startswith(".github/agents/")},
            {name + ".agent.md" for name in bootstrap.AGENTS})
        for context in bootstrap.IMAGES.values():
            for filename in ("Dockerfile", "Containerfile", "run.py", "tool.yaml", "entrypoint.sh"):
                self.assertIn(f"discovery_catalog/{context}/{filename}", self.payload)
        self.assertIn(".github/skills/report-gen/scripts/render_report.py", self.payload)
        self.assertIn(".github/skills/quickstart-runner/SKILL.md", self.payload)

    def test_shared_runner_is_exact_authoritative_repository_package(self):
        expected = bootstrap.read_runner(bootstrap.RUNNER)
        self.assertGreaterEqual(len(expected), 6)
        for relative, content in expected.items():
            destination = ".github/skills/quickstart-runner/" + relative
            self.assertEqual(self.payload[destination], content)
            self.assertEqual(self.manifest["files"][destination]["origin"],
                             "repository/skills/quickstart-runner/" + relative)
            self.assertEqual(self.manifest["files"][destination]["kind"],
                             "unchanged_repository_copy")
        self.assertEqual(self.manifest["selection"]["skills"], ["quickstart-runner", "report-gen"])
        self.assertEqual(self.manifest["activation"]["quickstart_runner_loaded"], "not_verified")
        self.assertEqual(self.manifest["activation"]["model_matches_guide"], "not_verified")

    def test_missing_or_incomplete_authoritative_runner_blocks_preparation(self):
        with mock.patch.object(bootstrap, "RUNNER", self.work / "missing"):
            with self.assertRaisesRegex(bootstrap.BootstrapError, "package is missing"):
                bootstrap.make_payload(HERE / "files" / "ship.tar", HERE / bootstrap.GUIDE)
        (self.work / "SKILL.md").write_bytes(b"partial")
        with self.assertRaisesRegex(bootstrap.BootstrapError, "package is incomplete"):
            bootstrap.read_runner(self.work)

    def test_research_requires_explicit_selection_and_is_not_indexed(self):
        payload, manifest = bootstrap.make_payload(
            HERE / "files" / "ship.tar", HERE / bootstrap.GUIDE, include_research=True)
        papers = [path for path in payload if path.startswith("knowledge/bs_data/") and path.endswith(".pdf")]
        self.assertEqual(len(papers), 40)
        self.assertTrue(manifest["selection"]["research_included"])
        self.assertFalse(manifest["activation"]["end_to_end_ready"])

    def test_payload_is_deterministic(self):
        second, manifest = bootstrap.make_payload(HERE / "files" / "ship.tar", HERE / bootstrap.GUIDE)
        self.assertEqual(self.payload, second)
        self.assertEqual(self.manifest, manifest)

    def test_full_authoritative_guide_and_exact_section6_prompt(self):
        guide = (HERE / bootstrap.GUIDE).read_bytes()
        self.assertEqual(self.payload[bootstrap.GUIDE], guide)
        section = guide[guide.index(b"## 6."):]
        prompt = re.search(rb"```text\r?\n(.*?)^```", section, re.M | re.S)[1]
        self.assertEqual(self.payload[bootstrap.PROMPT], prompt)
        self.assertEqual(prompt.replace(b"\r\n", b"\n"), EXPECTED_PROMPT)
        self.assertEqual(bootstrap.digest(EXPECTED_PROMPT), bootstrap.PROMPT_SHA256)

    def test_retained_source_is_complete_and_adjacent_without_checkout_references(self):
        prefix = "quickstarts/siphy/"
        self.assertEqual(self.payload[prefix + "files/ship.tar"],
                         (HERE / "files" / "ship.tar").read_bytes())
        self.assertEqual(self.payload[prefix + bootstrap.GUIDE], self.payload[bootstrap.GUIDE])
        for relative in ("README.md", "CUSTOMER-READINESS.md", "skill 1.md", "bootstrap.py",
                         "probe_microchip.py", "tests/test_bootstrap.py", "tests/test_probe_microchip.py"):
            self.assertEqual(self.payload[prefix + relative], (HERE / relative).read_bytes())
        self.assertNotIn(str(HERE).encode(), self.payload["README.md"])
        self.assertIn(b"preflight --destination .", self.payload["README.md"])

    def test_prepared_cli_plan_uses_only_prepared_project_sources(self):
        destination = self.work / "standalone"
        bootstrap.prepare(destination, self.payload)
        script = destination / "quickstarts" / "siphy" / "bootstrap.py"
        future = self.work / "next-project"
        result = subprocess.run(
            [sys.executable, "-B", str(script), "plan", "--destination", str(future)],
            cwd=HERE.parents[1], capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        evidence = json.loads(result.stdout)
        self.assertEqual(evidence["archive"]["sha256"], bootstrap.ARCHIVE_SHA256)
        self.assertEqual(evidence["selection"]["skills"], ["quickstart-runner", "report-gen"])
        self.assertFalse(evidence["activation"]["end_to_end_ready"])
        self.assertFalse(future.exists())

    def test_prompt_accepts_checkout_newlines_but_not_older_runner(self):
        guide = self.payload[bootstrap.GUIDE]
        self.assertEqual(bootstrap.exact_prompt(guide.replace(b"\r\n", b"\n")), EXPECTED_PROMPT)
        for invalid in (b"# old runner", guide.replace(b"veirlog", b"Verilog")):
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.exact_prompt(invalid)

    def test_immutable_originals_and_effective_overlays_have_provenance(self):
        with tarfile.open(HERE / "files" / "ship.tar") as archive:
            for name in bootstrap.AGENTS:
                member = f"ship/dot-github/agents/{name}.agent.md"
                original = archive.extractfile(member).read()
                self.assertEqual(self.payload[".siphy/originals/" + member], original)
                effective = f".github/agents/{name}.agent.md"
                self.assertNotEqual(self.payload[effective], original)
                self.assertEqual(self.manifest["files"][effective]["origin"], member)
                self.assertEqual(self.manifest["files"][effective]["kind"], "effective_overlay")
        hardware = self.payload[".github/agents/hardware-spec-dev.agent.md"].decode()
        self.assertIn(
            'tools:\n    - "sdk/microchip-mcp-server/search_microchip_product_documents"\n',
            hardware)
        self.assertNotIn("sdk/microchip-mcp-server/*", hardware)
        self.assertIn("that does not prove a live tool is exposed", hardware)
        self.assertIn("unvalidated prepared-project\ncandidate, not a proven activation fix", hardware)
        self.assertNotIn("c-users-ai4semi", hardware)
        self.assertNotIn("discovery-app.discovery-app/toolCatalog", hardware)
        for name in bootstrap.AGENTS[1:]:
            content = self.payload[f".github/agents/{name}.agent.md"].decode()
            self.assertNotIn("MUST verify each image exists and build", content)
            self.assertNotIn("# Container image bootstrap (auto-generated", content)
            self.assertNotIn("podman build -t", content)
            self.assertNotIn("docker build -t", content)
            self.assertIn("Never install, pull, build, import, index, or sign in automatically", content)
            self.assertIn("separate owner-authorized operation", content)

    def test_plugin_example_is_inert_and_uses_verified_shape_only(self):
        plugin = json.loads(self.payload["setup/microchip.plugin.example.json"])
        self.assertEqual(plugin, {"servers": {"microchip-mcp-server": {
            "type": "http", "url": "https://api.microchip.com/mcp/resources"}}})
        self.assertNotIn(".mcp.json", self.payload)
        self.assertNotIn(".github/copilot/mcp.json", self.payload)
        self.assertEqual(self.manifest["activation"]["catalog_connection_loaded"], "not_verified")
        self.assertEqual(self.manifest["activation"]["host_binding"],
                         "requires_supported_app_import_grant_and_exposure")
        self.assertEqual(self.manifest["activation"]["hardware_spec_dev_tool_reference"],
                         "sdk/microchip-mcp-server/search_microchip_product_documents")
        self.assertEqual(self.manifest["activation"]["hardware_spec_dev_tool_grant"],
                         "narrow_sdk_selector_requested_activation_unverified")
        self.assertEqual(self.manifest["activation"]["binding_candidate_validation"],
                         "parser_compatible_live_activation_unverified")
        self.assertNotIn("native_validation_history", self.manifest["activation"])
        self.assertFalse(self.manifest["activation"]["end_to_end_ready"])
        instructions = self.payload["setup/NEXT-STEPS.txt"].decode()
        self.assertIn("Activation MUST be checked", instructions)
        self.assertIn("A successful parent lookup is not sufficient.", instructions)
        self.assertNotIn("memory.max", instructions)
        self.assertNotIn("exit 127", instructions)

    def test_prepare_and_verify_preserves_all_bytes(self):
        destination = self.work / "project with spaces"
        bootstrap.prepare(destination, self.payload)
        self.assertTrue(bootstrap.verify_prepared(destination)["verified"])
        for name, content in self.payload.items():
            self.assertEqual((destination / name).read_bytes(), content)
        self.assertFalse(self.manifest["activation"]["end_to_end_ready"])
        self.assertEqual(self.manifest["activation"]["agents_loaded"], "not_verified")

    def test_never_overwrites_even_empty_destination(self):
        for populated in (False, True):
            destination = self.work / str(populated)
            destination.mkdir()
            if populated:
                (destination / "keep").write_bytes(b"keep")
            with self.assertRaisesRegex(bootstrap.BootstrapError, "already exists"):
                bootstrap.prepare(destination, self.payload)
            self.assertEqual(sorted(path.name for path in destination.iterdir()),
                             ["keep"] if populated else [])

    def test_rejects_destination_file_and_missing_parent(self):
        existing = self.work / "file"
        existing.write_bytes(b"keep")
        with self.assertRaisesRegex(bootstrap.BootstrapError, "already exists"):
            bootstrap.prepare(existing, self.payload)
        with self.assertRaisesRegex(bootstrap.BootstrapError, "parent must already exist"):
            bootstrap.prepare(self.work / "missing" / "child", self.payload)
        self.assertEqual(existing.read_bytes(), b"keep")

    def test_invalid_output_mapping_rejected_before_destination_is_created(self):
        for payload in ({"../outside": b"bad"}, {"File": b"1", "file": b"2"},
                        {"file": b"1", "file/child": b"2"}):
            with self.subTest(payload=payload):
                destination = self.work / "new"
                with self.assertRaises(bootstrap.BootstrapError):
                    bootstrap.prepare(destination, payload)
                self.assertFalse(destination.exists())

    def test_nonportable_destination_name_rejected(self):
        for name in ("NUL", "project.", "project "):
            with self.subTest(name=name):
                with self.assertRaises(bootstrap.BootstrapError):
                    bootstrap.prepare(self.work / name, {"file": b"content"})

    def test_linked_ancestor_is_rejected_without_symlink_privileges(self):
        destination = self.work / "linked-parent" / "new"
        original_linked = bootstrap.linked
        with mock.patch.object(
            bootstrap, "linked",
            side_effect=lambda path: path.name == "linked-parent" or original_linked(path),
        ):
            with self.assertRaisesRegex(bootstrap.BootstrapError, "link or junction"):
                bootstrap.prepare(destination, self.payload)
        self.assertFalse(destination.exists())

    def test_symlink_destination_or_ancestor_rejected(self):
        target = self.work / "target"
        target.mkdir()
        link = self.work / "link"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Host does not allow symlink creation: {exc}")
        for destination in (link, link / "child"):
            with self.assertRaisesRegex(bootstrap.BootstrapError, "link or junction"):
                bootstrap.prepare(destination, self.payload)
        self.assertEqual(list(target.iterdir()), [])

    def test_windows_junction_attributes_are_rejected_on_python310(self):
        with mock.patch.object(Path, "is_symlink", return_value=False), \
             mock.patch.object(Path, "lstat", return_value=mock.Mock(st_file_attributes=0x400)):
            self.assertTrue(bootstrap.linked(self.work))

    def test_write_failure_removes_only_new_project(self):
        destination = self.work / "new"
        sibling = self.work / "sibling"
        sibling.write_bytes(b"keep")
        original_open = Path.open

        def fail_second(path, *args, **kwargs):
            if path.name == "second" and args == ("xb",):
                raise OSError("simulated disk failure")
            return original_open(path, *args, **kwargs)

        with mock.patch.object(Path, "open", fail_second):
            with self.assertRaisesRegex(OSError, "simulated"):
                bootstrap.prepare(destination, {"first": b"first", "second": b"second"})
        self.assertFalse(destination.exists())
        self.assertEqual(sibling.read_bytes(), b"keep")

    def test_modified_or_missing_files_are_reported(self):
        destination = self.work / "project"
        bootstrap.prepare(destination, self.payload)
        (destination / bootstrap.PROMPT).write_bytes(b"wrong")
        (destination / ".github" / "agents" / "hardware-spec-dev.agent.md").unlink()
        evidence = bootstrap.verify_prepared(destination)
        self.assertFalse(evidence["verified"])
        self.assertEqual(len(evidence["errors"]), 2)

    def test_missing_manifest_is_not_prepared(self):
        self.assertFalse(bootstrap.verify_prepared(self.work)["verified"])

    def test_manifest_cannot_omit_recipe_files(self):
        destination = self.work / "project"
        bootstrap.prepare(destination, self.payload)
        manifest_path = destination / bootstrap.MANIFEST
        manifest = json.loads(manifest_path.read_bytes())
        del manifest["files"][bootstrap.PROMPT]
        manifest_path.write_bytes(bootstrap.json_bytes(manifest))
        with self.assertRaisesRegex(bootstrap.BootstrapError, "omits required"):
            bootstrap.verify_prepared(destination)

    def test_manifest_paths_cannot_escape(self):
        destination = self.work / "project"
        bootstrap.prepare(destination, self.payload)
        manifest_path = destination / bootstrap.MANIFEST
        manifest = json.loads(manifest_path.read_bytes())
        manifest["files"]["../../outside"] = {"sha256": "bad"}
        manifest_path.write_bytes(bootstrap.json_bytes(manifest))
        with self.assertRaisesRegex(bootstrap.BootstrapError, "path"):
            bootstrap.verify_prepared(destination)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.which = mock.patch.object(bootstrap.shutil, "which", side_effect=lambda name: name)
        self.which.start()
        self.addCleanup(self.which.stop)

    @staticmethod
    def good_command(args, timeout):
        if args[1] == "info":
            value = ({"host": {
                "os": "linux", "arch": "amd64", "cgroupVersion": "v2",
                "cgroupManager": "cgroupfs", "cgroupControllers": ["cpu", "memory", "pids"],
                "security": {"rootless": True},
            }} if args[0] == "podman"
                     else {"OSType": "linux", "Architecture": "x86_64"})
        else:
            value = {"Id": "sha256:example", "Os": "linux", "Architecture": "amd64"}
        return {"command": args, "returncode": 0, "stdout": json.dumps(value), "stderr": ""}

    def test_checks_only_readonly_commands_and_all_exact_tags(self):
        with mock.patch.object(bootstrap, "command", side_effect=self.good_command) as run:
            evidence = bootstrap.runtime_evidence()
        self.assertTrue(evidence["ready"])
        self.assertEqual(evidence["selected"], "docker")
        self.assertEqual(evidence["readiness_scope"],
                         "engine_info_existing_images_and_reported_podman_cgroup_prerequisites_only")
        self.assertEqual(evidence["native_execution"], "unverified_no_containers_executed")
        self.assertEqual(evidence["resource_limit_enforcement"], "unverified_no_containers_executed")
        self.assertEqual(run.call_count, 8)
        for call in run.call_args_list:
            args = call.args[0]
            self.assertTrue(args[1] == "info" or args[1:3] == ["image", "inspect"])
        for candidate in evidence["candidates"]:
            self.assertEqual(set(candidate["images"]), set(bootstrap.IMAGES))

    def test_rootless_podman_v2_missing_or_empty_controllers_blocks_even_with_all_images(self):
        for controllers in (None, [], ["cpu", "pids"], "cpu memory pids"):
            def command(args, timeout):
                result = self.good_command(args, timeout)
                if args[1] == "info":
                    info = json.loads(result["stdout"])
                    if controllers is None:
                        del info["host"]["cgroupControllers"]
                    else:
                        info["host"]["cgroupControllers"] = controllers
                    result["stdout"] = json.dumps(info)
                return result
            with self.subTest(controllers=controllers), \
                 mock.patch.object(bootstrap, "command", side_effect=command):
                evidence = bootstrap.runtime_evidence("podman")
            self.assertFalse(evidence["ready"])
            self.assertIsNone(evidence["selected"])
            candidate = evidence["candidates"][0]
            self.assertTrue(all(image["ready"] for image in candidate["images"].values()))
            check = candidate["cgroup_check"]
            self.assertEqual(check["status"], "blocked_missing_rootless_v2_controllers")
            self.assertIn("memory", check["missing_controllers"])
            self.assertIn("do not weaken limits", candidate["error"])

    def test_rootless_podman_v2_valid_controllers_do_not_prove_native_enforcement(self):
        with mock.patch.object(bootstrap, "command", side_effect=self.good_command):
            evidence = bootstrap.runtime_evidence("podman")
        self.assertTrue(evidence["ready"])
        check = evidence["candidates"][0]["cgroup_check"]
        self.assertEqual(check["missing_controllers"], [])
        self.assertEqual(check["status"], "required_controllers_reported_enforcement_unverified")
        self.assertEqual(check["resource_limit_enforcement"], "unverified_no_containers_executed")

    def test_unknown_podman_cgroup_metadata_blocks_instead_of_assuming_rootful(self):
        for host in (
            {"cgroupVersion": "v2", "cgroupControllers": ["cpu", "memory", "pids"]},
            {"security": {"rootless": True}, "cgroupControllers": ["cpu", "memory", "pids"]},
        ):
            with self.subTest(host=host):
                check = bootstrap.podman_cgroup_evidence(host)
                self.assertFalse(check["ready"])
                self.assertEqual(check["status"], "blocked_unknown_cgroup_metadata")

    def test_uppercase_podman_host_fields_and_rootful_inventory(self):
        check = bootstrap.podman_cgroup_evidence({
            "CgroupVersion": "v2", "CgroupManager": "systemd",
            "CgroupControllers": ["cpu", "memory", "pids"], "Security": {"Rootless": True},
        })
        self.assertTrue(check["ready"])
        self.assertEqual(check["missing_controllers"], [])
        rootful = bootstrap.podman_cgroup_evidence({
            "cgroupVersion": "v2", "security": {"rootless": False},
        })
        self.assertTrue(rootful["ready"])
        self.assertEqual(rootful["resource_limit_enforcement"], "unverified_no_containers_executed")

    def test_unresponsive_docker_falls_back_to_working_podman(self):
        def command(args, timeout):
            if args[0] == "docker":
                return {"command": args, "returncode": 1, "stdout": "", "stderr": "daemon unavailable"}
            return self.good_command(args, timeout)
        with mock.patch.object(bootstrap, "command", side_effect=command):
            evidence = bootstrap.runtime_evidence()
        self.assertEqual(evidence["selected"], "podman")
        self.assertFalse(evidence["candidates"][0]["ready"])

    def test_missing_image_is_not_ready_and_never_built(self):
        def command(args, timeout):
            if args[-1] == "rtl-lint:latest":
                return {"command": args, "returncode": 1, "stdout": "", "stderr": "No such image"}
            return self.good_command(args, timeout)
        with mock.patch.object(bootstrap, "command", side_effect=command):
            evidence = bootstrap.runtime_evidence("docker")
        self.assertFalse(evidence["ready"])
        image = evidence["candidates"][0]["images"]["rtl-lint:latest"]
        self.assertFalse(image["ready"])
        self.assertIn("No such image", image["check"]["stderr"])

    def test_complete_engine_preferred_over_first_engine_with_missing_images(self):
        def command(args, timeout):
            if args[0] == "docker" and args[-1] == "rtl-design:latest":
                return {"command": args, "returncode": 1, "stdout": "", "stderr": "missing"}
            return self.good_command(args, timeout)
        with mock.patch.object(bootstrap, "command", side_effect=command):
            self.assertEqual(bootstrap.runtime_evidence()["selected"], "podman")

    def test_windows_engine_and_wrong_architecture_are_not_assumed_supported(self):
        for field, value in (("OSType", "windows"), ("Architecture", "arm64")):
            def command(args, timeout):
                result = self.good_command(args, timeout)
                if args[1] == "info":
                    info = json.loads(result["stdout"])
                    info[field] = value
                    result["stdout"] = json.dumps(info)
                return result
            with self.subTest(field=field), mock.patch.object(bootstrap, "command", side_effect=command):
                self.assertFalse(bootstrap.runtime_evidence("docker")["ready"])

    def test_malformed_info_and_image_json_are_not_ready(self):
        for stage in ("info", "image"):
            def command(args, timeout):
                result = self.good_command(args, timeout)
                if args[1] == stage:
                    result["stdout"] = "not json"
                return result
            with self.subTest(stage=stage), mock.patch.object(bootstrap, "command", side_effect=command):
                evidence = bootstrap.runtime_evidence("docker")
                self.assertFalse(evidence["ready"])

    def test_no_runtime_executable_does_not_attempt_commands(self):
        with mock.patch.object(bootstrap.shutil, "which", return_value=None), \
             mock.patch.object(bootstrap, "command") as run:
            evidence = bootstrap.runtime_evidence()
        self.assertFalse(evidence["ready"])
        run.assert_not_called()

    def test_command_timeout_and_os_failure_are_evidence_not_crashes(self):
        for failure in (subprocess.TimeoutExpired(["docker"], 1), OSError("not executable")):
            with mock.patch.object(bootstrap.subprocess, "run", side_effect=failure):
                evidence = bootstrap.command(["docker", "info"], 1)
            self.assertIsNone(evidence["returncode"])
            self.assertTrue(evidence["stderr"])

    def test_subprocess_uses_no_shell_and_bounded_timeout(self):
        completed = subprocess.CompletedProcess(["docker"], 0, "{}", "")
        with mock.patch.object(bootstrap.subprocess, "run", return_value=completed) as run:
            bootstrap.command(["docker", "info"], 2)
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(run.call_args.kwargs["timeout"], 2)
        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)


class CliTests(ProjectTest):
    def invoke(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = bootstrap.main(args)
        return code, json.loads(output.getvalue())

    def test_plan_is_readonly_and_does_not_inspect_or_activate_runtime(self):
        destination = self.work / "planned"
        with mock.patch.object(bootstrap, "runtime_evidence") as runtime:
            code, evidence = self.invoke(["plan", "--destination", str(destination)])
        self.assertEqual(code, 0)
        self.assertFalse(destination.exists())
        runtime.assert_not_called()
        self.assertEqual(evidence["status"], "planned-no-files-written")
        self.assertFalse(evidence["activation"]["end_to_end_ready"])

    def test_prepare_success_and_repeat_failure(self):
        destination = self.work / "prepared"
        with mock.patch.object(bootstrap, "runtime_evidence") as runtime:
            code, evidence = self.invoke(["prepare", "--destination", str(destination)])
        self.assertEqual(code, 0)
        self.assertEqual(evidence["status"], "prepared-not-activated")
        runtime.assert_not_called()
        original = (destination / bootstrap.MANIFEST).read_bytes()
        code, evidence = self.invoke(["prepare", "--destination", str(destination)])
        self.assertEqual(code, 2)
        self.assertIn("already exists", evidence["error"])
        self.assertEqual((destination / bootstrap.MANIFEST).read_bytes(), original)

    def test_preflight_success_never_means_agents_or_tools_loaded(self):
        destination = self.work / "prepared"
        self.invoke(["prepare", "--destination", str(destination)])
        before = {str(path.relative_to(destination)): bootstrap.digest(path.read_bytes())
                  for path in destination.rglob("*") if path.is_file()}
        with mock.patch.object(bootstrap, "runtime_evidence", return_value={"ready": True, "selected": "docker"}):
            code, evidence = self.invoke(["preflight", "--destination", str(destination)])
        self.assertEqual(code, 0)
        self.assertTrue(evidence["local_prerequisites_ready"])
        self.assertEqual(evidence["activation"]["status"],
                         "blocked_pending_specialist_binding_and_native_execution_validation")
        self.assertEqual(evidence["activation"]["native_execution"],
                         "unverified_preflight_does_not_run_containers")
        self.assertEqual(evidence["activation"]["resource_limit_enforcement"],
                         "unverified_preflight_does_not_run_containers")
        self.assertNotIn("native_validation_history", evidence["activation"])
        self.assertEqual(evidence["activation"]["agents_loaded"], "not_verified")
        self.assertEqual(evidence["activation"]["hardware_spec_dev_catalog_call"], "not_verified")
        self.assertFalse(evidence["activation"]["end_to_end_ready"])
        self.assertFalse(evidence["activation"]["engineering_executed"])
        after = {str(path.relative_to(destination)): bootstrap.digest(path.read_bytes())
                 for path in destination.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_preflight_failure_and_missing_project_exit_two(self):
        with mock.patch.object(bootstrap, "runtime_evidence", return_value={"ready": False, "selected": None}):
            code, evidence = self.invoke(["preflight", "--destination", str(self.work)])
        self.assertEqual(code, 2)
        self.assertEqual(evidence["status"], "blocked")
        self.assertFalse(evidence["files"]["verified"])

    def test_preflight_blocks_missing_cgroups_despite_verified_files_and_existing_images(self):
        destination = self.work / "prepared"
        self.invoke(["prepare", "--destination", str(destination)])

        def command(args, timeout):
            result = RuntimeTests.good_command(args, timeout)
            if args[1] == "info":
                info = json.loads(result["stdout"])
                info["host"]["cgroupControllers"] = []
                result["stdout"] = json.dumps(info)
            return result

        with mock.patch.object(bootstrap.shutil, "which", return_value="podman"), \
             mock.patch.object(bootstrap, "command", side_effect=command):
            code, evidence = self.invoke([
                "preflight", "--destination", str(destination), "--runtime", "podman",
            ])
        self.assertEqual(code, 2)
        self.assertEqual(evidence["status"], "blocked")
        self.assertTrue(evidence["files"]["verified"])
        self.assertFalse(evidence["local_prerequisites_ready"])
        candidate = evidence["runtime"]["candidates"][0]
        self.assertTrue(all(image["ready"] for image in candidate["images"].values()))
        self.assertEqual(candidate["cgroup_check"]["missing_controllers"], ["cpu", "memory", "pids"])

    def test_insufficient_disk_prevents_writes(self):
        destination = self.work / "no-space"
        with mock.patch.object(bootstrap, "disk_evidence", return_value={"sufficient": False}):
            code, evidence = self.invoke(["prepare", "--destination", str(destination)])
        self.assertEqual(code, 2)
        self.assertIn("disk space", evidence["error"])
        self.assertFalse(destination.exists())

    def test_invalid_timeout_and_preflight_research_option(self):
        for extras in (["--timeout", "0"], ["--timeout", "61"], ["--timeout", "nan"],
                       ["--include-research"]):
            with self.subTest(extras=extras):
                code, evidence = self.invoke(["preflight", "--destination", str(self.work), *extras])
                self.assertEqual(code, 2)
                self.assertEqual(evidence["status"], "error")


if __name__ == "__main__":
    unittest.main()
