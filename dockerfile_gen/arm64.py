"""Generate pinned ARM64 Dockerfiles, resolving missing environments with Docker."""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

import requests
import yaml

from . import get_environment_yml, make_env_script_list, make_repo_script_list
from .constants import MAP_REPO_VERSION_TO_SPECS
from .tasks import task_dirs
from .utils import generate_heredoc_delimiter, make_heredoc_run_command

DEFAULT_MIRROR = "us-west-2.artifactory.aws.arm.com"
SYSTEM_PACKAGES = """wget git build-essential libffi-dev libtiff-dev python3
python3-pip python-is-python3 jq curl ca-certificates bzip2 locales locales-all
tzdata""".split()
# Defaults/x86 implementation packages are replaced by the ARM solver's choices.
X86_ONLY = {
    "_libgcc_mutex",
    "numpy-base",
    "intel-openmp",
    "mkl",
    "mkl-service",
    "mkl_fft",
    "mkl_random",
}
NATIVE_RUNTIME = set(
    """_openmp_mutex bzip2 ca-certificates expat libexpat libffi
libgcc libgcc-ng libgomp libstdcxx libstdcxx-ng libgfortran libgfortran-ng
libgfortran4 libgfortran5 liblzma libnsl libsqlite libuuid libxcrypt libzlib
ncurses openssl readline sqlite tk tzdata xz zlib zstd ld_impl_linux-aarch64
liblzma-devel xz-tools xz-gpl-tools
blas blas-devel libblas libcblas liblapack liblapacke openblas libopenblas""".split()
)
# Unavailable in the ARM64 mirror; PyPI provides a platform-independent wheel.
CONDA_TO_PIP = {"setuptools=38.2.4": "setuptools==38.2.4"}


def write_base_image() -> str:
    return """# syntax=docker/dockerfile:1
FROM --platform=linux/arm64 ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC
"""


def write_system_dependencies() -> str:
    packages = " ".join(SYSTEM_PACKAGES)
    return (
        f"RUN apt update && apt install -y {packages} && rm -rf /var/lib/apt/lists/*\n"
    )


def write_conda(mirror_host: str = DEFAULT_MIRROR) -> str:
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", mirror_host):
        raise ValueError("Artifactory host must be a hostname without a scheme or path")
    return f"""# Install Conda from the internal mirror.
ARG ARTIFACTORY_HOST={mirror_host}
ENV CONDARC=/etc/conda/condarc
RUN <<'BOOTSTRAP_CONDA'
set -eu
mkdir -p /etc/conda /tmp/swebench-micromamba
cat > /etc/conda/condarc <<CONDARC_CONFIG
channel_alias: https://${{ARTIFACTORY_HOST}}/artifactory/api/conda/
default_channels:
  - conda-forge
channels:
  - defaults
CONDARC_CONFIG
curl -fSL --retry 3 "https://${{ARTIFACTORY_HOST}}/artifactory/conda-forge/linux-aarch64/micromamba-2.1.0-0.tar.bz2" -o /tmp/swebench-micromamba/micromamba.tar.bz2
tar -xjf /tmp/swebench-micromamba/micromamba.tar.bz2 -C /tmp/swebench-micromamba bin/micromamba
/tmp/swebench-micromamba/bin/micromamba --rc-file /etc/conda/condarc create -y -p /opt/miniconda3 --override-channels -c conda-forge mamba conda
rm -rf /tmp/swebench-micromamba
BOOTSTRAP_CONDA
ENV PATH=/opt/miniconda3/bin:$PATH
RUN conda init --all
RUN adduser --disabled-password --gecos 'dog' nonroot
"""


