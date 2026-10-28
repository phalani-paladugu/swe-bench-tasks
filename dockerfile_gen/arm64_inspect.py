"""Standalone stdlib probe, executed by the image's bootstrap Python."""

import configparser
import email.parser
import json
import platform
import re
import subprocess
import tomllib
from pathlib import Path


def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def output(*command):
    return subprocess.check_output(command, text=True).strip()


def inspect():
    prefix = Path("/opt/miniconda3/envs/testbed")
    python = str(prefix / "bin/python")
    repository = Path("/testbed")
    packages = json.loads(output(python, "-m", "pip", "list", "--format=json"))
    editable = json.loads(
        output(python, "-m", "pip", "list", "--editable", "--format=json")
    )
    local = {
        canonical(package["name"])
        for package in editable
        if package.get("editable_project_location")
        and Path(package["editable_project_location"]).is_relative_to(repository)
    }
    # Older pip versions omit editable_project_location. Read project metadata too.
    for pattern in ("*.egg-info/PKG-INFO", "src/*.egg-info/PKG-INFO"):
        for path in repository.glob(pattern):
            name = email.parser.Parser().parsestr(path.read_text()).get("Name")
            if name:
                local.add(canonical(name))
    pyproject = repository / "pyproject.toml"
    if pyproject.is_file():
        name = tomllib.loads(pyproject.read_text()).get("project", {}).get("name")
        if name:
            local.add(canonical(name))
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.read(repository / "setup.cfg")
    if config.has_option("metadata", "name"):
        local.add(canonical(config.get("metadata", "name")))
    records = {}
    for path in (prefix / "conda-meta").glob("*.json"):
        record = json.loads(path.read_text())
        records[record["name"]] = {
            key: record.get(key)
            for key in ("name", "version", "build", "subdir", "url")
        }
    return {
        "architecture": platform.machine(),
        "python": output(
            python, "-c", "import platform; print(platform.python_version())"
        ),
        "environment": json.loads(
            output(
                "/opt/miniconda3/bin/conda", "env", "export", "-n", "testbed", "--json"
            )
        ),
        "python_distributions": {
            canonical(package["name"]): package["version"] for package in packages
        },
        "local_distributions": sorted(local),
        "conda_records": records,
        "base_commit": output("git", "-C", str(repository), "rev-parse", "HEAD^"),
        "git_remotes": output("git", "-C", str(repository), "remote").splitlines(),
    }


if __name__ == "__main__":
    print(json.dumps(inspect(), indent=2, sort_keys=True))
