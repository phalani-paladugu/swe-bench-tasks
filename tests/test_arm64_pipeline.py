import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from dockerfile_gen import arm64
from dockerfile_gen import arm64_pipeline as pipeline


def resolved_report():
    records = {}
    for name, version, build, subdir in (
        ("python", "3.9.21", "arm_build", "linux-aarch64"),
        ("pip", "25.0", "py_build", "noarch"),
        # Conda's metadata survives a pip replacement. It must not become a pin.
        ("setuptools", "80.9.0", "py_build", "noarch"),
    ):
        records[name] = {
            "name": name,
            "version": version,
            "build": build,
            "subdir": subdir,
            "url": f"https://{arm64.DEFAULT_MIRROR}/artifactory/api/conda/conda-forge/{subdir}/{name}.conda",
        }
    return {
        "architecture": "aarch64",
        "python": "3.9.21",
        "base_commit": "base123",
        "git_remotes": [],
        "local_distributions": ["astropy"],
        "python_distributions": {
            "pip": "25.0",
            "setuptools": "68.0.0",
            "astropy": "4.2.dev0",
        },
        "conda_records": records,
        "environment": {
            "dependencies": [
                "python=3.9.21=arm_build",
                "pip=25.0=py_build",
                {"pip": ["astropy==4.2.dev0", "setuptools==68.0.0"]},
            ]
        },
    }


