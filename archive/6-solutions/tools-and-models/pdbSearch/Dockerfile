# PDBSearch - Protein Data Bank search and analysis tool
FROM mcr.microsoft.com/azurelinux/base/python:3.12 AS base
WORKDIR /app

# Update system packages and install CA certificates for HTTPS connectivity
RUN tdnf -y update && \
    tdnf -y install ca-certificates && \
    update-ca-trust && \
    tdnf clean all

# Install Python dependencies
RUN pip3 install --no-cache-dir \
    matplotlib \
    pandas \
    requests \
    seaborn \
    rdkit

# Fix CVE-2025-64720, CVE-2025-65018, CVE-2025-66293, CVE-2025-64505,
# CVE-2025-64506, CVE-2026-22695, CVE-2026-22801 (libpng bundled in rdkit wheel)
# Three-step remediation: install system libpng, replace bundled .so, patch SBOM
RUN tdnf -y install libpng && \
    RDKIT_LIBS=/usr/lib/python3.12/site-packages/rdkit.libs && \
    rm -f "$RDKIT_LIBS"/libpng16-*.so* && \
    ln -s /usr/lib64/libpng16.so "$RDKIT_LIBS/libpng16-2bf8e833.so.16.34.0" && \
    sed -i '/libpng16-.*\.so/d' /usr/lib/python3.12/site-packages/rdkit-*.dist-info/RECORD && \
    python3 -c "import json,glob;exec(\"for p in glob.glob('/usr/lib/python3.12/site-packages/rdkit-*.dist-info/sboms/auditwheel.cdx.json'):\\n s=json.load(open(p))\\n s['components']=[c for c in s.get('components',[]) if 'libpng' not in c.get('name','').lower()]\\n json.dump(s,open(p,'w'),indent=2)\")" && \
    tdnf clean all

RUN ln -s /usr/bin/python3 /usr/bin/python

# Copy Python modules to /app
COPY app/ /app/

# Create working directories
RUN mkdir -p /input /output /workdir

WORKDIR /workdir

ENV PYTHONPATH="/app"
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/matplotlib

CMD ["/bin/bash"]
