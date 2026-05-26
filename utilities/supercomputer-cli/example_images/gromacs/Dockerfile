# Multi-stage Dockerfile for GROMACS 2025.3 with CUDA support
# Builder stage: compile GROMACS with CUDA
FROM nvidia/cuda:13.0.2-devel-ubuntu24.04 AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    wget \
    ca-certificates \
    libfftw3-dev \
    libhwloc-dev \
    libxml2-dev \
    libopenblas-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set GROMACS version
ENV GROMACS_VERSION=2025.3

# Download and extract GROMACS source
WORKDIR /tmp
RUN wget https://ftp.gromacs.org/gromacs/gromacs-${GROMACS_VERSION}.tar.gz && \
    tar xfz gromacs-${GROMACS_VERSION}.tar.gz && \
    rm gromacs-${GROMACS_VERSION}.tar.gz

# Build GROMACS with CUDA support
WORKDIR /tmp/gromacs-${GROMACS_VERSION}/build
RUN cmake .. \
    -DCMAKE_INSTALL_PREFIX=/opt/gromacs \
    -DGMX_BUILD_OWN_FFTW=OFF \
    -DGMX_GPU=CUDA \
    -DGMX_CUDA_TARGET_SM="80;86;89;90" \
    -DGMX_MPI=OFF \
    -DCMAKE_BUILD_TYPE=Release \
    -DGMX_SIMD=AVX2_256 \
    && make -j$(nproc) \
    && make install

# Download and install CHARMM36 force field for GROMACS
WORKDIR /tmp
RUN curl -o charmm36-jul2022.ff.tgz "https://mackerell.umaryland.edu/download.php?filename=CHARMM_ff_params_files/charmm36-jul2022.ff.tgz" \
    && tar -xzf charmm36-jul2022.ff.tgz \
    && mkdir -p /opt/gromacs/share/gromacs/top \
    && cp -r charmm36-jul2022.ff /opt/gromacs/share/gromacs/top/ \
    && rm -rf charmm36-jul2022.ff.tgz charmm36-jul2022.ff

# Runtime stage: CUDA runtime base with Python
FROM nvidia/cuda:13.0.2-runtime-ubuntu24.04

# Install Python and runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
    python3-pip \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy GROMACS installation from builder
COPY --from=builder /opt/gromacs /opt/gromacs

# Copy OpenBLAS and FFTW libraries from builder
COPY --from=builder /usr/lib/x86_64-linux-gnu/libopenblas.so.0 /usr/lib/x86_64-linux-gnu/
COPY --from=builder /usr/lib/x86_64-linux-gnu/libfftw3f.so.3 /usr/lib/x86_64-linux-gnu/
COPY --from=builder /usr/lib/x86_64-linux-gnu/libfftw3.so.3 /usr/lib/x86_64-linux-gnu/
COPY --from=builder /usr/lib/x86_64-linux-gnu/libgfortran.so.5 /usr/lib/x86_64-linux-gnu/
COPY --from=builder /usr/lib/x86_64-linux-gnu/libquadmath.so.0 /usr/lib/x86_64-linux-gnu/
COPY --from=builder /usr/lib/x86_64-linux-gnu/libgomp.so.1 /usr/lib/x86_64-linux-gnu/

# Set up library path
ENV LD_LIBRARY_PATH=/opt/gromacs/lib64:/usr/local/cuda/lib64:/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH}
ENV PATH=/opt/gromacs/bin:${PATH}
# # Ensure NVIDIA driver libraries can be found
# ENV NVIDIA_VISIBLE_DEVICES=all
# ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility

# Source GROMACS environment
RUN echo "source /opt/gromacs/bin/GMXRC" >> /etc/profile.d/gromacs.sh

# Create non-root user for running GROMACS (use different UID to avoid conflict)
RUN useradd -m -u 1001 -s /bin/bash gromacs

# Set up Python virtual environment and Jupyter kernel as root
WORKDIR /home/gromacs
RUN python3 -m venv gromacs_env \
    && /home/gromacs/gromacs_env/bin/pip install --upgrade pip \
    && /home/gromacs/gromacs_env/bin/pip install \
        ipykernel \
        matplotlib \
        numpy \
    && chown -R gromacs:gromacs /home/gromacs/gromacs_env

# Install Jupyter kernel as gromacs user
# USER gromacs
WORKDIR /home/gromacs
RUN /home/gromacs/gromacs_env/bin/python -m ipykernel install --user --name gromacs_env --display-name "GROMACS Tutorial"

# Copy tutorial notebook
COPY lysozyme_tutorial.ipynb /home/gromacs/
USER root
RUN chown gromacs:gromacs /home/gromacs/lysozyme_tutorial.ipynb

# Switch back to gromacs user
# USER gromacs
WORKDIR /home/gromacs

# Set up environment activation script
RUN echo '#!/bin/bash' > /home/gromacs/activate_env.sh \
    && echo 'source /opt/gromacs/bin/GMXRC' >> /home/gromacs/activate_env.sh \
    && echo 'source /home/gromacs/gromacs_env/bin/activate' >> /home/gromacs/activate_env.sh \
    && echo 'echo "GROMACS and Python environment activated!"' >> /home/gromacs/activate_env.sh \
    && echo 'echo "GROMACS version:"' >> /home/gromacs/activate_env.sh \
    && echo 'gmx --version | head -3' >> /home/gromacs/activate_env.sh \
    && echo 'echo "Python environment: $(which python)"' >> /home/gromacs/activate_env.sh \
    && echo 'echo "Jupyter kernels available:"' >> /home/gromacs/activate_env.sh \
    && echo 'jupyter kernelspec list | grep gromacs || echo "  No GROMACS kernel found"' >> /home/gromacs/activate_env.sh \
    && chmod +x /home/gromacs/activate_env.sh

# Add environment activation to bashrc
RUN echo 'alias activate_gromacs="source /home/gromacs/activate_env.sh"' >> /home/gromacs/.bashrc \
    && echo 'echo "Use '\''activate_gromacs'\'' to set up GROMACS and Python environment"' >> /home/gromacs/.bashrc

# Set default command to show setup instructions
CMD ["/bin/bash", "-c", "source /home/gromacs/activate_env.sh && echo 'Container ready! Use activate_gromacs or source activate_env.sh to set up environment.' && /bin/bash"]