def arm_environment(
    text: str, *, pinned: bool = False, native_versions: dict | None = None
) -> str:
    """Keep x86 versions, selecting ARM builds and explicit native substitutions."""
    environment = yaml.safe_load(text)
    if not isinstance(environment, dict) or not isinstance(
        environment.get("dependencies"), list
    ):
        raise ValueError("Environment YAML must contain a dependencies list")
    dependencies = []
    migrated = []
    for dependency in environment["dependencies"]:
        if isinstance(dependency, dict):
            if dependency == {"pip": None} or dependency == {"pip": []}:
                continue
            if set(dependency) != {"pip"} or not isinstance(dependency["pip"], list):
                raise ValueError(f"Unsupported environment dependency: {dependency!r}")
            dependencies.append(dependency)
            continue
        if not isinstance(dependency, str):
            raise ValueError(f"Unsupported Conda dependency: {dependency!r}")
        if "::" in dependency:
            channel, dependency = dependency.split("::", 1)
            if channel not in {"defaults", "conda-forge"}:
                raise ValueError(
                    f"Conda channel {channel!r} is not in the internal mirror"
                )
        match = re.fullmatch(r"([\w.-]+)\s*([=<>!~].*)?", dependency)
        if not match:
            raise ValueError(f"Unsupported Conda dependency: {dependency!r}")
        name = match[1]
        if pinned:
            if name in X86_ONLY or name.endswith("linux-64"):
                raise ValueError(f"x86 package in environment.arm64.yml: {name}")
        else:
            if name in X86_ONLY:
                continue
            if name == "ld_impl_linux-64":
                name = "ld_impl_linux-aarch64"
                dependency = dependency.replace("ld_impl_linux-64", name, 1)
            dependency = re.sub(r"^([\w.-]+=[^=]+)=.+$", r"\1", dependency)
            exact = re.fullmatch(r"[\w.-]+={1,2}([\w.!+-]+)", dependency)
            if name in NATIVE_RUNTIME:
                replacement = (native_versions or {}).get(name)
                if replacement:
                    dependency = f"{name}=={replacement['version']}"
                elif exact:
                    dependency = f"{name}=={exact[1]}"
            if dependency in CONDA_TO_PIP:
                migrated.append(CONDA_TO_PIP[dependency])
                continue
        dependencies.append(dependency)
    if migrated:
        pip = next((d["pip"] for d in dependencies if isinstance(d, dict)), None)
        if pip is None:
            pip = []
            dependencies.append({"pip": pip})
        for requirement in migrated:
            name = requirement.split("==")[0]
            existing = [
                p for p in pip if re.match(rf"{re.escape(name)}\s*[=<>!~ @]", p)
            ]
            if existing and existing != [requirement]:
                raise ValueError(f"Conflicting pip requirement for {name}: {existing}")
            if not existing:
                pip.append(requirement)
    return yaml.safe_dump(
        {"name": "testbed", "channels": ["conda-forge"], "dependencies": dependencies},
        sort_keys=False,
    )


def load_native_versions(task_dir: Path) -> dict:
    path = task_dir / "native-versions.arm64.yml"
    if not path.is_file():
        return {}
    versions = yaml.safe_load(path.read_text())
    if not isinstance(versions, dict):
        raise ValueError(f"{path}: expected package names mapped to version/reason")
    reference = yaml.safe_load((task_dir / "environment.yml").read_text())
    names = {
        re.split(r"[=<>!~ ]", pin.split("::")[-1])[0].replace(
            "ld_impl_linux-64", "ld_impl_linux-aarch64"
        )
        for pin in reference["dependencies"]
        if isinstance(pin, str)
    }
    for name, entry in versions.items():
        if (
            name not in NATIVE_RUNTIME
            or name not in names
            or not isinstance(entry, dict)
            or set(entry) != {"version", "reason"}
            or not isinstance(entry["version"], str)
            or not re.fullmatch(r"[\w.!+-]+", entry["version"])
            or not isinstance(entry["reason"], str)
            or not entry["reason"].strip()
        ):
            raise ValueError(f"{path}: invalid native version override for {name!r}")
    return versions


def relock_native_environment(task_dir: Path, environment: str | None = None) -> str:
    """Rebase native requirements on x86 while preserving ARM application versions."""
    source = (task_dir / "environment.yml").read_text()
    converted = yaml.safe_load(
        arm_environment(source, native_versions=load_native_versions(task_dir))
    )
    if environment is None:
        return yaml.safe_dump(converted, sort_keys=False)
    current = yaml.safe_load(arm_environment(environment, pinned=True))
    native = [
        pin
        for pin in converted["dependencies"]
        if isinstance(pin, str) and re.split(r"[=<>!~ ]", pin)[0] in NATIVE_RUNTIME
    ]
    applications = []
    for pin in current["dependencies"]:
        if isinstance(pin, dict):
            applications.append(pin)
        elif re.split(r"[=<>!~ ]", pin)[0] not in NATIVE_RUNTIME:
            # A different ARM build of the same application version may use older runtimes.
            applications.append(
                re.sub(r"^([\w.-]+)=([\w.!+-]+)=[\w.+-]+$", r"\1==\2", pin)
            )
    converted["dependencies"] = native + applications
    return yaml.safe_dump(converted, sort_keys=False)


def write_dependencies(
    task_dir: Path, instance: dict, specs: dict, environment: str | None = None
) -> str:
    arm_file = task_dir / "environment.arm64.yml"
    env_file = arm_file if arm_file.is_file() else task_dir / "environment.yml"
    if environment is not None:
        text = environment
    elif env_file.is_file():
        text = env_file.read_text()
    elif specs.get("packages") == "environment.yml":
        text = get_environment_yml(instance)
    else:
        # Reuse the repository's Python/package/requirements.txt setup for dev tasks.
        return make_env_script_list(instance, specs)
    pinned = environment is not None or arm_file.is_file()
    text = arm_environment(
        text,
        pinned=pinned,
        native_versions=load_native_versions(task_dir) if not pinned else None,
    )
    parsed = yaml.safe_load(text)
    pip = [
        pin
        for dependency in parsed["dependencies"]
        if isinstance(dependency, dict)
        for pin in dependency["pip"]
    ]
    legacy_setuptools = "setuptools==38.2.4" in pip
    if legacy_setuptools:
        # Legacy source packages need this setuptools installed before pip prepares metadata.
        parsed["dependencies"] = [
            d for d in parsed["dependencies"] if isinstance(d, str)
        ]
        text = yaml.safe_dump(parsed, sort_keys=False)
    delimiter = generate_heredoc_delimiter(text)
    commands = [
        "source /opt/miniconda3/bin/activate",
        f"cat > /root/environment.yml <<'{delimiter}'\n{text}{delimiter}",
        "conda env create --file /root/environment.yml",
    ]
    if legacy_setuptools:
        requirements = "\n".join(pip) + "\n"
        delimiter = generate_heredoc_delimiter(requirements)
        commands.extend(
            [
                "conda activate testbed",
                "python -m pip install setuptools==38.2.4",
                f"cat > /root/requirements.txt <<'{delimiter}'\n{requirements}{delimiter}",
                "python -m pip install -r /root/requirements.txt",
            ]
        )
    return make_heredoc_run_command(commands)


