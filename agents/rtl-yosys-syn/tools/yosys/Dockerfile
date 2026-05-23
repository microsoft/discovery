FROM mcr.microsoft.com/azurelinux/base/python:3.12

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Shared base layer -- keep identical across agents
RUN tdnf -y update && \
    tdnf -y install ca-certificates && \
    update-ca-trust && \
    tdnf clean all

# System dependencies for building Yosys
RUN tdnf -y install \
    gcc gcc-c++ make binutils \
    bison flex \
    pkg-config \
    tcl-devel \
    readline-devel \
    libffi-devel \
    glibc-devel \
    kernel-headers \
    zlib-devel \
    gawk \
    git \
    curl \
    tar \
    gzip \
    && tdnf clean all

# FlexLexer.h is not included in Azure Linux's flex package -- download it
RUN curl -L -o /usr/include/FlexLexer.h \
    "https://raw.githubusercontent.com/westes/flex/v2.6.4/src/FlexLexer.h" && \
    test -s /usr/include/FlexLexer.h

# Build and install Yosys from source
# Using official release tarball (includes ABC submodule)
RUN mkdir -p /tmp/yosys-build && cd /tmp/yosys-build && \
    curl -L -o yosys.tar.gz https://github.com/YosysHQ/yosys/releases/download/v0.65/yosys.tar.gz && \
    tar xzf yosys.tar.gz && \
    make config-gcc && \
    CXXFLAGS="-w" make -j$(nproc) PREFIX=/usr/local && \
    make install PREFIX=/usr/local && \
    cd / && rm -rf /tmp/yosys-build /tmp/*.tar.gz

# Install ABC (required by Yosys for technology mapping)
# ABC is bundled with Yosys build, verify it's available
RUN yosys -V && which yosys-abc || echo "ABC bundled with Yosys"

# Download SKY130 Liberty file from OpenROAD-flow-scripts (known working source)
RUN mkdir -p /app/pdk && \
    curl -L -o /app/pdk/sky130_fd_sc_hd__tt_025C_1v80.lib \
    "https://raw.githubusercontent.com/The-OpenROAD-Project/OpenROAD-flow-scripts/master/flow/platforms/sky130hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib" && \
    test -s /app/pdk/sky130_fd_sc_hd__tt_025C_1v80.lib && \
    echo "SKY130 lib: $(wc -c < /app/pdk/sky130_fd_sc_hd__tt_025C_1v80.lib) bytes"

# Download GF180MCU Liberty file (gzipped in repo)
RUN curl -L -o /app/pdk/gf180mcu_fd_sc_mcu7t5v0__tt_025C_3v30.lib.gz \
    "https://raw.githubusercontent.com/The-OpenROAD-Project/OpenROAD-flow-scripts/master/flow/platforms/gf180/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_3v30.lib.gz" && \
    gunzip /app/pdk/gf180mcu_fd_sc_mcu7t5v0__tt_025C_3v30.lib.gz && \
    test -s /app/pdk/gf180mcu_fd_sc_mcu7t5v0__tt_025C_3v30.lib && \
    echo "GF180 lib: $(wc -c < /app/pdk/gf180mcu_fd_sc_mcu7t5v0__tt_025C_3v30.lib) bytes"

# Remove build tools to reduce image size and CVE surface
RUN tdnf -y remove gcc gcc-c++ make bison flex git gawk && \
    tdnf clean all || true
RUN rm -rf /tmp/* /var/cache/*

# Create directories
RUN mkdir -p /workdir /input /output /tmp/yosys_scratch && \
    chmod 755 /workdir /input /output

# Copy application code
COPY yosys_utils.py /app/
COPY yosys_synth.sh /app/
COPY yosys_synth_from_work.sh /app/
RUN chmod +x /app/yosys_synth.sh /app/yosys_synth_from_work.sh

# Thread control
ENV OMP_NUM_THREADS=1

# No ENTRYPOINT, use CMD
CMD ["/bin/bash"]
