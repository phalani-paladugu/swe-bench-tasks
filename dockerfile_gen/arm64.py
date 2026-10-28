"""Generate standalone ARM64 Dockerfiles; dependency solving happens at build time."""

import argparse
import re
import shutil
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
blas blas-devel libblas libcblas liblapack liblapacke openblas libopenblas""".split()
)


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


def arm_environment(text: str, *, pinned: bool = False) -> str:
    """Retain application/pip versions; re-solve native runtime pins for ARM64."""
    environment = yaml.safe_load(text)
    if not isinstance(environment, dict) or not isinstance(
        environment.get("dependencies"), list
    ):
        raise ValueError("Environment YAML must contain a dependencies list")
    dependencies = []
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
            if name in NATIVE_RUNTIME and re.fullmatch(
                r"[\w.-]+=[^=]+(?:=.*)?", dependency
            ):
                dependency = name
            else:
                dependency = re.sub(r"^([\w.-]+=[^=]+)=.+$", r"\1", dependency)
        dependencies.append(dependency)
    return yaml.safe_dump(
        {"name": "testbed", "channels": ["conda-forge"], "dependencies": dependencies},
        sort_keys=False,
    )


def write_dependencies(task_dir: Path, instance: dict, specs: dict) -> str:
    arm_file = task_dir / "environment.arm64.yml"
    env_file = arm_file if arm_file.is_file() else task_dir / "environment.yml"
    if env_file.is_file():
        text = env_file.read_text()
    elif specs.get("packages") == "environment.yml":
        text = get_environment_yml(instance)
    else:
        # Reuse the repository's Python/package/requirements.txt setup for dev tasks.
        return make_env_script_list(instance, specs)
    text = arm_environment(text, pinned=arm_file.is_file())
    delimiter = generate_heredoc_delimiter(text)
    return make_heredoc_run_command(
        [
            "source /opt/miniconda3/bin/activate",
            f"cat > /root/environment.yml <<'{delimiter}'\n{text}{delimiter}",
            "conda env create --file /root/environment.yml",
        ]
    )


def write_repo_setup(instance: dict, specs: dict) -> str:
    # Includes clone, pinned checkout, history cleanup, pre-install fixes and install.
    return make_repo_script_list(specs, instance["repo"], instance["base_commit"])


def generate(task_dir: Path, mirror_host: str = DEFAULT_MIRROR) -> str:
    instance = yaml.safe_load((task_dir / "task.yaml").read_text())
    specs = MAP_REPO_VERSION_TO_SPECS[instance["repo"]][instance["version"]]
    return "\n".join(
        [
            write_base_image(),
            write_system_dependencies(),
            write_conda(mirror_host),
            write_dependencies(task_dir, instance, specs),
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
    args = parser.parse_args()
    tasks = {task.name: task for task in task_dirs()}
    wanted = sorted(set(args.instance_ids or tasks))
    unknown = set(wanted) - tasks.keys()
    if unknown:
        parser.error(f"Unknown task IDs: {', '.join(sorted(unknown))}")
    failed = 0
    for task_id in wanted:
        try:
            dockerfile = generate(tasks[task_id], args.artifactory_host)
            print(write_dockerfile(tasks[task_id], dockerfile, args.output_dir))
        except (
            OSError,
            ValueError,
            KeyError,
            yaml.YAMLError,
            requests.RequestException,
        ) as error:
            print(f"{task_id}: {error}", file=sys.stderr)
            failed += 1
    print(f"Generated {len(wanted) - failed} Dockerfiles; {failed} failed.")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