def write_repo_setup(instance: dict, specs: dict) -> str:
    # Includes clone, pinned checkout, history cleanup, pre-install fixes and install.
    return make_repo_script_list(specs, instance["repo"], instance["base_commit"])


def generate(
    task_dir: Path, mirror_host: str = DEFAULT_MIRROR, environment: str | None = None
) -> str:
    instance = yaml.safe_load((task_dir / "task.yaml").read_text())
    specs = MAP_REPO_VERSION_TO_SPECS[instance["repo"]][instance["version"]]
    return "\n".join(
        [
            write_base_image(),
            write_system_dependencies(),
            write_conda(mirror_host),
            write_dependencies(task_dir, instance, specs, environment),
            'RUN echo "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed" > /root/.bashrc\n',
            write_repo_setup(instance, specs),
            "WORKDIR /testbed/\n",
            *specs.get("dockerfile_extra", []),
        ]
    )


def write_dockerfile(
    task_dir: Path, dockerfile: str, output_dir: Path | None = None
) -> Path:
    directory = output_dir / task_dir.name if output_dir else task_dir
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / "Dockerfile.amd"
    original = task_dir / "Dockerfile.amd"
    if not original.is_file():
        original = task_dir / "Dockerfile"
    if not archive.exists() and original.is_file():
        if re.search(r"^FROM .*--platform=linux/arm64", original.read_text(), re.M):
            raise ValueError(
                "Original Dockerfile is already ARM64; supply Dockerfile.amd first"
            )
        shutil.copyfile(original, archive)
    destination = directory / "Dockerfile"
    destination.write_text(dockerfile)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--instance_ids", nargs="+", help="Task IDs to generate")
    selection.add_argument("--all", action="store_true", help="Generate every task")
    parser.add_argument("--artifactory-host", default=DEFAULT_MIRROR)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Write <dir>/<task>/Dockerfile and Dockerfile.amd",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--draft",
        action="store_true",
        help="Generate only; do not resolve missing pins",
    )
    mode.add_argument(
        "--refresh-lock",
        action="store_true",
        help="Rebuild and verify even when an ARM64 snapshot already exists",
    )
    mode.add_argument(
        "--relock-native",
        action="store_true",
        help="Align native versions with x86 and task overrides, retaining ARM application versions",
    )
    parser.add_argument("--logs-dir", type=Path, default=Path("logs/arm64"))
    parser.add_argument(
        "--keep-images",
        action="store_true",
        help="Keep temporary resolve/verify images",
    )
    args = parser.parse_args()
    tasks = {task.name: task for task in task_dirs()}
    wanted = sorted(set(args.instance_ids or tasks))
    unknown = set(wanted) - tasks.keys()
    if unknown:
        parser.error(f"Unknown task IDs: {', '.join(sorted(unknown))}")
    from .arm64_pipeline import is_fully_pinned, resolve_environment

    failed = 0
    for task_id in wanted:
        try:
            task = tasks[task_id]
            directory = args.output_dir / task_id if args.output_dir else task
            saved = directory / "environment.arm64.yml"
            if not saved.is_file():
                saved = task / "environment.arm64.yml"
            environment = saved.read_text() if saved.is_file() else None
            if args.relock_native:
                environment = relock_native_environment(task, environment)
            needs_resolution = environment is None or not is_fully_pinned(environment)
            if not args.draft and (
                args.refresh_lock or args.relock_native or needs_resolution
            ):
                environment = resolve_environment(
                    task,
                    args.artifactory_host,
                    args.logs_dir,
                    environment=environment,
                    keep_images=args.keep_images,
                )
            dockerfile = generate(task, args.artifactory_host, environment)
            print(write_dockerfile(task, dockerfile, args.output_dir))
            if environment is not None:
                (directory / "environment.arm64.yml").write_text(environment)
            if args.draft and needs_resolution:
                print(f"{task_id}: draft only; dependencies have not been frozen")
        except (
            OSError,
            ValueError,
            KeyError,
            yaml.YAMLError,
            requests.RequestException,
            subprocess.SubprocessError,
            RuntimeError,
        ) as error:
            print(f"{task_id}: {error}", file=sys.stderr)
            failed += 1
    print(f"Generated {len(wanted) - failed} Dockerfiles; {failed} failed.")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
