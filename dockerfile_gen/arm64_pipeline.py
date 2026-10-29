"""Resolve on ARM64, export dependencies, and verify a rebuild from those pins."""

import json
import re
import shlex
import subprocess
import uuid
from pathlib import Path

import yaml

from .arm64 import NATIVE_RUNTIME, arm_environment, generate, load_native_versions


def is_fully_pinned(text: str) -> bool:
    environment = yaml.safe_load(text)
    if not isinstance(environment, dict):
        return False
    dependencies = environment.get("dependencies")
    if not isinstance(dependencies, list):
        return False
    has_python = False
    for dependency in dependencies:
        if isinstance(dependency, str):
            if not re.fullmatch(r"[\w.-]+=[\w.!+-]+=[\w.+-]+", dependency):
                return False
            has_python |= dependency.startswith("python=")
        elif isinstance(dependency, dict) and set(dependency) == {"pip"}:
            pins = dependency["pip"]
            if not isinstance(pins, list) or not all(
                isinstance(pin, str) and re.fullmatch(r"[\w.-]+==[\w.!+-]+", pin)
                for pin in pins
            ):
                return False
        else:
            return False
    return has_python


def frozen_environment(report: dict, mirror_host: str, base_commit: str) -> str:
    if report["architecture"] != "aarch64":
        raise ValueError("Resolved image is not ARM64")
    if report["base_commit"] != base_commit or report["git_remotes"]:
        raise ValueError(
            "Image repository checkout/history cleanup did not match the task"
        )
    local = set(report["local_distributions"]) & report["python_distributions"].keys()
    if not local:
        raise ValueError(
            "Cannot identify the installed /testbed project to exclude from pins"
        )

    def conda_pin(name):
        record = report["conda_records"][name]
        if record["subdir"] not in {"linux-aarch64", "noarch"}:
            raise ValueError(f"Non-ARM64 Conda package: {name}")
        if not (record["url"] or "").startswith(f"https://{mirror_host}/artifactory/"):
            raise ValueError(
                f"Conda package did not come from the internal mirror: {name}"
            )
        return f"{name}={record['version']}={record['build']}"

    conda, pip = {}, []
    # Use Conda's export, not all conda-meta records: pip may have replaced a package.
    for dependency in report["environment"]["dependencies"]:
        if isinstance(dependency, str):
            name = dependency.split("::")[-1].split("=")[0]
            if name in local:
                continue
            conda[name] = conda_pin(name)
        else:
            for pin in dependency["pip"]:
                name = re.sub(r"[-_.]+", "-", re.split(r"[= @]", pin)[0]).lower()
                if name not in local:
                    pip.append(pin)
    # Native files remain installed when a distinct PyPI package shares their name
    # (e.g. tzdata). Conda's export hides these; preserve both sets of pins.
    for name in (report["conda_records"].keys() & NATIVE_RUNTIME) - local:
        if name not in conda:
            conda[name] = conda_pin(name)
    dependencies = sorted(conda.values())
    if pip:
        dependencies.append({"pip": sorted(pip)})
    frozen = arm_environment(
        yaml.safe_dump({"dependencies": dependencies}), pinned=True
    )
    if not is_fully_pinned(frozen):
        raise ValueError(
            "Export contains unpinned/source dependencies; adjust the task environment"
        )
    return frozen


def build_image(task_dir: Path, dockerfile: str, image: str, log_dir: Path, stage: str):
    source = log_dir / f"{stage}.Dockerfile"
    source.write_text(dockerfile)
    log_path = log_dir / f"{stage}-build.log"
    command = [
        "docker",
        "buildx",
        "build",
        "--platform",
        "linux/arm64",
        "--load",
        "--progress",
        "plain",
        "--tag",
        image,
        "--file",
        str(source),
        str(task_dir.resolve()),
    ]
    print(f"{task_dir.name}: {stage} build; log: {log_path}", flush=True)
    with log_path.open("w") as log:
        log.write(shlex.join(command) + "\n")
        log.flush()
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"{stage} build failed; see {log_path}")


