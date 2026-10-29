import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from dockerfile_gen import arm64
from dockerfile_gen import arm64_pipeline as pipeline


SOURCE = """dependencies:
- python=3.9.20=x86_build
- libffi=3.4.4=x86_build
- ld_impl_linux-64=2.40=x86_build
- pip:
  - pytest==7.4.0
"""
ARM = """dependencies:
- python=3.9.23=arm_build
- libffi=3.7.0=arm_build
- ld_impl_linux-aarch64=2.46.1=arm_build
- libgcc=16.2.0=arm_build
- liblzma-devel=5.8.3=arm_build
- xz-tools=5.8.3=arm_build
- pip:
  - pytest==7.4.0
"""


class NativeVersionTests(unittest.TestCase):
    def make_task(self, directory):
        task = Path(directory)
        (task / "environment.yml").write_text(SOURCE)
        (task / "environment.arm64.yml").write_text(ARM)
        (task / "native-versions.arm64.yml").write_text(
            yaml.safe_dump(
                {
                    "libffi": {
                        "version": "3.4.6",
                        "reason": "3.4.4 is unavailable on ARM64.",
                    },
                }
            )
        )
        return task

    def test_native_versions_are_exact_and_ranges_are_retained(self):
        result = yaml.safe_load(
            arm64.arm_environment(
                "dependencies: [libffi=3.3=x86_build, openssl>=3.0, _openmp_mutex=5.1=1_gnu]"
            )
        )
        self.assertEqual(
            result["dependencies"],
            ["libffi==3.3", "openssl>=3.0", "_openmp_mutex==5.1"],
        )

    def test_relock_preserves_application_versions_and_replaces_native_constraints(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            task = self.make_task(directory)
            result = yaml.safe_load(arm64.relock_native_environment(task, ARM))
            self.assertEqual(
                result["dependencies"],
                [
                    "libffi==3.4.6",
                    "ld_impl_linux-aarch64==2.40",
                    "python==3.9.23",
                    {"pip": ["pytest==7.4.0"]},
                ],
            )
            self.assertEqual((task / "environment.arm64.yml").read_text(), ARM)

    def test_overrides_require_exact_string_versions_reasons_and_existing_native_names(
        self,
    ):
        invalid = [
            {"python": {"version": "3.9.23", "reason": "Not a native override."}},
            {"libffi": {"version": ">=3.4", "reason": "Not an exact version."}},
            {"libffi": {"version": 3.4, "reason": "Not a string."}},
            {"libffi": {"version": "3.4.6", "reason": ""}},
            {"libgcc": {"version": "13.3.0", "reason": "Absent from x86 reference."}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            task = self.make_task(directory)
            for data in invalid:
                with self.subTest(data=data):
                    (task / "native-versions.arm64.yml").write_text(
                        yaml.safe_dump(data)
                    )
                    with self.assertRaises(ValueError):
                        arm64.load_native_versions(task)

    def test_native_comparison_rejects_version_drift_and_reports_exceptions(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self.make_task(directory)
            requested = arm64.relock_native_environment(task, ARM)
            frozen = "dependencies: [libffi=3.4.6=arm_build, ld_impl_linux-aarch64=2.40=arm_build, python=3.9.23=arm_build]"
            comparison = pipeline.check_native_versions(task, requested, frozen)
            entry = next(row for row in comparison if row["package"] == "libffi")
            self.assertEqual(entry["x86_version"], "3.4.4")
            self.assertEqual(entry["arm64_version"], "3.4.6")
            self.assertEqual(entry["requested_version"], "3.4.6")
            self.assertTrue(entry["reason"])
            with self.assertRaisesRegex(ValueError, "Native pin changed for libffi"):
                pipeline.check_native_versions(
                    task, requested, frozen.replace("libffi=3.4.6", "libffi=3.7.0")
                )

    def test_cli_relocks_native_versions_even_when_a_pinned_snapshot_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self.make_task(directory)
            original = "FROM --platform=linux/amd64 ubuntu:22.04\n"
            (task / "Dockerfile").write_text(original)
            frozen = "dependencies: [python=3.9.23=arm_build, libffi=3.4.6=arm_build]"
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
                patch(
                    "sys.argv",
                    ["arm64", "--instance_ids", task.name, "--relock-native"],
                ),
                patch("builtins.print"),
            ):
                arm64.main()
            resolve.assert_called_once()
            self.assertIn("python==3.9.23", resolve.call_args.kwargs["environment"])
            self.assertIn("libffi==3.4.6", resolve.call_args.kwargs["environment"])
            self.assertEqual((task / "Dockerfile.amd").read_text(), original)
            self.assertEqual((task / "environment.arm64.yml").read_text(), frozen)


if __name__ == "__main__":
    unittest.main()
