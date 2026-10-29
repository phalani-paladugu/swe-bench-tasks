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

RUN <<EOF_f6e1c4d70c34
#!/bin/bash
set -euxo pipefail
source /opt/miniconda3/bin/activate
cat > /root/environment.yml <<'EOF_559e331f90d1'
name: testbed
channels:
- conda-forge
dependencies:
- _openmp_mutex=4.5=20_gnu
- ca-certificates=2024.8.30=hcefe29a_0
- certifi=2021.5.30=py36h704843e_0
- ld_impl_linux-aarch64=2.40=h9fc2d93_7
- libffi=3.3=h884eca8_2
- libgcc-ng=12.1.0=h3242a24_17
- libgomp=12.1.0=h3242a24_17
- libsqlite=3.45.3=h194ca79_0
- libstdcxx-ng=12.1.0=hd01590b_17
- libzlib=1.2.13=h68df207_6
- ncurses=6.4.20240210=h0425590_0
- openssl=1.1.1w=h31becfc_0
- pip=21.2.2=pyhd8ed1ab_0
- python=3.6.13=h468538b_0_cpython
- python_abi=3.6=2_cp36m
- readline=8.2=h8fc344f_1
- sqlite=3.45.3=h3b3482f_0
- tk=8.6.13=h194ca79_0
- wheel=0.37.1=pyhd8ed1ab_0
- xz=5.2.6=h9cdd2b7_0
- zlib=1.2.13=h68df207_6
EOF_559e331f90d1
conda env create --file /root/environment.yml
conda activate testbed
python -m pip install setuptools==38.2.4
cat > /root/requirements.txt <<'EOF_146107461d2e'
apipkg==2.1.1
async-generator==1.10
attrs==17.3.0
contextvars==2.4
coverage==6.2
cython==0.27.3
exceptiongroup==0.0.0a0
execnet==1.5.0
hypothesis==3.44.2
idna==3.10
immutables==0.19
jinja2==2.10
markupsafe==1.0
numpy==1.16.0
outcome==1.0.0
packaging==16.8
pluggy==0.6.0
psutil==5.4.2
py==1.11.0
pyerfa==1.7.0
pyparsing==3.1.4
pytest-arraydiff==0.1
pytest-astropy-header==0.1
pytest-astropy==0.2.1
pytest-cov==2.5.1
pytest-doctestplus==0.1.2
pytest-filter-subpackage==0.1
pytest-forked==0.2
pytest-mock==1.6.3
pytest-openfiles==0.2.0
pytest-remotedata==0.2.0
pytest-xdist==1.20.1
pytest==3.3.1
pyyaml==3.12
setuptools==38.2.4
six==1.16.0
sniffio==1.2.0
sortedcontainers==1.5.9
tomli==0.2.0
trio==0.8.0
typing-extensions==4.1.1
EOF_146107461d2e
python -m pip install -r /root/requirements.txt
EOF_f6e1c4d70c34

RUN echo "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed" > /root/.bashrc

RUN <<EOF_be4498193a2d
#!/bin/bash
set -euxo pipefail
git clone -o origin --single-branch https://github.com/astropy/astropy /testbed
cd /testbed
git reset --hard c76af9ed6bb89bfba45b9f5bc1e635188278e2fa
git remote remove origin
TARGET_TIMESTAMP=$(git show -s --format=%ci c76af9ed6bb89bfba45b9f5bc1e635188278e2fa)
TARGET_EPOCH=$(git show -s --format=%ct c76af9ed6bb89bfba45b9f5bc1e635188278e2fa)
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
python -m pip install -e .[test] --verbose

# Configure git
git config --global user.email setup@swebench.com
git config --global user.name SWE-bench
git commit --allow-empty -am SWE-bench
EOF_be4498193a2d

WORKDIR /testbed/
