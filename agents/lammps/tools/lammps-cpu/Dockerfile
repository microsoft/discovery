# LAMMPS container using conda-forge prebuilt packages
# Includes: EXTRA-PAIR, EXTRA-FIX, MOLECULE, KSPACE, RIGID, MANYBODY, REAXFF, and many more
FROM continuumio/miniconda3:latest

USER root
ENV DEBIAN_FRONTEND=noninteractive

# Layer 1: System update + utilities (rarely changes)
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        coreutils && \
    rm -rf /var/lib/apt/lists/*

# Layer 2: LAMMPS core + MPI (slowest layer, rarely changes)
# The conda-forge build includes most popular packages:
# ASPHERE, BODY, CLASS2, COLLOID, COLVARS, DIPOLE, EXTRA-COMPUTE, EXTRA-DUMP,
# EXTRA-FIX, EXTRA-MOLECULE, EXTRA-PAIR, GRANULAR, KSPACE, MANYBODY, MC, MEAM,
# MISC, ML-IAP, ML-PACE, ML-SNAP, MOLECULE, OPT, OPENMP, PERI, PHONON, REAXFF,
# REPLICA, RIGID, SHOCK, SRD, VORONOI, and more
RUN conda install -y -c conda-forge \
        lammps \
        openmpi && \
    conda clean -afy

# Layer 3: Python scientific packages for self-sufficient workflows
# Core: numpy, scipy, matplotlib
# Trajectory: MDAnalysis (RDF, MSD, RMSD, atom selections)
# Structure: ASE (read/write CIF, PDB, XYZ, build crystals)
# Analysis: freud (order parameters, Voronoi), pandas (log parsing, data export)
# Data: h5py (large datasets), networkx (connectivity)
RUN conda install -y -c conda-forge \
        numpy \
        scipy \
        matplotlib \
        mdanalysis \
        ase \
        pandas \
        freud \
        h5py \
        networkx && \
    conda clean -afy

# Layer 3b: Upgrade pip packages with known CVEs
# --force-reinstall needed for jaraco.context and wheel to override conda-pinned versions
# Remove stale conda metadata so Trivy detects the pip-upgraded versions
RUN pip install --no-cache-dir --upgrade \
        cryptography>=46.0.5 \
        pillow>=12.1.1 \
        urllib3>=2.6.3 && \
    pip install --no-cache-dir --force-reinstall \
        "jaraco.context>=6.1.0" \
        wheel>=0.46.2 && \
    rm -f /opt/conda/conda-meta/jaraco.context-*.json \
          /opt/conda/conda-meta/wheel-*.json

# Layer 4: LAMMPS utilities library (lightweight, may change frequently)
COPY lammps_utils.py /usr/local/lib/lammps_utils.py
# Install to Python site-packages using shell glob (COPY doesn't support wildcards)
RUN cp /usr/local/lib/lammps_utils.py /opt/conda/lib/python3.*/site-packages/

# Layer 5: LAMMPS configuration (quick layer)
RUN ln -sf $(which lmp) /usr/local/bin/lmp && \
    ln -sf $(which lmp) /usr/local/bin/lmp_mpi && \
    ln -sf $(which lmp) /usr/local/bin/lmp_serial

ENV LAMMPS_POTENTIALS=/opt/conda/share/lammps/potentials

# Layer 6: VS Code CLI (optional tooling, quick layer)
RUN curl -Lk 'https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64' \
        --output /tmp/vscode_cli.tar.gz && \
    tar -xf /tmp/vscode_cli.tar.gz -C /usr/local/bin && \
    rm /tmp/vscode_cli.tar.gz && \
    chmod +x /usr/local/bin/code || true

WORKDIR /workdir

CMD ["/bin/bash"]
