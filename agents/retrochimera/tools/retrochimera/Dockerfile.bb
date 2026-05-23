# eMolecules building blocks image -- rebuild when the eMolecules URL rotates.
# Produces /app/data/building_blocks.smi (canonicalized, one SMILES per line).
#
# Build:
#   az acr build -r <acr-name> -t retrochimera-bb:2026-04 \
#     -f Dockerfile.bb .
#
# Override the URL at build time if eMolecules rotates the date slug:
#   --build-arg BUILDING_BLOCKS_URL=https://downloads.emolecules.com/orderbb/<date>/parent.smi.gz

FROM condaforge/mambaforge:24.3.0-0

# Minimal conda env with just RDKit for SMILES canonicalization.
# Pin to the same RDKit version that the runtime deps image ends up with
# (graphviz install upgrades RDKit from 2023.09.6 to 2024.09.6).
RUN mamba create -n rdkit python=3.9 "rdkit=2024.09.6" -y -c conda-forge && \
    mamba clean -afy

SHELL ["mamba", "run", "-n", "rdkit", "/bin/bash", "-c"]

RUN mkdir -p /app/data
COPY building_blocks.smi /app/data/building_blocks.smi

ARG BUILDING_BLOCKS_URL="https://downloads.emolecules.com/orderbb/2026-04-01/parent.smi.gz"
COPY prepare_building_blocks.py /tmp/prepare_building_blocks.py
RUN python /tmp/prepare_building_blocks.py --url "$BUILDING_BLOCKS_URL" && \
    rm /tmp/prepare_building_blocks.py
