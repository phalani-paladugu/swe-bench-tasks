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
Generate them with `dockerfile-gen-arm64 --instance_ids <task_id>` or
`dockerfile-gen-arm64 --all` after installation. See [ARM64.md](ARM64.md) for
environment conversion rules, available images, and build instructions.

## Install

```bash
pip install -e .
```
