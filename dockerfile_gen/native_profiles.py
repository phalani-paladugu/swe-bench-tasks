"""Validated native substitutions, scoped to Python and exact source versions."""

import re


# Validation results and representative tasks are recorded in ARM64.md.
# Each tuple is (x86 version, ARM version, reason).
# Match both Python and the source package version; never apply to arbitrary pins.
PROFILES = {
    "3.9.20": {
        "_openmp_mutex": (
            "5.1",
            "4.5",
            "conda-forge provides 4.5; 5.1 is unavailable.",
        ),
        "ca-certificates": (
            "2024.9.24",
            "2024.8.30",
            "The exact x86 bundle is unavailable; use the nearby earlier release.",
        ),
        "libffi": (
            "3.4.4",
            "3.4.6",
            "3.4.4 is unavailable; use the nearby newer 3.4.6 release.",
        ),
        "libgcc-ng": (
            "11.2.0",
            "13.3.0",
            "ARM Python requires libgcc >=13; use the earliest available split runtime.",
        ),
        "libgomp": (
            "11.2.0",
            "13.3.0",
            "Keep GCC runtimes aligned with libgcc 13.3.0 required by ARM Python.",
        ),
        "libstdcxx-ng": (
            "11.2.0",
            "13.3.0",
            "Keep the C++ runtime aligned with the selected GCC 13.3.0 runtime.",
        ),
        "ncurses": (
            "6.4",
            "6.5",
            "Minimum ncurses version required by the supported ARM Python builds.",
        ),
        "openssl": (
            "3.0.15",
            "3.3.2",
            "Minimum OpenSSL version required by the supported ARM Python builds.",
        ),
        "sqlite": (
            "3.45.3",
            "3.46.1",
            "Minimum SQLite version required by the supported ARM Python builds.",
        ),
        "tk": (
            "8.6.14",
            "8.6.13",
            "8.6.14 is unavailable; retain the 8.6 series with 8.6.13.",
        ),
        "xz": (
            "5.4.6",
            "5.6.3",
            "5.4.6 is unavailable; use the nearby newer release with the GCC 13 runtime.",
        ),
        "zlib": (
            "1.2.13",
            "1.3.1",
            "ARM Python requires libzlib >=1.3.1; keep zlib and libzlib aligned.",
        ),
    },
}

# Preserve the older runtime combination validated for ARM Python 3.6.13.
PROFILES["3.6.13"] = {
    **{
        name: PROFILES["3.9.20"][name]
        for name in ("_openmp_mutex", "ca-certificates", "tk")
    },
    "libgcc-ng": (
        "11.2.0",
        "12.1.0",
        "ARM OpenSSL/readline require GCC >=12; use the validated 12.1.0 runtime.",
    ),
    "libgomp": (
        "11.2.0",
        "12.1.0",
        "Keep libgomp matched to the selected GCC 12.1.0 runtime.",
    ),
    "libstdcxx-ng": (
        "11.2.0",
        "12.1.0",
        "Keep the C++ runtime aligned with the selected GCC 12.1.0 runtime.",
    ),
    "ncurses": (
        "6.4",
        "6.4.20240210",
        "Minimum ncurses version required by the selected ARM SQLite build.",
    ),
    "xz": (
        "5.4.6",
        "5.2.6",
        "5.4.6 is unavailable; use the validated 5.2.6 build with the GCC 12 runtime.",
    ),
}

# The mirror's Python 3.8.20 builds use the same native requirements as 3.9.20.
PROFILES["3.8.20"] = {**PROFILES["3.9.20"]}

PROFILES["3.9.21"] = {
    **PROFILES["3.9.20"],
    "ca-certificates": (
        "2024.11.26",
        "2024.12.14",
        "The exact x86 bundle is unavailable; use the nearby newer release.",
    ),
    "openssl": (
        "3.0.15",
        "3.4.0",
        "Minimum OpenSSL version required by the selected ARM Python 3.9.21 build.",
    ),
    "sqlite": (
        "3.45.3",
        "3.47.0",
        "Minimum SQLite version required by the selected ARM Python 3.9.21 build.",
    ),
}

# The mirror's Python 3.11.10 builds require the same runtime versions, plus libuuid.
PROFILES["3.11.10"] = {
    **PROFILES["3.9.20"],
    "libuuid": (
        "1.41.5",
        "2.38.1",
        "1.41.5 is unavailable; ARM Python 3.11.10 requires libuuid >=2.38.1.",
    ),
}


def exact_conda_versions(environment: dict) -> dict:
    if not isinstance(environment, dict) or not isinstance(
        environment.get("dependencies"), list
    ):
        raise ValueError("Environment YAML must contain a dependencies list")
    versions = {}
    for pin in environment["dependencies"]:
        if not isinstance(pin, str):
            continue
        match = re.fullmatch(
            r"([\w.-]+)={1,2}([\w.!+-]+)(?:=[\w.+-]+)?", pin.split("::")[-1]
        )
        if match:
            name = match[1].replace("ld_impl_linux-64", "ld_impl_linux-aarch64")
            versions[name] = match[2]
    return versions


def native_profile(reference: dict, environment: dict | None = None) -> dict:
    source = exact_conda_versions(reference)
    effective = exact_conda_versions(environment) if environment is not None else source
    python = effective.get("python")
    return {
        name: {"version": arm, "reason": f"Python {python} profile: {reason}"}
        for name, (x86, arm, reason) in PROFILES.get(python, {}).items()
        if source.get(name) == x86
    }
