# ARM64 task images

Generated ARM64 Dockerfiles live at `tasks/<instance_id>/Dockerfile`. The original
x86 file is saved as `Dockerfile.amd` before replacement. Each ARM64 file is
standalone and contains system packages, Conda setup, task dependencies,
repository checkout, and installation.

## Generate Dockerfiles

Install the generator in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
dockerfile-gen-arm64 --instance_ids astropy__astropy-11693
```

The default command produces pinned task dependencies. When a fully pinned
`environment.arm64.yml` is missing, it runs this pipeline:

1. Generate a temporary Dockerfile from the task's existing requirements and
   ARM64 conversion rules below.
2. Build it with Docker for `linux/arm64`, including the repository clone,
   checkout, history cleanup, and installation.
3. Export the installed `testbed` environment: Conda `name=version=build` pins
   and pip `name==version` pins. Exclude the task package installed from
   `/testbed`; the Dockerfile continues to install that from its Git commit.
4. Generate and build a second Dockerfile containing those exact pins.
5. Inspect both images without network access. Check ARM64 architecture,
   internal Conda mirror URLs, base commit, removed Git remotes, matching
   Conda/pip exports, requested native version pins, and matching installed
   third-party Python versions.
6. Only after verification succeeds, save `environment.arm64.yml` and embed it
   in the final `Dockerfile`, preserving the x86 file as `Dockerfile.amd`.

This runs directly from task files; no SWE-bench v4 build is needed. Docker
Buildx must support ARM64 (natively or through emulation), and the builder must
reach the internal mirror, GitHub, PyPI, and Ubuntu repositories.

Later runs reuse a fully pinned ARM64 snapshot without building. Use
`--refresh-lock` to rebuild and verify it again. This respects the snapshot's
constraints; to select newer packages, edit or remove the relevant pins first.
Build failures leave the task's existing Dockerfile and snapshot unchanged.

To bring an existing ARM64 snapshot's native runtime versions closer to x86:

```bash
dockerfile-gen-arm64 --instance_ids astropy__astropy-6938 --relock-native
```

This retains the existing ARM64 Python and application package versions, including
pip pins, and replaces native requirements with the task's x86 version pins plus
the explicit exceptions in `native-versions.arm64.yml`. Conda may choose different
ARM builds of the retained application versions to satisfy those runtimes.
ARM-only native dependencies are resolved again instead of carrying forward
unnecessarily new pins. The command rebuilds and verifies before replacing files.

Generate several tasks, or every task:

```bash
dockerfile-gen-arm64 --instance_ids astropy__astropy-13236 astropy__astropy-14309
dockerfile-gen-arm64 --all
```

`--all` resolves each task that lacks pins, so it can run many Docker builds.
For fast generation without building or freezing dependencies, use `--draft`:

```bash
dockerfile-gen-arm64 --all --draft --output-dir /tmp/swebench-arm64
```

`--output-dir /tmp/swebench-arm64` writes generated files outside the task tree;
without `--draft`, missing snapshots are still built and verified there.
`python -m dockerfile_gen.arm64` is equivalent to `dockerfile-gen-arm64`.
The script writes `Dockerfile` for ARM64 and saves the original x86 file as
`Dockerfile.amd` once. Later runs preserve that x86 copy. With `--output-dir`,
the Dockerfiles and any ARM64 snapshot are written under the selected directory,
and the task tree is unchanged. `eval.sh` and task metadata are unchanged.
Unknown task IDs fail before writing anything; batch generation reports failures
and exits nonzero if any task fails. The original `dockerfile-gen` command still
generates x86 files; use `dockerfile-gen-arm64` for this workflow.

The functions in [dockerfile_gen/arm64.py](dockerfile_gen/arm64.py) write the base
image, system dependencies, internal Conda setup, environment, and repository
setup. Repository-specific pre-install commands, installation commands, and
trailing Dockerfile instructions reuse the existing generator.
The build/export/verify pipeline is in
[dockerfile_gen/arm64_pipeline.py](dockerfile_gen/arm64_pipeline.py).

Logs and inspection reports are saved to `logs/arm64/<instance_id>/` (ignored by
Git), or `--logs-dir <directory>`. They include `resolve.Dockerfile`,
`verify.Dockerfile`, both build logs, `resolve.json`, `verify.json`, and the
exported `environment.arm64.yml`. Rerunning the same task replaces these logs.
`native-versions.json` compares x86 versions, requested native pins, and the
installed ARM64 versions, including the reasons for declared exceptions.
Temporary image tags are removed on completion; Docker's build cache remains.
Use `--keep-images` to retain the printed image tags for further tests.

Environment selection is:

1. `environment.arm64.yml`, when present: preserve its version constraints,
   Conda build identifiers, and pip pins. Fully pinned snapshots are reused;
   partial snapshots trigger resolution. An output-directory snapshot takes
   precedence over the task-directory snapshot.
2. Otherwise, convert the task's `environment.yml`: keep Python and application
   versions and the pip section, remove Conda build identifiers, remove
   x86/defaults implementation packages such as `_libgcc_mutex` and `numpy-base`,
   change the linker to `ld_impl_linux-aarch64`, and retain native versions using
   exact Conda `name==version` requirements. For names in `NATIVE_RUNTIME`, only
   explicit task overrides can change those versions. Explicit input version
   ranges are retained; empty pip sections are omitted.
3. Tasks without a snapshot use the existing repository/version specifications.
   Requirements files are fetched at `environment_setup_commit`, falling back
   to `base_commit`, so those tasks need GitHub access during generation.

Some x86 defaults-channel versions are absent from ARM64 conda-forge, and some
ARM64 Python builds require newer runtimes than their x86 equivalents. Declare
these exceptions in `tasks/<instance_id>/native-versions.arm64.yml`:

```yaml
libffi:
  version: "3.4.6"
  reason: "3.4.4 is unavailable; use a nearby release in the same 3.4 series."