class Arm64PipelineTests(unittest.TestCase):
    def test_pins_require_versions_and_conda_builds(self):
        pinned = "dependencies: [python=3.9.21=arm_build, {pip: [pytest==7.4.0]}]"
        self.assertTrue(pipeline.is_fully_pinned(pinned))
        for source in (
            "dependencies: [python=3.9.21]",
            "dependencies: [openssl]",
            "dependencies: [python=3.9.*=arm_build]",
            "dependencies: [python=3.9.21|3.10.0=arm_build]",
            "dependencies: []",
            "dependencies: [python=3.9.21=arm_build, {pip: ['pytest>=7']}]",
            "dependencies: [python=3.9.21=arm_build, {pip: ['foo @ https://example.org/foo.whl']}]",
        ):
            with self.subTest(source=source):
                self.assertFalse(pipeline.is_fully_pinned(source))

    def test_export_omits_local_project_and_stale_conda_metadata(self):
        frozen = pipeline.frozen_environment(
            resolved_report(), arm64.DEFAULT_MIRROR, "base123"
        )
        self.assertTrue(pipeline.is_fully_pinned(frozen))
        self.assertIn("setuptools==68.0.0", frozen)
        self.assertNotIn("80.9.0", frozen)
        self.assertNotIn("astropy", frozen)
        self.assertIn("python=3.9.21=arm_build", frozen)
        self.assertEqual(yaml.safe_load(frozen)["channels"], ["conda-forge"])

    def test_export_rejects_wrong_architecture_checkout_mirror_and_sources(self):
        changes = (
            lambda r: r.update(architecture="x86_64"),
            lambda r: r.update(base_commit="wrong"),
            lambda r: r.update(git_remotes=["origin"]),
            lambda r: r.update(local_distributions=[]),
            lambda r: r["conda_records"]["python"].update(subdir="linux-64"),
            lambda r: r["conda_records"]["python"].update(
                url="https://other.org/python.conda"
            ),
            lambda r: r["environment"]["dependencies"][-1]["pip"].append(
                "foo @ https://example.org/foo.whl"
            ),
        )
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                report = resolved_report()
                change(report)
                with self.assertRaises(ValueError):
                    pipeline.frozen_environment(report, arm64.DEFAULT_MIRROR, "base123")

    def test_export_keeps_native_package_hidden_by_same_named_python_package(self):
        report = resolved_report()
        report["conda_records"]["tzdata"] = {
            "name": "tzdata",
            "version": "2026e",
            "build": "data_build",
            "subdir": "noarch",
            "url": f"https://{arm64.DEFAULT_MIRROR}/artifactory/conda-forge/noarch/tzdata.conda",
        }
        report["environment"]["dependencies"][-1]["pip"].append("tzdata==2024.2")
        report["python_distributions"]["tzdata"] = "2024.2"
        frozen = pipeline.frozen_environment(report, arm64.DEFAULT_MIRROR, "base123")
        self.assertIn("tzdata=2026e=data_build", frozen)
        self.assertIn("tzdata==2024.2", frozen)
        self.assertNotIn("setuptools=80.9.0", frozen)
        for change in (
            {"subdir": "linux-64"},
            {"url": "https://other.org/tzdata.conda"},
        ):
            changed = copy.deepcopy(report)
            changed["conda_records"]["tzdata"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                pipeline.frozen_environment(changed, arm64.DEFAULT_MIRROR, "base123")

    def test_pipeline_rebuilds_from_export_and_removes_only_its_temporary_tags(self):
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory) / "task-1"
            task.mkdir()
            (task / "task.yaml").write_text("base_commit: base123\n")
            with (
                patch.object(
                    pipeline, "generate", return_value="Dockerfile"
                ) as generate,
                patch.object(pipeline, "build_image") as build,
                patch.object(pipeline, "inspect_image", return_value=resolved_report()),
                patch.object(pipeline.subprocess, "run") as cleanup,
                patch("builtins.print"),
            ):
                frozen = pipeline.resolve_environment(
                    task, arm64.DEFAULT_MIRROR, Path(directory) / "logs"
                )
            self.assertEqual(build.call_count, 2)
            self.assertEqual(generate.call_args_list[1].args[2], frozen)
            self.assertFalse((task / "environment.arm64.yml").exists())
            self.assertEqual(cleanup.call_count, 2)
            for build_call, cleanup_call in zip(
                build.call_args_list, cleanup.call_args_list
            ):
                self.assertEqual(
                    cleanup_call.args[0], ["docker", "image", "rm", build_call.args[2]]
                )

    def test_rebuild_rejects_changed_packages_even_if_export_is_unchanged(self):
        report = resolved_report()
        changed = copy.deepcopy(report)
        changed["python_distributions"]["setuptools"] = "70.0.0"
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory)
            (task / "task.yaml").write_text("base_commit: base123\n")
            with (
                patch.object(pipeline, "generate", return_value="Dockerfile"),
                patch.object(pipeline, "build_image"),
                patch.object(pipeline, "inspect_image", side_effect=[report, changed]),
                patch.object(pipeline.subprocess, "run"),
                patch("builtins.print"),
                self.assertRaisesRegex(
                    ValueError, "Python distribution versions changed"
                ),
            ):
                pipeline.resolve_environment(task, arm64.DEFAULT_MIRROR, task / "logs")

    def test_cli_resolves_missing_pins_reuses_saved_pins_and_refreshes(self):
        frozen = pipeline.frozen_environment(
            resolved_report(), arm64.DEFAULT_MIRROR, "base123"
        )
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory) / "task-1"
            task.mkdir()
            (task / "Dockerfile").write_text(
                "FROM --platform=linux/amd64 ubuntu:22.04\n"
            )
            argv = ["arm64", "--instance_ids", task.name]
            with (
                patch.object(arm64, "task_dirs", return_value=[task]),
                patch.object(
                    arm64,
                    "generate",
                    return_value="FROM --platform=linux/arm64 ubuntu:22.04\n",
                ),
                patch.object(
                    pipeline, "resolve_environment", return_value=frozen
                ) as resolve,
                patch("builtins.print"),
            ):
                with patch("sys.argv", argv):
                    arm64.main()
                    arm64.main()
                self.assertEqual(resolve.call_count, 1)
                self.assertEqual((task / "environment.arm64.yml").read_text(), frozen)
                with patch("sys.argv", argv + ["--refresh-lock"]):
                    arm64.main()
                self.assertEqual(resolve.call_count, 2)

    def test_failed_resolution_does_not_replace_task_files(self):
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory)
            original = "FROM --platform=linux/amd64 ubuntu:22.04\n"
            (task / "Dockerfile").write_text(original)
            with (
                patch.object(arm64, "task_dirs", return_value=[task]),
                patch.object(
                    pipeline,
                    "resolve_environment",
                    side_effect=RuntimeError("build failed"),
                ),
                patch("sys.argv", ["arm64", "--instance_ids", task.name]),
                patch("builtins.print"),
                self.assertRaises(SystemExit) as error,
            ):
                arm64.main()
            self.assertEqual(error.exception.code, 1)
            self.assertEqual((task / "Dockerfile").read_text(), original)
            self.assertEqual([p.name for p in task.iterdir()], ["Dockerfile"])

    def test_draft_does_not_build_and_output_lock_stays_outside_task(self):
        frozen = pipeline.frozen_environment(
            resolved_report(), arm64.DEFAULT_MIRROR, "base123"
        )
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory) / "task-1"
            task.mkdir()
            original = "FROM --platform=linux/amd64 ubuntu:22.04\n"
            (task / "Dockerfile").write_text(original)
            destination = Path(directory) / "preview"
            argv = [
                "arm64",
                "--instance_ids",
                task.name,
                "--output-dir",
                str(destination),
            ]
            with (
                patch.object(arm64, "task_dirs", return_value=[task]),
                patch.object(
                    arm64,
                    "generate",
                    return_value="FROM --platform=linux/arm64 ubuntu:22.04\n",
                ),
                patch.object(
                    pipeline, "resolve_environment", return_value=frozen
                ) as resolve,
                patch("builtins.print"),
            ):
                with patch("sys.argv", argv + ["--draft"]):
                    arm64.main()
                resolve.assert_not_called()
                with patch("sys.argv", argv):
                    arm64.main()
                    arm64.main()
                resolve.assert_called_once()
            self.assertEqual((task / "Dockerfile").read_text(), original)
            self.assertFalse((task / "environment.arm64.yml").exists())
            self.assertEqual(
                (destination / task.name / "environment.arm64.yml").read_text(), frozen
            )


if __name__ == "__main__":
    unittest.main()
