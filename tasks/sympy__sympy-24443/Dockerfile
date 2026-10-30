# syntax=docker/dockerfile:1
FROM --platform=linux/arm64 ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

RUN apt update && apt install -y \
wget \
git \
build-essential \
libffi-dev \
libtiff-dev \
python3 \
python3-pip \
python-is-python3 \
jq \
curl \
ca-certificates \
bzip2 \
locales \
locales-all \
tzdata \
&& rm -rf /var/lib/apt/lists/*

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

curl -fSL --retry 3 \
    "https://${ARTIFACTORY_HOST}/artifactory/conda-forge/linux-aarch64/micromamba-2.1.0-0.tar.bz2" \
    -o /tmp/swebench-micromamba/micromamba.tar.bz2
tar -xjf /tmp/swebench-micromamba/micromamba.tar.bz2 \
    -C /tmp/swebench-micromamba bin/micromamba
/tmp/swebench-micromamba/bin/micromamba \
    --rc-file /etc/conda/condarc create -y \
    -p /opt/miniconda3 \
    --override-channels -c conda-forge \
    mamba \
    conda
rm -rf /tmp/swebench-micromamba
BOOTSTRAP_CONDA

# Add conda to PATH
ENV PATH=/opt/miniconda3/bin:$PATH
# Add conda to shell startup scripts like .bashrc (DO NOT REMOVE THIS)
RUN conda init --all

RUN adduser --disabled-password --gecos 'dog' nonroot

RUN <<EOF_8f1a24b92db1
#!/bin/bash
set -euxo pipefail
source /opt/miniconda3/bin/activate
cat > /root/environment.yml <<'EOF_c552dbf7567a'
name: testbed
channels:
  - conda-forge
dependencies:
  - _openmp_mutex=4.5=20_gnu
  - bzip2=1.0.8=h68df207_7
  - ca-certificates=2024.8.30=hcefe29a_0
  - flake8=7.1.1=pyhd8ed1ab_1
  - ld_impl_linux-aarch64=2.40=h9fc2d93_7
  - libffi=3.4.6=he21f813_1
  - libgcc-ng=13.3.0=he9431aa_2
  - libgcc=13.3.0=he277a41_2
  - libgomp=13.3.0=he277a41_2
  - liblzma-devel=5.6.3=h86ecc28_1
  - liblzma=5.6.3=h86ecc28_1
  - libnsl=2.0.1=h86ecc28_1
  - libsqlite=3.46.1=hc4a20ef_0
  - libstdcxx-ng=13.3.0=hf1166c9_2
  - libstdcxx=13.3.0=h3f4de04_2
  - libuuid=2.38.1=hb4cce97_0
  - libxcrypt=4.4.36=h31becfc_1
  - libzlib=1.3.1=h86ecc28_2
  - mccabe=0.7.0=pyhd8ed1ab_1
  - mpmath=1.3.0=pyhd8ed1ab_1
  - ncurses=6.5=ha32ae93_3
  - openssl=3.3.2=h86ecc28_0
  - pip=24.2=pyh8b19718_1
  - pycodestyle=2.12.1=pyhd8ed1ab_1
  - pyflakes=3.2.0=pyhd8ed1ab_1
  - python=3.9.20=h4a649e4_1_cpython
  - readline=8.2=h8382b9d_2
  - setuptools=75.1.0=pyhd8ed1ab_0
  - sqlite=3.46.1=h578a6b9_0
  - tk=8.6.13=noxft_h561c983_103
  - tzdata=2024b=hc8b5060_0
  - wheel=0.44.0=pyhd8ed1ab_0
  - xz-gpl-tools=5.6.3=h2dbfc1b_1
  - xz-tools=5.6.3=h86ecc28_1
  - xz=5.6.3=h2dbfc1b_1
  - zlib=1.3.1=h86ecc28_2
  - pip:
      - flake8-comprehensions==3.15.0
EOF_c552dbf7567a
conda env create --file /root/environment.yml
EOF_8f1a24b92db1

RUN echo "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed" > /root/.bashrc

RUN <<EOF_d75520b10fd3
#!/bin/bash
set -euxo pipefail
git clone -o origin --single-branch https://github.com/sympy/sympy /testbed
cd /testbed
git reset --hard 809c53c077485ca48a206cee78340389cb83b7f1
git remote remove origin
TARGET_TIMESTAMP=$(git show -s --format=%ci 809c53c077485ca48a206cee78340389cb83b7f1)
TARGET_EPOCH=$(git show -s --format=%ct 809c53c077485ca48a206cee78340389cb83b7f1)
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
python -m pip install -e .

# Configure git
git config --global user.email setup@swebench.com
git config --global user.name SWE-bench
git commit --allow-empty -am SWE-bench
EOF_d75520b10fd3

WORKDIR /testbed/
