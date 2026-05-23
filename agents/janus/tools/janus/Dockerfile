# janus agent — wraps janus-ga (Apache-2.0) for SELFIES-based de novo molecule generation.
# Wrapper code in /app/ is MIT (governed by repo-level LICENSE). Upstream attribution lives
# in /app/THIRD_PARTY_NOTICES.md and the bundled janus-ga LICENSE inside the Python wheel.

FROM mcr.microsoft.com/azurelinux/base/python:3.12

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV TOKENIZERS_PARALLELISM=false

# Shared base layer — kept byte-identical with other Azure Linux agents for layer cache reuse.
RUN tdnf -y update && \
    tdnf -y install ca-certificates && \
    update-ca-trust && \
    tdnf clean all

# Common scientific Python packages — shared layer across many Discovery agents.
RUN pip3 install --no-cache-dir \
    matplotlib==3.8.2 \
    numpy==1.26.4 \
    pandas==2.1.4 \
    pyyaml==6.0.1 \
    requests==2.32.3 \
    scipy==1.11.4 \
    seaborn==0.13.2

# rdkit ships as a manylinux wheel — no compilation needed.
RUN pip3 install --no-cache-dir rdkit==2024.3.5

# CPU-only PyTorch from the official CPU index (avoids 2GB CUDA payload).
# torch is a hard dep of janus-ga (used internally for the DNN classifier on the exploit branch).
RUN pip3 install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
    torch==2.2.2

# JANUS GA + pinned SELFIES (janus-ga 1.0.3 hard-pins selfies==1.0.3).
RUN pip3 install --no-cache-dir \
    selfies==1.0.3 \
    janus-ga==1.0.3

# Working directories.
RUN mkdir -p /input /output /workdir /tmp/matplotlib && \
    chmod 755 /input /output /workdir

# App code (utilities + entry point).
COPY janus_utils.py /app/janus_utils.py
COPY THIRD_PARTY_NOTICES.md /app/THIRD_PARTY_NOTICES.md

# FIX 1: Patch upstream janus-ga to add iteration caps on exploration/exploitation
# while loops. Without this, strict custom_filters cause infinite loops.
COPY patch_janus_loops.py /app/patch_janus_loops.py
RUN python3 /app/patch_janus_loops.py && rm /app/patch_janus_loops.py

# Make /app importable from any cwd.
ENV PYTHONPATH=/app:${PYTHONPATH}

WORKDIR /workdir

CMD ["/bin/bash"]
