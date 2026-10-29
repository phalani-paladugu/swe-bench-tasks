# SWE-bench task data

Dockerfile generator for the SWE-bench benchmark. This repo is just for the original SWE-bench benchmark and does not contain any data related to the newer benchmarks we released like SWE-bench Multilingual or SWE-bench Multimodal.

## Usage

```bash
# From HuggingFace dataset
dockerfile-gen

# From local JSON/JSONL file
dockerfile-gen

# Specific instances
dockerfile-gen
```

## Output

`Dockerfile` and `eval.sh` are regenerated in place under `tasks/<instance_id>/`, from that task's `task.yaml`.

## ARM64 images

Generated ARM64 images use `Dockerfile`; the original x86 file is saved as
`Dockerfile.amd` in the same task directory.
Generate them with `dockerfile-gen-arm64 --instance_ids <task_id>` after
installation. When ARM64 pins are missing, this builds an ARM64 image, exports
exact Conda and pip versions, and verifies a rebuild before saving the Dockerfile
and `environment.arm64.yml`. Existing pinned snapshots are reused. Add `--draft`
to generate without building, or `--all` to process all tasks. See
[ARM64.md](ARM64.md) for the pipeline, conversion rules, and build instructions.
Native runtime versions follow the x86 snapshot, with documented exceptions in
each task's `native-versions.arm64.yml`. Use `--relock-native` to apply those
constraints to an existing ARM64 snapshot while retaining its Python/pip versions.

## Install

```bash
pip install -e .
```