def inspect_image(image: str, log_dir: Path, stage: str) -> dict:
    script = Path(__file__).with_name("arm64_inspect.py").read_text()
    log_path = log_dir / f"{stage}-inspect.log"
    with log_path.open("w") as log:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--platform",
                "linux/arm64",
                "--workdir",
                "/",
                "--entrypoint",
                "/opt/miniconda3/bin/python",
                image,
                "-c",
                script,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=log,
        )
    if result.returncode:
        raise RuntimeError(f"{stage} inspection failed; see {log_path}")
    report = json.loads(result.stdout)
    (log_dir / f"{stage}.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    return report


def third_party(report: dict) -> dict:
    return {
        name: version
        for name, version in report["python_distributions"].items()
        if name not in report["local_distributions"]
    }


def check_native_versions(task_dir: Path, environment: str | None, frozen: str) -> list:
    """Check requested native pins and explain version differences from x86."""
    source = task_dir / "environment.yml"
    x86 = source.read_text() if source.is_file() else "dependencies: []"
    if environment is None:
        saved = task_dir / "environment.arm64.yml"
        environment = saved.read_text() if saved.is_file() else None
    overrides = load_native_versions(task_dir, environment)
    if environment is None:
        environment = arm_environment(x86, native_versions=overrides)

    def versions(text):
        result = {}
        for pin in yaml.safe_load(text)["dependencies"]:
            if isinstance(pin, str):
                match = re.fullmatch(
                    r"([\w.-]+)={1,2}([\w.!+-]+)(?:=([\w.+-]+))?", pin.split("::")[-1]
                )
                if match:
                    name = match[1].replace("ld_impl_linux-64", "ld_impl_linux-aarch64")
                    if name in NATIVE_RUNTIME:
                        result[name] = match[2]
        return result

    original, requested, installed = (
        versions(x86),
        versions(environment),
        versions(frozen),
    )
    for name, version in requested.items():
        if installed.get(name) != version:
            raise ValueError(
                f"Native pin changed for {name}: requested {version}, installed {installed.get(name)}"
            )
    return [
        {
            "package": name,
            "x86_version": original.get(name),
            "requested_version": requested.get(name),
            "arm64_version": installed[name],
            "reason": overrides.get(name, {}).get("reason")
            if overrides.get(name, {}).get("version") == installed[name]
            else None,
        }
        for name in sorted(installed)
    ]


def resolve_environment(
    task_dir: Path,
    mirror_host: str,
    logs_dir: Path,
    *,
    environment: str | None = None,
    keep_images: bool = False,
) -> str:
    log_dir = (logs_dir / task_dir.name).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    base_commit = yaml.safe_load((task_dir / "task.yaml").read_text())["base_commit"]
    run_id = uuid.uuid4().hex[:12]
    images = [
        f"sweb.arm64.{task_dir.name}:{stage}-{run_id}"
        for stage in ("resolve", "verify")
    ]
    try:
        build_image(
            task_dir,
            generate(task_dir, mirror_host, environment),
            images[0],
            log_dir,
            "resolve",
        )
        resolved = inspect_image(images[0], log_dir, "resolve")
        frozen = frozen_environment(resolved, mirror_host, base_commit)
        comparison = check_native_versions(task_dir, environment, frozen)
        (log_dir / "native-versions.json").write_text(
            json.dumps(comparison, indent=2) + "\n"
        )
        (log_dir / "environment.arm64.yml").write_text(frozen)
        build_image(
            task_dir,
            generate(task_dir, mirror_host, frozen),
            images[1],
            log_dir,
            "verify",
        )
        verified = inspect_image(images[1], log_dir, "verify")
        if yaml.safe_load(frozen) != yaml.safe_load(
            frozen_environment(verified, mirror_host, base_commit)
        ):
            raise ValueError(
                f"Rebuilt Conda/pip pins changed; compare reports in {log_dir}"
            )
        if third_party(resolved) != third_party(verified):
            raise ValueError(
                f"Rebuilt Python distribution versions changed; compare reports in {log_dir}"
            )
        print(f"{task_dir.name}: ARM64 dependency pins verified", flush=True)
        return frozen
    finally:
        if keep_images:
            print(f"Temporary images: {' '.join(images)}", flush=True)
        else:
            for image in images:
                try:
                    subprocess.run(
                        ["docker", "image", "rm", image],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except OSError:
                    pass