```

Each entry must name a native package in the x86 snapshot and supply an exact
version string and a nonempty reason. These overrides apply when converting the
x86 environment or running `--relock-native`; normal runs reuse the saved ARM64
snapshot. The generator checks that the installed native versions match the
requested pins. It does not silently remove constraints or automatically choose
a nearest version. A failed solve requires inspecting the mirror and recording a
compatible exception. Tasks without an x86 snapshot have no native reference
versions to preserve; their first successful resolution is frozen as before.

The included ARM64 Astropy tasks have separately verified overrides. Other tasks
may need their own exceptions. A single global runtime version would not fit both
legacy Python 3.6 and newer Python 3.9 builds.

Legacy Astropy snapshots request `setuptools=38.2.4`, which is unavailable as an
ARM64 Conda package in the mirror. The converter keeps version 38.2.4 and installs
its [platform-independent PyPI wheel](https://pypi.org/project/setuptools/38.2.4/#files)
instead. For these environments it creates the Conda environment first, installs
`setuptools==38.2.4`, then installs the remaining pip requirements. The ordering
lets legacy source packages prepare their metadata with the required setuptools
version. Both the initial build and the rebuild from exported pins use this
sequence; Python and application package versions are preserved.

Conda channels are directed to the internal conda-forge mirror. Use
`--artifactory-host <hostname>` to change the generated default. Pip package
sources are unchanged.

An old application version or a platform-specific pip requirement may still be
unavailable on ARM64. The pipeline reports the failed build; it does not silently
upgrade application versions. Adjust the task's `environment.arm64.yml` and rerun
with `--refresh-lock`. Exports that still contain unpinned or direct URL/VCS
requirements are rejected for task-specific handling.

The snapshot pins the task's Conda packages and third-party Python distributions.
It does not pin the Ubuntu image digest, apt package versions, the bootstrap
Conda environment, isolated pip build environments, or pip wheel hashes.
Verification checks the environment and checkout; it does not run the full
benchmark tests.

## Available tasks

| Task | Dockerfile | Validation |
| --- | --- | --- |
| `astropy__astropy-6938` | [Dockerfile](tasks/astropy__astropy-6938/Dockerfile) | Resolve/export/rebuild verified: 21 Conda build pins, 41 pip pins, Python 3.6.13; table/FITS smoke checks and all 11 baseline PASS_TO_PASS tests passed |
| `astropy__astropy-11693` | [Dockerfile](tasks/astropy__astropy-11693/Dockerfile) | Resolve/export/rebuild verified: 30 Conda build pins, 26 pip pins, Python 3.9.21; table/FITS smoke checks and 27 baseline PASS_TO_PASS tests passed with the warning filter below |
| `astropy__astropy-13236` | [Dockerfile](tasks/astropy__astropy-13236/Dockerfile) | Resolve/export/rebuild verified: 31 Conda build pins, 26 pip pins, Python 3.9.23; table/FITS smoke checks passed; original table tests matched the previous image's results, including two existing failures |
| `astropy__astropy-14309` | [Dockerfile](tasks/astropy__astropy-14309/Dockerfile) | Resolve/export/rebuild verified: 30 Conda build pins, 26 pip pins, Python 3.9.20; table/FITS smoke checks and all 141 baseline PASS_TO_PASS tests passed |

Astropy 11693's unmodified offline baseline run passed 26 tests and failed one
because the bundled leap-second data is expired. All 27 passed when rerun with
only `-W 'ignore:leap-second file is expired.:astropy.utils.iers.IERSStaleWarning'`.
This filter was used for validation only; the Dockerfile and task tests do not
include it.

For Astropy 13236, three upstream PASS_TO_PASS selectors do not match the
unpatched checkout: one needs the task's test patch, and two contain truncated
parameter names. Running the original `test_mixin.py` and `test_table.py` files
instead produced 644 passed, 2 failed, 25 skipped, and 1 xfailed. The previous ARM64
image produced the same counts and the same failures in
`test_skycoord_representation` and `test_values_equal_part1`. These existing
application-level failures were not changed by the native-runtime update.

Full benchmark evaluation has not been run for these ARM64 images.

## Build an image

Run from the repository root:

```bash
docker buildx build \
  --platform linux/arm64 \
  --load \
  --progress plain \
  --tag sweb.eval.arm64.astropy__astropy-13236:latest \
  --file tasks/astropy__astropy-13236/Dockerfile \
  tasks/astropy__astropy-13236
