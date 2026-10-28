# syntax=docker/dockerfile:1
FROM --platform=linux/arm64 ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

RUN apt update && apt install -y wget git build-essential libffi-dev libtiff-dev python3 python3-pip python-is-python3 jq curl ca-certificates bzip2 locales locales-all tzdata && rm -rf /var/lib/apt/lists/*

# Install Conda from the internal mirror.
ARG ARTIFACTORY_HOST=us-west-2.artifactory.aws.arm.com
ENV CONDARC=/etc/conda/condarc
RUN <<'BOOTSTRAP_CONDA'
set -eu
mkdir -p /etc/conda /tmp/swebench-micromamba
cat > /etc/conda/condarc <<CONDARC_CONFIG
channel_alias: https://${ARTIFACTORY_HOST}/artifactory/api/conda/
default_channels:
  - conda-forge
channels:
  - defaults
CONDARC_CONFIG
curl -fSL --retry 3 "https://${ARTIFACTORY_HOST}/artifactory/conda-forge/linux-aarch64/micromamba-2.1.0-0.tar.bz2" -o /tmp/swebench-micromamba/micromamba.tar.bz2
tar -xjf /tmp/swebench-micromamba/micromamba.tar.bz2 -C /tmp/swebench-micromamba bin/micromamba
/tmp/swebench-micromamba/bin/micromamba --rc-file /etc/conda/condarc create -y -p /opt/miniconda3 --override-channels -c conda-forge mamba conda
rm -rf /tmp/swebench-micromamba
BOOTSTRAP_CONDA
ENV PATH=/opt/miniconda3/bin:$PATH
RUN conda init --all
RUN adduser --disabled-password --gecos 'dog' nonroot

RUN <<EOF_8c64538e3e93
#!/bin/bash
set -euxo pipefail
source /opt/miniconda3/bin/activate
cat > /root/environment.yml <<'EOF_c8ddb2aa5435'
name: testbed
channels:
- conda-forge
dependencies:
- _openmp_mutex=4.5=20_gnu
- bzip2=1.0.8=h4777abc_10
- ca-certificates=2026.10.23=hbd8a1cb_0
- ld_impl_linux-aarch64=2.46.1=default_h1979696_103
- libexpat=2.9.0=h4154aff_0
- libffi=3.7.0=hdaad0be_1
- libgcc=16.2.0=h205dda4_7
- libgomp=16.2.0=h8acb6b2_7
- liblzma=5.8.3=he30d5cf_1
- libnsl=2.0.1=h86ecc28_1
- libsqlite=3.54.1=hd26f1b6_101
- libuuid=2.42.4=hd6fdeab_0
- libxcrypt=4.4.38=h80f16a2_0
- libzlib=1.3.2=hdc9db2a_3
- ncurses=6.6=h2b6f883_1
- openssl=3.6.5=he6ad1d5_0
- pip=25.2=pyh8b19718_0
- python=3.9.23=h0819846_0_cpython
- readline=8.3=ha7194a6_1
- tk=8.6.13=noxft_hf03c496_4
- tzdata=2026e=h5d301ff_0
- wheel=0.45.1=pyhd8ed1ab_1
- zstd=1.5.7=h9d15635_7
- pip:
  - attrs==23.1.0
  - coverage==7.10.7
  - exceptiongroup==1.1.3
  - execnet==2.0.2
  - hypothesis==6.82.6
  - iniconfig==2.0.0
  - numpy==1.25.2
  - packaging==23.1
  - pluggy==1.3.0
  - psutil==5.9.5
  - pyerfa==2.0.0.3
  - pytest==7.4.0
  - pytest-arraydiff==0.5.0
  - pytest-astropy==0.10.0
  - pytest-astropy-header==0.2.2
  - pytest-cov==4.1.0
  - pytest-doctestplus==1.0.0
  - pytest-filter-subpackage==0.1.2
  - pytest-mock==3.11.1
  - pytest-openfiles==0.5.0
  - pytest-remotedata==0.4.0
  - pytest-xdist==3.3.1
  - pyyaml==6.0.1
  - setuptools==68.0.0
  - sortedcontainers==2.4.0
  - tomli==2.0.1
EOF_c8ddb2aa5435
conda env create --file /root/environment.yml
EOF_8c64538e3e93

RUN echo "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed" > /root/.bashrc

RUN <<EOF_2bb07ccbdce2
#!/bin/bash
set -euxo pipefail
git clone -o origin --single-branch https://github.com/astropy/astropy /testbed
cd /testbed
git reset --hard 6ed769d58d89380ebaa1ef52b300691eefda8928
git remote remove origin
TARGET_TIMESTAMP=$(git show -s --format=%ci 6ed769d58d89380ebaa1ef52b300691eefda8928)
TARGET_EPOCH=$(git show -s --format=%ct 6ed769d58d89380ebaa1ef52b300691eefda8928)
for tag in $(git tag -l); do TAG_EPOCH=$(git log -1 --format=%ct "$tag" 2>/dev/null || echo 0); if [ "${TAG_EPOCH:-0}" -gt "$TARGET_EPOCH" ]; then git tag -d "$tag" >/dev/null 2>&1 || true; fi; done
git branch | grep -v '^\*' | xargs -r git branch -D || true
git reflog expire --expire=now --all
git gc --prune=now --aggressive
AFTER_TIMESTAMP=$(date -d "$TARGET_TIMESTAMP + 1 second" '+%Y-%m-%d %H:%M:%S')
COMMIT_COUNT=$(git log --oneline --all --since="$AFTER_TIMESTAMP" | wc -l)
[ "$COMMIT_COUNT" -eq 0 ] || exit 1
chmod -R 777 /testbed
cd - || true
source /opt/miniconda3/bin/activate
conda activate testbed
echo "Current environment: $CONDA_DEFAULT_ENV"
cd /testbed
sed -i 's/requires = \["setuptools",/requires = \["setuptools==68.0.0",/' pyproject.toml
python -m pip install -e .[test] --verbose

# Configure git
git config --global user.email setup@swebench.com
git config --global user.name SWE-bench
git commit --allow-empty -am SWE-bench
EOF_2bb07ccbdce2

WORKDIR /testbed/
