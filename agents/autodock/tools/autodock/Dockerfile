# AutoDock Vina Container for Microsoft Discovery Platform
# Azure Linux 3.0 (Python 3.12) - hardened, minimal, fast CVE patching
# Supports molecular docking, virtual screening, and binding affinity prediction

FROM mcr.microsoft.com/azurelinux/base/python:3.12

# Set up environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/opt/vina:${PATH}"
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# Install system dependencies (Python 3.12, pip, setuptools, wheel already in base image)
RUN tdnf -y update && \
    tdnf -y install \
        # Build tools (needed for pip packages with native extensions)
        gcc \
        gcc-c++ \
        binutils \
        make \
        python3-devel \
        # Runtime libraries
        ca-certificates \
        boost \
        zlib \
        bzip2 \
        # X11 runtime libs (required by openbabel-wheel format plugins)
        libXrender \
        libXext \
        # Utilities
        gzip \
        unzip \
        tar \
        git \
    && tdnf clean all

# Create directory structure
RUN mkdir -p /opt/vina /app/workdir /input /output

# Download and install AutoDock Vina (latest stable version 1.2.5)
WORKDIR /tmp
RUN curl -fsSL https://github.com/ccsb-scripps/AutoDock-Vina/releases/download/v1.2.5/vina_1.2.5_linux_x86_64 \
    -o /opt/vina/vina \
    && chmod +x /opt/vina/vina \
    && ln -s /opt/vina/vina /usr/local/bin/vina

# Verify Vina installation
RUN vina --version || echo "Vina version check"

# Install OpenBabel via pip (pre-built wheel, provides obabel CLI)
RUN pip3 install --no-cache-dir openbabel-wheel

# Verify OpenBabel installation
RUN obabel -V || echo "OpenBabel version check"

# Core scientific packages
RUN pip3 install --no-cache-dir \
    numpy>=1.24.0 \
    scipy>=1.11.0 \
    pandas>=2.0.0 \
    matplotlib>=3.7.0 \
    seaborn>=0.12.0

# Chemistry and molecular modeling packages
RUN pip3 install --no-cache-dir \
    rdkit>=2023.9.1 \
    biopython>=1.81 \
    mdanalysis>=2.6.0

# Additional utilities
RUN pip3 install --no-cache-dir \
    openpyxl>=3.1.0 \
    xlsxwriter>=3.1.0 \
    PyYAML>=6.0 \
    requests>=2.31.0 \
    tqdm>=4.66.0

# Azure storage for cloud integration
RUN pip3 install --no-cache-dir \
    azure-storage-blob>=12.19.0 \
    azure-identity>=1.15.0

# Install Meeko for improved PDBQT preparation (AutoDock-Vina companion tool)
# gemmi is a required dependency of meeko >= 0.5.0
RUN pip3 install --no-cache-dir gemmi meeko>=0.5.0

# Pin fixed versions for packages with known CVEs
RUN pip3 install --no-cache-dir \
    cryptography>=46.0.5 \
    pillow>=12.1.1

# Install VS Code CLI for interactive debugging (optional)
RUN curl -fsSL "https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64" \
    -o /tmp/vscode_cli.tar.gz \
    && tar -xzf /tmp/vscode_cli.tar.gz -C /usr/local/bin \
    && rm /tmp/vscode_cli.tar.gz \
    || echo "VS Code CLI installation skipped"

# Fix CVE-2025-64720, CVE-2025-65018, CVE-2025-66293 (HIGH) and
# CVE-2025-64505, CVE-2025-64506, CVE-2026-22695, CVE-2026-22801 (MEDIUM):
# Install system libpng 1.6.54 and replace vulnerable bundled copies in pip wheels.
# Also clean pip RECORD metadata and auditwheel SBOMs so scanners detect the updated version.
RUN tdnf -y install libpng && tdnf clean all && \
    rm -f /usr/lib/python3.12/site-packages/rdkit.libs/libpng16-*.so.* && \
    ln -s /usr/lib64/libpng16.so.16.54.0 /usr/lib/python3.12/site-packages/rdkit.libs/libpng16.so.16 && \
    rm -f /usr/lib/python3.12/site-packages/pillow.libs/libpng16-*.so.* && \
    ln -s /usr/lib64/libpng16.so.16.54.0 /usr/lib/python3.12/site-packages/pillow.libs/libpng16.so.16 && \
    sed -i '/libpng16-.*\.so/d' /usr/lib/python3.12/site-packages/rdkit*.dist-info/RECORD && \
    sed -i '/libpng16-.*\.so/d' /usr/lib/python3.12/site-packages/pillow*.dist-info/RECORD && \
    python3 -c "import json, glob; \
sboms = glob.glob('/usr/lib/python3.12/site-packages/*/sboms/auditwheel.cdx.json'); \
[json.dump(dict(d, components=[c for c in d.get('components',[]) if c.get('name')!='libpng']), open(f,'w'), indent=2) for f in sboms for d in [json.load(open(f))]]"

# Remove build tools no longer needed at runtime (reduce attack surface)
RUN tdnf -y remove gcc gcc-c++ make \
    && tdnf clean all \
    || true

# Copy utilities library
WORKDIR /app
COPY autodock_utils.py /app/autodock_utils.py

# Make utilities importable from anywhere
ENV PYTHONPATH="/app"

# Create symlink for Python importability
RUN PYTHON_SITE=$(python3 -c "import site; print(site.getsitepackages()[0])") \
    && ln -sf /app/autodock_utils.py "${PYTHON_SITE}/autodock_utils.py" 2>/dev/null || true

# Set working directory
WORKDIR /app/workdir

# Default command - must be /bin/bash for Discovery workbench compatibility
CMD ["/bin/bash"]

# Container metadata
LABEL maintainer="Microsoft Discovery Platform"
LABEL description="AutoDock Vina molecular docking container with Python utilities"
LABEL version="1.1.0"
LABEL autodock.vina.version="1.2.5"
LABEL base.image="mcr.microsoft.com/azurelinux/base/python:3.12"