```

The Astropy Dockerfile uses Arm's internal Conda mirror. The default host is
`us-west-2.artifactory.aws.arm.com`; select another reachable regional mirror
with `--build-arg ARTIFACTORY_HOST=<hostname>`. The builder needs access to that
mirror, GitHub, PyPI, and Ubuntu package repositories.

Astropy 13236 retains Python 3.9.23 and the successful ARM64 build's 28 third-party
Python distribution versions, including coverage 7.10.7. Its native runtime
versions now follow x86 where compatible, with exceptions documented in
`native-versions.arm64.yml`. The snapshot freezes 31 Conda version/build pins
and 26 pip pins. Astropy is installed from commit
`6ed769d58d89380ebaa1ef52b300691eefda8928`.

Inspect the image without network access:

```bash
docker run --rm --network none \
  sweb.eval.arm64.astropy__astropy-13236:latest \
  /opt/miniconda3/envs/testbed/bin/python -c \
  'import platform, astropy; print(platform.machine(), platform.python_version(), astropy.__version__)'

docker run --rm --network none \
  sweb.eval.arm64.astropy__astropy-13236:latest \
  git -C /testbed log -2 --oneline
```

SWE-bench v5.0.0/v5.0.1's image CLI defaults to AMD64 even when `Dockerfile`
contains an ARM64 image. Use the Docker command above to build these images.
The existing `task.yaml` image references still identify upstream x86 images; selecting an
ARM64 image for evaluation requires separate harness configuration.

## Add another task

Run `dockerfile-gen-arm64 --instance_ids <task_id>` to build, freeze, and verify
the task. If exact x86 native versions cannot be resolved, record compatible
exceptions in `native-versions.arm64.yml` and rerun. Commit its `Dockerfile`,
`Dockerfile.amd`, `environment.arm64.yml`, and any native overrides. Update the
table above with the task and the checks
completed. Shared files such as
`eval.sh`, patches, and task metadata remain available in the same task folder.

## Generator validation

Run focused tests with `python -m unittest discover -s tests -v`.

On 2026-10-28, all 28 focused tests passed, including exact native constraints,
override validation, preservation of ARM application versions during relocking,
and rejection of native version drift. Ruff checks passed. All 2,519 tasks
generated in draft mode with the stricter native policy; all archived x86
Dockerfiles matched their source files byte-for-byte. Draft generation does not
establish that a task's dependencies can resolve on ARM64.

Astropy 6938, 11693, and 13236 passed the complete resolve/export/rebuild pipeline,
native-pin comparison, and offline table/FITS smoke checks. Their Python versions
and previous third-party Python distribution versions were retained: 44 for
Astropy 6938, 28 for 11693, and 28 for 13236. Saved Dockerfiles matched the verified
build inputs, x86 archives were unchanged, and repeat generation reused the
verified snapshots without changing the files. Reports for this validation run
are in `logs/arm64/native-pins/<instance_id>/` (ignored by Git).
See the table above for baseline test results and their limitations.

Astropy 14309 initially failed to resolve exact x86 native versions. Its
`native-versions.arm64.yml` now records compatible alternatives, including
OpenSSL 3.3.2, SQLite 3.46.1, and GCC runtimes 13.3.0 for ARM64 Python 3.9.20.
The complete resolve/export/rebuild pipeline passed, retaining the x86 Python,
pip, wheel, and pip-package versions. Both images matched all 30 Conda build pins,
26 pip pins, and 28 third-party Python distribution versions. Offline table/FITS
smoke checks and all 141 baseline PASS_TO_PASS tests passed. Pytest startup emitted
a NumPy ndarray-size `RuntimeWarning`; no selected test failed. The saved
Dockerfile matched the verified build input, its x86 archive matched the original
byte-for-byte, and repeat generation left the files unchanged. Reports are in
`logs/arm64/astropy__astropy-14309/`; the original failed build is preserved as
`failed-before-native-pins.log` there.

Other tasks may need native overrides before they can build. The full benchmark,
including evaluation with the task's test and solution patches, has not been run.
