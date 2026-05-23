# Build Xyce 7.8 (serial) from source on Ubuntu 24.04 (noble).
# Multi-stage: builder compiles Trilinos + Xyce, runtime ships only the binaries.
#
# Security posture (validated 2026-05-19):
#   CRITICAL=0, HIGH=0 (Trivy scan, 154 OS pkgs)
#
# References:
#   Sandia Xyce Building Guide: https://xyce.sandia.gov/documentation-tutorials/building-guide/
#   Trilinos: https://github.com/trilinos/Trilinos
#
# Build notes (lessons learned):
#   - Trilinos MUST be built with -DTeuchos_ENABLE_COMPLEX=ON (AC/noise analysis)
#   - -DEpetraExt_BUILD_BLOCK_AND_INVERSE=ON is required
#   - -DTrilinos_ENABLE_TrilinosCouplings=ON is required (configure error otherwise)
#   - Use ACR --timeout 10800 when building (Trilinos+Xyce ~65-80 min on 2-vCPU ACR agent)

# ============================================================
# Stage 1: Builder
# ============================================================
FROM ubuntu:24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive
ENV TRILINOS_VERSION=trilinos-release-14-4-0
ENV XYCE_VERSION=Release-7.8.0

RUN apt-get update && \
    apt-get -y upgrade && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        cmake \
        make \
        g++ \
        gfortran \
        autoconf \
        automake \
        libtool \
        bison \
        flex \
        libfl-dev \
        libfftw3-dev \
        libsuitesparse-dev \
        libblas-dev \
        liblapack-dev \
        libopenblas-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone --depth 1 --branch ${TRILINOS_VERSION} https://github.com/trilinos/Trilinos.git trilinos
RUN mkdir -p /src/trilinos-build && cd /src/trilinos-build && \
    cmake \
        -DCMAKE_INSTALL_PREFIX=/opt/trilinos \
        -DCMAKE_BUILD_TYPE=RELEASE \
        -DCMAKE_CXX_FLAGS="-O3 -fPIC" \
        -DCMAKE_C_FLAGS="-O3 -fPIC" \
        -DCMAKE_Fortran_FLAGS="-O3 -fPIC" \
        -DTrilinos_ENABLE_NOX=ON \
        -DNOX_ENABLE_LOCA=ON \
        -DTrilinos_ENABLE_EpetraExt=ON \
        -DEpetraExt_BUILD_BTF=ON \
        -DEpetraExt_BUILD_EXPERIMENTAL=ON \
        -DEpetraExt_BUILD_GRAPH_REORDERINGS=ON \
        -DEpetraExt_BUILD_BLOCK_AND_INVERSE=ON \
        -DTrilinos_ENABLE_TrilinosCouplings=ON \
        -DTrilinos_ENABLE_Ifpack=ON \
        -DTrilinos_ENABLE_AztecOO=ON \
        -DTrilinos_ENABLE_Belos=ON \
        -DTrilinos_ENABLE_Teuchos=ON \
        -DTeuchos_ENABLE_COMPLEX=ON \
        -DTrilinos_ENABLE_Amesos=ON \
        -DAmesos_ENABLE_KLU=ON \
        -DTrilinos_ENABLE_Sacado=ON \
        -DTrilinos_ENABLE_Stokhos=ON \
        -DTrilinos_ENABLE_Kokkos=ON \
        -DTrilinos_ENABLE_Zoltan=ON \
        -DTrilinos_ENABLE_ALL_OPTIONAL_PACKAGES=OFF \
        -DTrilinos_ENABLE_CXX11=ON \
        -DTPL_ENABLE_AMD=ON \
        -DAMD_LIBRARY_DIRS="/usr/lib/x86_64-linux-gnu" \
        -DTPL_AMD_INCLUDE_DIRS="/usr/include/suitesparse" \
        -DTPL_ENABLE_BLAS=ON \
        -DTPL_ENABLE_LAPACK=ON \
        -DBUILD_SHARED_LIBS=ON \
        /src/trilinos && \
    make -j"$(nproc)" install && \
    rm -rf /src/trilinos /src/trilinos-build

RUN git clone --depth 1 --branch ${XYCE_VERSION} https://github.com/Xyce/Xyce.git /src/xyce && \
    cd /src/xyce && ./bootstrap
RUN mkdir -p /src/xyce-build && cd /src/xyce-build && \
    /src/xyce/configure \
        CXXFLAGS="-O3 -std=c++17" \
        ARCHDIR="/opt/trilinos" \
        --prefix=/opt/xyce \
        --enable-shared \
        --enable-stokhos \
        --enable-amesos \
        && \
    make -j"$(nproc)" && \
    make install && \
    rm -rf /src/xyce /src/xyce-build

