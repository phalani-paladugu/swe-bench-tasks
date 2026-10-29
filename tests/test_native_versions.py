import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from dockerfile_gen import arm64
from dockerfile_gen import arm64_pipeline as pipeline
from dockerfile_gen.native_profiles import native_profile


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
    def test_shared_profile_requires_matching_python_and_source_versions(self):
        source = yaml.safe_load(SOURCE)
        profile = native_profile(source)
        self.assertEqual(set(profile), {"libffi"})
        self.assertEqual(profile["libffi"]["version"], "3.4.6")
        self.assertIn("Python 3.9.20 profile", profile["libffi"]["reason"])
        for changed in (
            SOURCE.replace("python=3.9.20", "python=3.9.21"),
            SOURCE.replace("python=3.9.20", "python=3.11.11"),
            SOURCE.replace("python=3.9.20=x86_build", "python=3.9"),
            SOURCE.replace("libffi=3.4.4", "libffi=3.3"),
            SOURCE.replace("libffi=3.4.4=x86_build", "libffi>=3.4"),
        ):
            with self.subTest(source=changed):
                self.assertEqual(native_profile(yaml.safe_load(changed)), {})

    def test_python_311_profile_pins_libuuid_without_changing_applications(self):
        source = yaml.safe_load(SOURCE.replace("python=3.9.20", "python=3.11.10"))
        source["dependencies"].insert(1, "libuuid=1.41.5=x86_build")
        profile = native_profile(source)
        self.assertEqual(profile["libuuid"]["version"], "2.38.1")
        self.assertIn("Python 3.11.10 profile", profile["libuuid"]["reason"])
        converted = yaml.safe_load(
            arm64.arm_environment(yaml.safe_dump(source), native_versions=profile)
        )
        self.assertIn("libuuid==2.38.1", converted["dependencies"])
        self.assertIn("libffi==3.4.6", converted["dependencies"])
        self.assertIn("python=3.11.10", converted["dependencies"])
        self.assertIn({"pip": ["pytest==7.4.0"]}, converted["dependencies"])
        source["dependencies"][0] = "python=3.9.20=x86_build"
        self.assertNotIn("libuuid", native_profile(source))

    def test_shared_profile_uses_effective_arm_python_when_relocking(self):
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory)
            (task / "environment.yml").write_text(SOURCE)
            self.assertEqual(
                arm64.load_native_versions(task)["libffi"]["version"], "3.4.6"
            )
            self.assertEqual(arm64.load_native_versions(task, ARM), {})
            result = yaml.safe_load(arm64.relock_native_environment(task, ARM))
            self.assertIn("python==3.9.23", result["dependencies"])
            self.assertIn("libffi==3.4.4", result["dependencies"])

    def test_task_overrides_take_precedence_over_shared_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            task = self.make_task(directory)
            override = {
                "libffi": {"version": "3.7.0", "reason": "Task-specific constraint."}
            }
            (task / "native-versions.arm64.yml").write_text(yaml.safe_dump(override))
            self.assertEqual(arm64.load_native_versions(task), override)
            self.assertEqual(arm64.load_native_versions(task, ARM), override)

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
