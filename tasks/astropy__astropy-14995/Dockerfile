
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

RUN <<EOF_9e033ead4bf3
#!/bin/bash
set -euxo pipefail
source /opt/miniconda3/bin/activate
cat > /root/environment.yml <<'EOF_326389ef76a5'
name: testbed
channels:
  - conda-forge
dependencies:
  - _openmp_mutex=4.5=20_gnu
  - bzip2=1.0.8=h68df207_7
  - ca-certificates=2024.8.30=hcefe29a_0
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
  - ncurses=6.5=ha32ae93_3
  - openssl=3.3.2=h86ecc28_0
  - pip=24.2=pyh8b19718_1
  - python=3.9.20=h4a649e4_1_cpython
  - readline=8.2=h8382b9d_2
  - sqlite=3.46.1=h578a6b9_0
  - tk=8.6.13=noxft_h561c983_103
  - tzdata=2024b=hc8b5060_0
  - wheel=0.44.0=pyhd8ed1ab_0
  - xz-gpl-tools=5.6.3=h2dbfc1b_1
  - xz-tools=5.6.3=h86ecc28_1
  - xz=5.6.3=h2dbfc1b_1
  - zlib=1.3.1=h86ecc28_2
  - pip:
      - attrs==23.1.0
      - coverage==7.6.2
      - exceptiongroup==1.1.3
      - execnet==2.0.2
      - hypothesis==6.82.6
      - iniconfig==2.0.0
      - numpy==1.25.2
      - packaging==23.1
      - pluggy==1.3.0
      - psutil==5.9.5
      - pyerfa==2.0.0.3
      - pytest-arraydiff==0.5.0
      - pytest-astropy-header==0.2.2
      - pytest-astropy==0.10.0
      - pytest-cov==4.1.0
      - pytest-doctestplus==1.0.0
      - pytest-filter-subpackage==0.1.2
      - pytest-mock==3.11.1
      - pytest-openfiles==0.5.0
      - pytest-remotedata==0.4.0
      - pytest-xdist==3.3.1
      - pytest==7.4.0
      - pyyaml==6.0.1
      - setuptools==68.0.0
      - sortedcontainers==2.4.0
      - tomli==2.0.1
EOF_326389ef76a5
conda env create --file /root/environment.yml
EOF_9e033ead4bf3

RUN echo "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed" > /root/.bashrc

RUN <<EOF_15916c08c458
#!/bin/bash
set -euxo pipefail
git clone -o origin --single-branch https://github.com/astropy/astropy /testbed
cd /testbed
git reset --hard b16c7d12ccbc7b2d20364b89fb44285bcbfede54
git remote remove origin
TARGET_TIMESTAMP=$(git show -s --format=%ci b16c7d12ccbc7b2d20364b89fb44285bcbfede54)
TARGET_EPOCH=$(git show -s --format=%ct b16c7d12ccbc7b2d20364b89fb44285bcbfede54)
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
EOF_15916c08c458

WORKDIR /testbed/
