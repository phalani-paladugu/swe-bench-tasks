import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from dockerfile_gen import arm64


class Arm64GeneratorTests(unittest.TestCase):
    def test_in_place_generation_saves_x86_once(self):
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory)
            (task / "Dockerfile").write_text(
                "FROM --platform=linux/amd64 ubuntu:22.04\n"
            )
            arm64.write_dockerfile(task, "FROM --platform=linux/arm64 ubuntu:22.04\n")
            arm64.write_dockerfile(
                task, "FROM --platform=linux/arm64 ubuntu:22.04\n# regenerated\n"
            )
            self.assertEqual(
                (task / "Dockerfile.amd").read_text(),
                "FROM --platform=linux/amd64 ubuntu:22.04\n",
            )
            self.assertIn("# regenerated", (task / "Dockerfile").read_text())

    def test_preview_copies_x86_without_changing_task(self):
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory) / "task-1"
            task.mkdir()
            original = "FROM --platform=linux/amd64 ubuntu:22.04\n"
            (task / "Dockerfile").write_text(original)
            result = arm64.write_dockerfile(
                task,
                "FROM --platform=linux/arm64 ubuntu:22.04\n",
                Path(directory) / "preview",
            )
            self.assertEqual((task / "Dockerfile").read_text(), original)
            self.assertEqual(result.with_name("Dockerfile.amd").read_text(), original)
            self.assertIn("linux/arm64", result.read_text())

    def test_empty_pip_section_and_native_ranges(self):
        source = "dependencies:\n- openssl>=3.0,<4\n- libffi >=3.4,<4\n- pip:\n"
        result = yaml.safe_load(arm64.arm_environment(source))
        self.assertEqual(result["dependencies"], ["openssl>=3.0,<4", "libffi >=3.4,<4"])

    def test_x86_snapshot_keeps_application_versions_and_pip_pins(self):
        source = {
            "prefix": "/old/path",
            "channels": ["defaults"],
            "dependencies": [
                "python=3.9.20=old_build",
                "numpy=1.25.2=old_build",
                "_libgcc_mutex=0.1=main",
                "numpy-base=1.25.2=old_build",
                "ld_impl_linux-64=2.40=old_build",
                "openssl=3.0.15=old_build",
                {"pip": ["pytest==7.4.0", "coverage==7.6.2"]},
            ],
        }
        result = yaml.safe_load(arm64.arm_environment(yaml.safe_dump(source)))
        self.assertEqual(
            result,
            {
                "name": "testbed",
                "channels": ["conda-forge"],
                "dependencies": [
                    "python=3.9.20",
                    "numpy=1.25.2",
                    "ld_impl_linux-aarch64",
                    "openssl",
                    {"pip": ["pytest==7.4.0", "coverage==7.6.2"]},
                ],
            },
        )

    def test_arm_snapshot_preserves_native_versions_and_builds(self):
        task = Path("tasks/astropy__astropy-13236")
        source = yaml.safe_load((task / "environment.arm64.yml").read_text())
        result = yaml.safe_load(
            arm64.arm_environment(yaml.safe_dump(source), pinned=True)
        )
        self.assertEqual(result["dependencies"], source["dependencies"])
        self.assertEqual(
            len([d for d in result["dependencies"] if isinstance(d, str)]), 23
        )

    def test_rejects_x86_pins_in_arm_override_and_external_conda_sources(self):
        for dependency in (
            "ld_impl_linux-64=2.40=old",
            "other::python=3.9",
            "https://example.com/python.conda",
        ):
            with self.subTest(dependency=dependency), self.assertRaises(ValueError):
                arm64.arm_environment(
                    yaml.safe_dump({"dependencies": [dependency]}), pinned=True
                )

    def test_internal_channel_qualifiers_are_normalized(self):
        result = yaml.safe_load(
            arm64.arm_environment("dependencies: [conda-forge::python=3.9.20=build]")
        )
        self.assertEqual(result["dependencies"], ["python=3.9.20"])

    def test_rejects_malformed_yaml_and_mirror_host(self):
        with self.assertRaises(ValueError):
            arm64.arm_environment("dependencies: broken")
        with self.assertRaises(ValueError):
            arm64.write_conda("mirror.example.com\nRUN false")

    def test_generation_uses_arm_override_and_preserves_repository_setup(self):
        task = Path("tasks/astropy__astropy-13236")
        result = arm64.generate(task)
        self.assertIn("python=3.9.23=h0819846_0_cpython", result)
        self.assertNotIn("python=3.9.20", result)
        self.assertIn(
            "git reset --hard 6ed769d58d89380ebaa1ef52b300691eefda8928", result
        )
        self.assertIn("git reflog expire --expire=now --all", result)
        self.assertIn("setuptools==68.0.0", result)
        self.assertIn("linux-aarch64/micromamba-2.1.0-0.tar.bz2", result)
        for block in re.finditer(r"^RUN <<'?([\w]+)'?\n(.*?)^\1$", result, re.M | re.S):
            subprocess.run(["bash", "-n"], input=block[2], text=True, check=True)

    def test_missing_environment_uses_requirements_at_setup_commit(self):
        instance = {
            "instance_id": "example__repo-1",
            "repo": "example/repo",
            "environment_setup_commit": "setup-commit",
            "base_commit": "base-commit",
        }
        specs = {
            "python": "3.9",
            "packages": "requirements.txt",
            "pip_packages": ["pytest==7.4.0"],
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "dockerfile_gen.get_requirements_by_commit",
                return_value="numpy==1.25.2",
            ) as fetch,
        ):
            result = arm64.write_dependencies(Path(directory), instance, specs)
        fetch.assert_called_once_with("example/repo", "setup-commit")
        self.assertIn("python=3.9", result)
        self.assertIn("numpy==1.25.2", result)
        self.assertIn("python -m pip install pytest==7.4.0", result)

    def test_unknown_task_does_not_create_output(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "sys.argv",
                [
                    "arm64",
                    "--instance_ids",
                    "missing__task-1",
                    "--output-dir",
                    directory,
                ],
            ),
            patch("sys.stderr"),
        ):
            with self.assertRaises(SystemExit) as error:
                arm64.main()
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
