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
dockerfile-gen-arm64 --instance_ids astropy__astropy-13236
```

Generate several tasks, or every task, without building images:

```bash
dockerfile-gen-arm64 --instance_ids astropy__astropy-13236 astropy__astropy-14309
dockerfile-gen-arm64 --all
```

For a preview outside the task tree, add `--output-dir /tmp/swebench-arm64`.
`python -m dockerfile_gen.arm64` is equivalent to `dockerfile-gen-arm64`.
The script writes `Dockerfile` for ARM64 and saves the original x86 file as
`Dockerfile.amd` once. Later runs preserve that x86 copy. With `--output-dir`,
both files are written under the selected directory and the task tree is
unchanged. `eval.sh` and task metadata are unchanged. Unknown task IDs fail before
writing anything; batch generation reports failures and exits nonzero if any
task fails. The original `dockerfile-gen` command still generates x86 files;
use `dockerfile-gen-arm64` for this workflow.

The functions in [dockerfile_gen/arm64.py](dockerfile_gen/arm64.py) write the base
image, system dependencies, internal Conda setup, environment, and repository
setup. Repository-specific pre-install commands, installation commands, and
trailing Dockerfile instructions reuse the existing generator.

Environment selection is:

1. `environment.arm64.yml`, when present: preserve the Conda versions and build
   identifiers as well as pip pins. Astropy 13236 includes its validated snapshot.
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

Generation does not solve dependencies or prove ARM64 compatibility. Conda and
pip resolve packages during `docker build`. An old application version or a
platform-specific pip requirement may still be unavailable on ARM64; generation
does not silently upgrade application versions. Adjust a task-specific
`environment.arm64.yml`, build and verify it, then regenerate to embed those pins.

## Available tasks

| Task | Dockerfile | Validation |
| --- | --- | --- |
| `astropy__astropy-13236` | [Dockerfile](tasks/astropy__astropy-13236/Dockerfile) | ARM64 build, dependency versions, Git checkout, and import/table smoke test passed |

Full benchmark evaluation has not been run for this ARM64 image.

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

The environment preserves the successful ARM64 build's 23 Conda version/build
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

Generate an ARM64 `Dockerfile` while preserving the original as `Dockerfile.amd`,
keep the task's base commit, and save dependency pins validated on ARM64. Update the
table above with the task and the checks completed. Shared files such as
`eval.sh`, patches, and task metadata remain available in the same task folder.

## Generator validation

Run focused tests with `python -m unittest discover -s tests -v`.

On 2026-10-28, all 11 tests passed. All 2,519 tasks generated successfully in a
temporary directory; their shell blocks passed syntax checks and their x86
archives matched the source files. ARM64 builds and import/table smoke tests
passed for Astropy 13236 (saved ARM64 pins) and Astropy 14309 (converted x86
snapshot), with dependency versions, mirror URLs, and base commits checked.
The other generated images have not been built, and full benchmark evaluations
have not been run.
