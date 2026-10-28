# ARM64 task images

ARM64 Dockerfiles live at `tasks/<instance_id>/Dockerfile.arm64`. Each file is
standalone and contains system packages, Conda setup, pinned dependencies,
repository checkout, and installation.

## Available tasks

| Task | Dockerfile | Validation |
| --- | --- | --- |
| `astropy__astropy-13236` | [Dockerfile.arm64](tasks/astropy__astropy-13236/Dockerfile.arm64) | ARM64 build, dependency versions, Git checkout, and import/table smoke test passed |

Full benchmark evaluation has not been run for this ARM64 image.

## Build an image

Run from the repository root:

```bash
docker buildx build \
  --platform linux/arm64 \
  --load \
  --progress plain \
  --tag sweb.eval.arm64.astropy__astropy-13236:latest \
  --file tasks/astropy__astropy-13236/Dockerfile.arm64 \
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

SWE-bench v5.0.0/v5.0.1's image CLI defaults to AMD64 and selects `Dockerfile`.
Use the Docker command above to build these ARM64 variants. The existing
`task.yaml` image references still identify upstream x86 images; selecting an
ARM64 image for evaluation requires separate harness configuration.

## Add another task

Add a `Dockerfile.arm64` beside the task's existing Dockerfile, preserve the
task's base commit, and use dependency pins validated on ARM64. Update the
table above with the task and the checks completed. Shared files such as
`eval.sh`, patches, and task metadata remain available in the same task folder.