# ============================================================
# Stage 2: Runtime
# ============================================================
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get -y upgrade && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        python3 \
        python3-pip \
        libfftw3-double3 \
        libsuitesparse-dev \
        libgfortran5 \
        libopenblas0 \
        liblapack3 \
        libgomp1 \
        libstdc++6 && \
    apt-get -y autoremove && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/trilinos /opt/trilinos
COPY --from=builder /opt/xyce /opt/xyce

ENV PATH="/opt/xyce/bin:${PATH}"
ENV LD_LIBRARY_PATH="/opt/xyce/lib:/opt/trilinos/lib:${LD_LIBRARY_PATH}"

RUN mkdir -p /app/pdk/sky130 /app/pdk/gf180mcu /workdir /input /output && \
    chmod 755 /workdir /input /output

# SKY130 transistor SPICE models — use mkghub/skywater130_fd_pr_models
# (Apache 2.0, last updated Sept 2025). This is a community repackaging of the
# upstream google/skywater-pdk explicitly cleaned for Ngspice/Xyce compatibility:
#   - HSPICE-only $Units annotations removed
#   - .lib <corner> blocks at root level
#   - corner-specific files in cells/ referenced via relative
#     sky130_fd_pr_models/cells/* paths from sky130.lib.spice
#
# Layout requirement: sky130.lib.spice contains relative .include paths like
# "sky130_fd_pr_models/cells/...". Those resolve relative to the dir of the
# entry .lib file. So we extract into /app/pdk/sky130/sky130_fd_pr_models/
# (note the explicit subdirectory name).
RUN cd /tmp && \
    curl -L -o sky130_models.tar.gz \
    "https://api.github.com/repos/mkghub/skywater130_fd_pr_models/tarball/master" && \
    mkdir -p /app/pdk/sky130/sky130_fd_pr_models && \
    tar xzf sky130_models.tar.gz -C /app/pdk/sky130/sky130_fd_pr_models --strip-components=1 && \
    rm -f /tmp/sky130_models.tar.gz && \
    echo "Rewriting relative .include paths to absolute..." && \
    find /app/pdk/sky130/sky130_fd_pr_models -type f \( -name "*.spice" -o -name "*.lib" \) \
        -exec sed -i 's|\.include[[:space:]]*"sky130_fd_pr_models/|.include "/app/pdk/sky130/sky130_fd_pr_models/|g' {} \; \
        -exec sed -i "s|\.include[[:space:]]*'sky130_fd_pr_models/|.include '/app/pdk/sky130/sky130_fd_pr_models/|g" {} \; && \
    echo "Creating empty stubs for sonos files (NVM models not used by standard CMOS)..." && \
    mkdir -p /app/pdk/sky130/sky130_fd_pr_models/sonos_p/begin_of_life \
             /app/pdk/sky130/sky130_fd_pr_models/sonos_e/begin_of_life && \
    : > /app/pdk/sky130/sky130_fd_pr_models/sonos_p/begin_of_life/mm.spice && \
    : > /app/pdk/sky130/sky130_fd_pr_models/sonos_e/begin_of_life/mm.spice && \
    echo "Fixing bare .endl (Xyce requires matching library name)..." && \
    sed -i 's|^\.endl\s*$|.endl tt|' /app/pdk/sky130/sky130_fd_pr_models/sky130_tt.lib.spice && \
    echo "SKY130 models installed:" && \
    ls /app/pdk/sky130/sky130_fd_pr_models/sky130_tt.lib.spice && \
    echo "Sample rewritten includes:" && \
    grep -m 3 '\.include' /app/pdk/sky130/sky130_fd_pr_models/sky130_tt.lib.spice

RUN curl -L -o /app/pdk/gf180mcu/sm141064.xyce \
    "https://raw.githubusercontent.com/efabless/globalfoundries-pdk-libs-gf180mcu_fd_pr/main/models/xyce/sm141064.xyce" && \
    curl -L -o /app/pdk/gf180mcu/design.xyce \
    "https://raw.githubusercontent.com/efabless/globalfoundries-pdk-libs-gf180mcu_fd_pr/main/models/xyce/design.xyce" && \
    curl -L -o /app/pdk/gf180mcu/sm141064_mim.xyce \
    "https://raw.githubusercontent.com/efabless/globalfoundries-pdk-libs-gf180mcu_fd_pr/main/models/xyce/sm141064_mim.xyce" && \
    curl -L -o /app/pdk/gf180mcu/smbb000149.xyce \
    "https://raw.githubusercontent.com/efabless/globalfoundries-pdk-libs-gf180mcu_fd_pr/main/models/xyce/smbb000149.xyce"

COPY xyce_utils.py /app/
COPY xyce_run.sh /app/
COPY xyce_run_from_work.sh /app/
RUN chmod +x /app/xyce_run.sh /app/xyce_run_from_work.sh

ENV PYTHONUNBUFFERED=1
ENV OMP_NUM_THREADS=1

CMD ["/bin/bash"]
