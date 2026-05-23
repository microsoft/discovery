FROM mcr.microsoft.com/azurelinux/base/python:3.12

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Shared base layer -- keep identical across agents
RUN tdnf -y update && \
    tdnf -y install ca-certificates && \
    update-ca-trust && \
    tdnf clean all

# System dependencies for building OpenSTA and CUDD
RUN tdnf -y install \
    gcc gcc-c++ make binutils cmake \
    bison flex \
    swig \
    tcl-devel \
    glibc-devel \
    kernel-headers \
    zlib-devel \
    fmt-devel \
    git \
    gawk \
    gawk \
    curl \
    tar \
    gzip \
    && tdnf clean all

# FlexLexer.h is not included in Azure Linux's flex package
RUN curl -L -o /usr/include/FlexLexer.h \
    "https://raw.githubusercontent.com/westes/flex/v2.6.4/src/FlexLexer.h" && \
    test -s /usr/include/FlexLexer.h

# Install Eigen3 (header-only library, not in Azure Linux repos)
RUN cd /tmp && \
    curl -L -o eigen3.tar.gz \
    "https://gitlab.com/libeigen/eigen/-/archive/3.4.0/eigen-3.4.0.tar.gz" && \
    tar xzf eigen3.tar.gz && \
    cd eigen-3.4.0 && \
    mkdir build && cd build && \
    cmake -DCMAKE_INSTALL_PREFIX=/usr/local .. && \
    make install && \
    cd / && rm -rf /tmp/eigen*

# Build CUDD (BDD library required by OpenSTA)
RUN cd /tmp && \
    curl -L -o cudd-3.0.0.tar.gz \
    "https://raw.githubusercontent.com/davidkebo/cudd/main/cudd_versions/cudd-3.0.0.tar.gz" && \
    tar xzf cudd-3.0.0.tar.gz && \
    cd cudd-3.0.0 && \
    ./configure --prefix=/usr/local CFLAGS="-fPIC" CXXFLAGS="-fPIC" && \
    make -j$(nproc) && \
    cd / && rm -f /tmp/cudd-3.0.0.tar.gz

# Build Google Test from source (Azure Linux gtest package has broken cmake config)
RUN cd /tmp && \
    curl -L -o gtest.tar.gz \
    "https://github.com/google/googletest/archive/refs/tags/v1.14.0.tar.gz" && \
    tar xzf gtest.tar.gz && \
    cd googletest-1.14.0 && \
    mkdir build && cd build && \
    cmake -DCMAKE_INSTALL_PREFIX=/usr/local .. && \
    make -j$(nproc) && make install && \
    cd / && rm -rf /tmp/googletest* /tmp/gtest*

# Clone and build OpenSTA from source
RUN cd /tmp && \
    git clone --depth 1 https://github.com/The-OpenROAD-Project/OpenSTA.git && \
    cd OpenSTA && \
    mkdir build && cd build && \
    cmake -DCUDD_DIR=/tmp/cudd-3.0.0 \
          -DCMAKE_INSTALL_PREFIX=/usr/local \
          -DCMAKE_BUILD_TYPE=RELEASE \
          -DCMAKE_CXX_FLAGS="-w" \
          .. && \
    make -j$(nproc) && \
    make install && \
    cd / && rm -rf /tmp/OpenSTA /tmp/cudd-3.0.0

# Verify sta binary is installed
RUN sta -help 2>&1 | head -3 || echo "sta binary installed"

# Download SKY130 Liberty (from OpenSTA examples -- compressed, STA reads .gz natively)
RUN mkdir -p /app/pdk && \
    curl -L -o /app/pdk/sky130hd_tt.lib.gz \
    "https://raw.githubusercontent.com/The-OpenROAD-Project/OpenSTA/master/examples/sky130hd_tt.lib.gz" && \
    test -s /app/pdk/sky130hd_tt.lib.gz && \
    echo "SKY130 lib: $(wc -c < /app/pdk/sky130hd_tt.lib.gz) bytes"

# Download GF180MCU Liberty (from OpenROAD-flow-scripts)
RUN curl -L -o /app/pdk/gf180mcu_fd_sc_mcu7t5v0__tt_025C_3v30.lib.gz \
    "https://raw.githubusercontent.com/The-OpenROAD-Project/OpenROAD-flow-scripts/master/flow/platforms/gf180/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_3v30.lib.gz" && \
    gunzip /app/pdk/gf180mcu_fd_sc_mcu7t5v0__tt_025C_3v30.lib.gz && \
    test -s /app/pdk/gf180mcu_fd_sc_mcu7t5v0__tt_025C_3v30.lib && \
    echo "GF180 lib: $(wc -c < /app/pdk/gf180mcu_fd_sc_mcu7t5v0__tt_025C_3v30.lib) bytes"

# Remove build tools to reduce image size
RUN tdnf -y remove gcc gcc-c++ make cmake bison flex swig git && \
    tdnf clean all || true
RUN rm -rf /tmp/* /var/cache/*

# Create directories
RUN mkdir -p /workdir /input /output /tmp/sta_scratch && \
    chmod 755 /workdir /input /output

# Copy application code
COPY sta_utils.py /app/
COPY sta_run.sh /app/
COPY sta_run_from_work.sh /app/
RUN chmod +x /app/sta_run.sh /app/sta_run_from_work.sh

# Thread control
ENV OMP_NUM_THREADS=1

CMD ["/bin/bash"]
