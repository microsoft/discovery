# Runtime-only ESI/OpenCFD image
FROM opencfd/openfoam-run:2512

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/matplotlib

# Source OpenFOAM env during build so RUN commands can use OF tools
ENV BASH_ENV=/usr/lib/openfoam/openfoam2512/etc/bashrc
SHELL ["/bin/bash", "-c"]

# System update + Python (image is Ubuntu 24.04 based)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv && \
    apt-get upgrade -y && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Common scientific Python packages
RUN pip3 install --no-cache-dir --break-system-packages \
    numpy==1.26.4 \
    scipy==1.13.1 \
    pandas==2.2.2 \
    matplotlib==3.9.0

# Thread control
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1

# Working directories
RUN mkdir -p /workdir /input /output /tmp/openfoam_scratch /app

# === CAPTURE OpenFOAM environment as a flat env file ===
# The OpenFOAM bashrc works during build but causes pop_var_context errors
# at runtime on bash 5.2+. Snapshot the env vars now; source the snapshot at runtime.
COPY capture_env.py /tmp/capture_env.py
RUN python3 /tmp/capture_env.py && rm /tmp/capture_env.py

# === CLEAR BASH_ENV for runtime ===
ENV BASH_ENV=""

# Copy utilities, entrypoint, and runner
COPY openfoam_utils.py /app/openfoam_utils.py
COPY run.py /app/run.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
ENV PYTHONPATH=/app

# Entrypoint loads the pre-captured env snapshot, then runs the command
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "-u", "/app/run.py"]
