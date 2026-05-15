FROM mcr.microsoft.com/azurelinux/base/core:3.0 AS mpi-builder

# Install build dependencies including kernel headers
RUN tdnf -y update && \
    tdnf -y install openmpi-devel make glibc-devel kernel-headers && \
    tdnf clean all

# Copy source code
COPY src/ /src
WORKDIR /src

# Build the MPI application
RUN bash -c 'source /etc/profile.d/modules.sh && module load mpi/openmpi-x86_64 && make'

# Runtime stage
FROM mcr.microsoft.com/azurelinux/base/core:3.0

# Install MPI runtime and networking tools (TCP/Ethernet only)
RUN tdnf -y update && \
    tdnf -y install openmpi hostname iproute procps && \
    tdnf clean all

# Copy the compiled binary from builder stage
COPY --from=mpi-builder /src/master_worker /root/master_worker

# Configure MPI module to load automatically
RUN echo 'source /etc/profile.d/modules.sh' >> /etc/bash.bashrc && \
    echo 'module load mpi/openmpi-x86_64' >> /etc/bash.bashrc

# Set working directory
WORKDIR /root

# Make the binary executable
RUN chmod +x /root/master_worker

# For MPI orchestration, keep container running
# The actual execution will be done by mpirun command
CMD ["/bin/bash", "-c", "tail -f /dev/null"]
