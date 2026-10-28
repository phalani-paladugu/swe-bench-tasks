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
   Conda/pip exports, and matching installed third-party Python versions.
6. Only after verification succeeds, save `environment.arm64.yml` and embed it
   in the final `Dockerfile`, preserving the x86 file as `Dockerfile.amd`.

This runs directly from task files; no SWE-bench v4 build is needed. Docker
Buildx must support ARM64 (natively or through emulation), and the builder must
reach the internal mirror, GitHub, PyPI, and Ubuntu repositories.

Later runs reuse a fully pinned ARM64 snapshot without building. Use
`--refresh-lock` to rebuild and verify it again. This respects the snapshot's
constraints; to select newer packages, edit or remove the relevant pins first.
Build failures leave the task's existing Dockerfile and snapshot unchanged.

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
   change the linker to `ld_impl_linux-aarch64`, and release the native runtime
   exact version pins listed in `NATIVE_RUNTIME` so Conda can select compatible
   builds. Explicit version ranges are retained; empty pip sections are omitted.
3. Tasks without a snapshot use the existing repository/version specifications.
   Requirements files are fetched at `environment_setup_commit`, falling back
   to `base_commit`, so those tasks need GitHub access during generation.

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
| `astropy__astropy-11693` | [Dockerfile](tasks/astropy__astropy-11693/Dockerfile) | Resolve/export/rebuild verification passed: 31 Conda build pins, 26 pip pins, Python 3.9.21; import/table smoke tests passed |
| `astropy__astropy-13236` | [Dockerfile](tasks/astropy__astropy-13236/Dockerfile) | ARM64 build, dependency versions, Git checkout, and import/table smoke test passed |

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

Astropy 13236 preserves the successful ARM64 build's 23 Conda version/build
pins and 28 Python distribution versions, including Python 3.9.23 and coverage
7.10.7. Astropy is installed from commit
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
the task, then commit its `Dockerfile`, `Dockerfile.amd`, and
`environment.arm64.yml`. Update the table above with the task and the checks
completed. Shared files such as
`eval.sh`, patches, and task metadata remain available in the same task folder.

## Generator validation

Run focused tests with `python -m unittest discover -s tests -v`.

On 2026-10-28, all 19 tests passed. All 2,519 tasks generated successfully in draft
mode in a temporary directory; all 7,557 shell blocks passed syntax checks and
their x86 archives matched the source files byte-for-byte.

The complete resolve/export/rebuild pipeline passed for Astropy 11693: both
images matched 31 Conda version/build pins, 26 pip pins, and all 28 third-party
Python distribution versions. Offline import/table tests passed in both images.
The saved Dockerfile matched the verified build input, and a subsequent command
reused the snapshot without changing the generated files.

Earlier ARM64 builds and import/table smoke tests passed for Astropy 13236
(saved ARM64 pins) and Astropy 14309 (converted x86 snapshot), with dependency
versions, mirror URLs, and base commits checked. The remaining generated images
have not been built, and full benchmark evaluations have not been run.
