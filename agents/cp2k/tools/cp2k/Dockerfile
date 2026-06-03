# ============================================================================
# CP2K Atomistic Simulation Docker Image for Discovery Platform (v19)
# ============================================================================
# CP2K built from SOURCE with DFT-D4 support enabled.
#
# The conda-forge CP2K package (2024.2) lacks D4 — it is not compiled with
# -D__DFTD4. This Dockerfile installs all dependencies (MPI, math libs,
# dftd4) via conda-forge for ABI consistency, then compiles only CP2K from
# source with CMake to enable D4.
#
# Build strategy:
#   Stage 1 (builder) — conda deps + CP2K source build with CMake
#   Stage 2 (runtime) — copy conda env with custom CP2K binaries
#
# Key design choices (see INSTALL.md, conda-forge feedstocks, CP2K CMakeLists):
#   - conda-forge compilers for ABI compat with conda math libs
#   - dftd4 from conda provides libdftd4.so; custom CMake shim bridges
#     pkg-config → CMake target (conda dftd4 is built with Meson, no CMake config)
#   - libxc package (not libxc-c) includes Fortran bindings (.mod + libxcf03)
#   - CP2K_USE_LIBINT2=OFF for now — libint2 Fortran bridge is not yet stable
#   - PKG_CONFIG_PATH explicitly set for pkg-config to find conda .pc files
#
# Build time: ~15-25 min with full parallelism
# ============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Builder — compile CP2K from source
# ---------------------------------------------------------------------------
FROM mambaorg/micromamba:1.5-jammy AS builder

USER root

ENV DEBIAN_FRONTEND=noninteractive
ENV MAMBA_ROOT_PREFIX=/opt/conda
ENV PATH="${MAMBA_ROOT_PREFIX}/bin:${PATH}"

# System tools only (NOT compilers — those come from conda for ABI compatibility)
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget git ca-certificates openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Create conda env with compilers + build tools + all CP2K dependencies.
# NOTE: Output redirected to log file; Unicode stripped on error display
#       to prevent Azure CLI log streaming crash (colorama cp1252 bug).
# IMPORTANT: Install 'libxc' (NOT 'libxc-c') to get Fortran bindings.
RUN micromamba create -n cp2kenv -c conda-forge --quiet -y \
        python=3.11 \
        cmake ninja pkg-config \
        compilers \
        openmpi \
        "libxc>=6,<7" fftw openblas scalapack libxsmm \
        "dftd4>=3.0,<4" \
        "libint>=2.6" \
        numpy scipy matplotlib-base pandas ase pymatgen \
        patchelf \
        cp2k-input-tools mdanalysis \
    > /tmp/conda_create.log 2>&1 \
    || { echo "=== CONDA CREATE FAILED ==="; \
         cat /tmp/conda_create.log | tr -cd '[:print:]\n\t' | tail -100; exit 1; } \
    && echo "=== Conda env created ===" \
    && micromamba clean -afy > /dev/null 2>&1 \
    && echo "=== Conda env cleaned ==="

# Environment for the build — CE is the conda env prefix
ENV CE=/opt/conda/envs/cp2kenv
ENV PATH="${CE}/bin:${PATH}"
ENV LD_LIBRARY_PATH="${CE}/lib"
# CRITICAL: pkg-config must find .pc files from conda packages (dftd4, scalapack, libxc, etc.)
ENV PKG_CONFIG_PATH="${CE}/lib/pkgconfig:${CE}/share/pkgconfig"

# ---------------------------------------------------------------------------
# libint2 pkg-config shim: conda-forge "libint" package provides the library
# and headers but does NOT install a libint2.pc file.  Both CP2K's
# FindLibint2.cmake and our Libint2Config.cmake shim require pkg-config.
# Create a minimal .pc that points to the conda prefix.
# ---------------------------------------------------------------------------
RUN if ! pkg-config --exists libint2 2>/dev/null; then \
        echo "=== Creating libint2.pc (conda pkg missing .pc) ===" && \
        LINT2_SO=$(ls ${CE}/lib/libint2.so* 2>/dev/null | head -1) && \
        if [ -z "$LINT2_SO" ]; then \
            echo "FATAL: libint2.so not found in ${CE}/lib — conda install failed?"; \
            ls ${CE}/lib/libint* 2>/dev/null || echo "  (no libint files at all)"; \
            exit 1; \
        fi && \
        echo "  Found: $LINT2_SO" && \
        printf 'prefix=%s\nlibdir=${prefix}/lib\nincludedir=${prefix}/include\n\nName: libint2\nDescription: Libint2 integral evaluation library (conda-forge)\nVersion: 2.6.0\nLibs: -L${libdir} -lint2 -lstdc++\nCflags: -I${includedir} -I${includedir}/libint2\n' \
            "${CE}" > ${CE}/lib/pkgconfig/libint2.pc && \
        echo "  Created ${CE}/lib/pkgconfig/libint2.pc" && \
        pkg-config --modversion libint2 && \
        echo "  Libs: $(pkg-config --libs libint2)" && \
        echo "  Cflags: $(pkg-config --cflags libint2)" && \
        echo "=== libint2.pc installed ==="; \
    else \
        echo "=== libint2.pc already provided by conda ==="; \
    fi

# Allow mpirun as root in the builder stage (needed for verification step).
# OpenMPI 5.x uses PRTE runtime — need both OMPI and PRTE env vars.
ENV OMPI_ALLOW_RUN_AS_ROOT=1
ENV OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1
ENV PRTE_ALLOW_RUN_AS_ROOT=1
ENV PRTE_ALLOW_RUN_AS_ROOT_CONFIRM=1

# ---------------------------------------------------------------------------
# Verify critical conda packages installed correctly
# ---------------------------------------------------------------------------
RUN echo "=== Verifying conda packages ===" && \
    echo "--- pkg-config files ---" && \
    for pc in dftd4 scalapack libxc libxcf03 fftw3 openblas mctc-lib multicharge libint2; do \
        if pkg-config --exists "$pc" 2>/dev/null; then \
            echo "  OK: $pc $(pkg-config --modversion $pc 2>/dev/null)"; \
        else \
            echo "  MISSING: $pc"; \
        fi; \
    done && \
    echo "--- CMake config files ---" && \
    for cmdir in Libxc DBCSR; do \
        if [ -d "${CE}/lib/cmake/${cmdir}" ]; then \
            echo "  OK: ${cmdir} CMake config found"; \
        else \
            echo "  INFO: ${cmdir} CMake config not found (may be OK)"; \
        fi; \
    done && \
    echo "--- Critical libraries ---" && \
    ls -la ${CE}/lib/libdftd4* 2>/dev/null || echo "  WARNING: libdftd4 not found" && \
    ls -la ${CE}/lib/libxcf03* 2>/dev/null || echo "  WARNING: libxcf03 (Fortran) not found" && \
    ls -la ${CE}/lib/libscalapack* 2>/dev/null || echo "  WARNING: libscalapack not found" && \
    echo "--- Fortran module files ---" && \
    ls ${CE}/include/xc_f03*.mod 2>/dev/null | head -3 || echo "  WARNING: libxc Fortran .mod files not found" && \
    echo "=== Verification complete ==="

# ---------------------------------------------------------------------------
# dftd4 CMake shim: conda-forge dftd4 is built with Meson, so it provides
# only pkg-config (.pc) files. CP2K's find_package(dftd4) needs CMake config.
# This shim bridges pkg-config → CMake imported target dftd4::dftd4.
# ---------------------------------------------------------------------------
COPY dftd4Config.cmake /tmp/dftd4Config.cmake
RUN mkdir -p ${CE}/lib/cmake/dftd4 && \
    cp /tmp/dftd4Config.cmake ${CE}/lib/cmake/dftd4/dftd4Config.cmake && \
    echo "=== dftd4 CMake config installed ==="

# ---------------------------------------------------------------------------
# libint2 CMake shim: conda-forge libint provides pkg-config but not CMake
# config files. CP2K's find_package(Libint2) needs this shim.
# ---------------------------------------------------------------------------
COPY Libint2Config.cmake /tmp/Libint2Config.cmake
RUN mkdir -p ${CE}/lib/cmake/Libint2 && \
    cp /tmp/Libint2Config.cmake ${CE}/lib/cmake/Libint2/Libint2Config.cmake && \
    echo "=== libint2 CMake config shim installed ==="

# ---------------------------------------------------------------------------
# Build libint2 Fortran module: conda's libint is built WITHOUT Fortran
# support (ENABLE_FORTRAN=OFF). CP2K needs libint_f.mod which provides
# ISO_C_BINDING types for the libint2 C API. We download the Fortran
# interface source from the libint2 GitHub repo and compile it against
# the installed conda headers to produce libint_f.mod.
#
# Three files are needed from libint2:
#   1. libint_f.F90  — the Fortran module source (uses C preprocessor)
#   2. c_to_f.py     — generates libint2_types_f.h from C struct defs
#   3. make_defs.py  — extracts #define macros into fortran_incldefs.h
# ---------------------------------------------------------------------------
RUN echo "=== Building libint2 Fortran interface module ===" && \
    mkdir -p /tmp/libint_fortran && cd /tmp/libint_fortran && \
    wget -q "https://raw.githubusercontent.com/evaleev/libint/v2.9.0/export/fortran/libint_f.F90" && \
    wget -q "https://raw.githubusercontent.com/evaleev/libint/v2.9.0/export/fortran/c_to_f.py" && \
    wget -q "https://raw.githubusercontent.com/evaleev/libint/v2.9.0/export/fortran/make_defs.py" && \
    echo "  Downloaded Fortran interface source from libint2 v2.9.0" && \
    echo "  --- Diagnosing installed libint2 headers ---" && \
    find ${CE}/include/libint2 -name '*.h' -type f 2>/dev/null | sort | head -15 && \
    TYPES_H=$(find ${CE}/include -name 'libint2_types.h' -path '*/libint2/*' -type f | head -1) && \
    if [ -z "$TYPES_H" ]; then \
        echo "FATAL: libint2_types.h not found in conda install"; \
        echo "  Files in ${CE}/include/libint2/:"; \
        ls -la ${CE}/include/libint2/ 2>/dev/null; \
        exit 1; \
    fi && \
    echo "  Using types header: $TYPES_H" && \
    echo "  --- Preprocessing libint2_types.h to resolve macros ---" && \
    echo "  Including libint2_params.h for LIBINT2_DEFINED_* macros..." && \
    PARAMS_H=$(find ${CE}/include -name 'libint2_params.h' -path '*/libint2/*' -type f | head -1) && \
    echo "  Params header: ${PARAMS_H:-NOT FOUND}" && \
    if [ -n "$PARAMS_H" ]; then \
        echo "  Params content (first 30 lines):" && head -30 "$PARAMS_H" && \
        gcc -E -P -I${CE}/include -include "$PARAMS_H" "$TYPES_H" 2>/dev/null > libint2_types_pp.h; \
    else \
        gcc -E -P -I${CE}/include "$TYPES_H" 2>/dev/null > libint2_types_pp.h; \
    fi && \
    echo "  Preprocessed types: $(wc -l < libint2_types_pp.h) lines" && \
    echo "  --- Generating libint2_types_f.h (Fortran type definitions) ---" && \
    python c_to_f.py libint2_types_pp.h libint2_types_f.h prim_data Libint_t && \
    echo "  Generated libint2_types_f.h:" && cat libint2_types_f.h && \
    echo "  --- Generating fortran_incldefs.h (preprocessor macros) ---" && \
    if [ -n "$PARAMS_H" ]; then \
        cat ${CE}/include/libint2/config.h "$PARAMS_H" > combined_config.h && \
        python make_defs.py combined_config.h fortran_incldefs.h && \
        rm combined_config.h; \
    else \
        python make_defs.py ${CE}/include/libint2/config.h fortran_incldefs.h; \
    fi && \
    echo "  fortran_incldefs.h: $(wc -l < fortran_incldefs.h) lines (first 30):" && head -30 fortran_incldefs.h && \
    echo "  --- Compiling libint_f.F90 to produce libint_f.mod ---" && \
    echo "  Trimming compute_eri_f subroutine (not needed by CP2K, triggers gfortran ICE)..." && \
    CONTAINS_LINE=$(grep -n '^CONTAINS$' libint_f.F90 | head -1 | cut -d: -f1) && \
    if [ -n "$CONTAINS_LINE" ]; then \
        IFDEF_LINE=$((CONTAINS_LINE - 1)) && \
        head -n $((IFDEF_LINE - 1)) libint_f.F90 > libint_f_trimmed.F90 && \
        echo "END MODULE libint_f" >> libint_f_trimmed.F90 && \
        mv libint_f_trimmed.F90 libint_f.F90 && \
        echo "  Removed CONTAINS block from line $IFDEF_LINE onward ($(wc -l < libint_f.F90) lines remain)"; \
    else \
        echo "  No CONTAINS block found, using as-is"; \
    fi && \
    echo "  Step 1: Preprocess with external cpp (avoids gfortran cpp ICE)..." && \
    cpp -traditional-cpp -P \
        -I${CE}/include -I/tmp/libint_fortran \
        libint_f.F90 2>/dev/null > libint_f_pp.f90 && \
    echo "  Preprocessed: $(wc -l < libint_f_pp.f90) lines" && \
    echo "  First 20 lines:" && head -20 libint_f_pp.f90 && \
    echo "  Step 2: Compile preprocessed Fortran (no -cpp flag)..." && \
    ${CE}/bin/gfortran -c -ffree-form -fPIC -O0 \
        libint_f_pp.f90 -o libint_f.o 2>&1 && \
    if [ ! -f libint_f.mod ]; then \
        echo "FATAL: libint_f.mod not generated after compilation"; \
        ls -la /tmp/libint_fortran/; \
        exit 1; \
    fi && \
    cp libint_f.mod ${CE}/include/ && \
    echo "  Installed: $(ls -la ${CE}/include/libint_f.mod)" && \
    rm -rf /tmp/libint_fortran && \
    echo "=== libint2 Fortran module ready ==="

# Download CP2K 2024.2 release (includes DBCSR submodule at exts/dbcsr/)
WORKDIR /opt
RUN wget -q "https://github.com/cp2k/cp2k/releases/download/v2024.2/cp2k-2024.2.tar.bz2" \
    && tar xjf cp2k-2024.2.tar.bz2 \
    && rm cp2k-2024.2.tar.bz2

# ---------------------------------------------------------------------------
# Patch FindLibint2.cmake: CP2K's original version requires a pre-built
# libint_f.mod Fortran module, and has a variable-name mismatch where
# pkg_check_modules sets CP2K_LIBINT2_LIBRARIES but the code later uses
# CP2K_LIBINT2_LINK_LIBRARIES. Our replacement fixes both issues.
# ---------------------------------------------------------------------------
COPY FindLibint2.cmake /opt/cp2k-2024.2/cmake/modules/FindLibint2.cmake
RUN echo "=== Replaced FindLibint2.cmake with conda-compatible version ==="

# ---------------------------------------------------------------------------
# Build DBCSR first (CP2K CMake requires find_package(DBCSR 2.6 REQUIRED))
# DBCSR source is in the release tarball at exts/dbcsr/.
# ---------------------------------------------------------------------------
WORKDIR /opt/cp2k-2024.2
RUN cd exts/dbcsr && mkdir build && cd build && \
    cmake .. \
        -GNinja \
        -DCMAKE_INSTALL_PREFIX=${CE} \
        -DCMAKE_PREFIX_PATH="${CE}" \
        -DUSE_MPI=ON \
        -DUSE_OPENMP=ON \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_Fortran_COMPILER=mpifort \
        -DCMAKE_C_COMPILER=mpicc \
        -DCMAKE_CXX_COMPILER=mpicxx \
    > /tmp/dbcsr_cmake.log 2>&1 \
    || { echo "=== DBCSR CMAKE FAILED ==="; \
         cat /tmp/dbcsr_cmake.log | tr -cd '[:print:]\n\t'; exit 1; } && \
    echo "=== DBCSR CMake configured ===" && \
    ninja -j$(nproc) > /tmp/dbcsr_build.log 2>&1 \
    || { echo "=== DBCSR BUILD FAILED ==="; \
         tail -100 /tmp/dbcsr_build.log | tr -cd '[:print:]\n\t'; exit 1; } && \
    ninja install > /tmp/dbcsr_install.log 2>&1 \
    || { echo "=== DBCSR INSTALL FAILED ==="; \
         cat /tmp/dbcsr_install.log | tr -cd '[:print:]\n\t'; exit 1; } && \
    echo "=== DBCSR installed ==="

# ---------------------------------------------------------------------------
# Build CP2K with CMake — DCP2K_USE_DFTD4=ON is the key flag.
# Uses full parallelism to reduce build time from ~40 min to ~15 min.
#
# IMPORTANT: We build ONLY the main cp2k executables (cp2k.psmp, cp2k.ssmp)
# instead of "ninja" (all targets). The C-only miniapp benchmarks
# (dbm_miniapp, grid_miniapp) have a known linking issue where CP2K's
# CMake doesn't propagate the core libxsmm library to their link lines
# when using conda-forge's split libxsmm packages (libxsmmf, libxsmmext,
# libxsmm). These miniapps are optional benchmarks not needed at runtime.
#
# We then do a manual install instead of "ninja install" to avoid the
# install target's dependency on all build targets.
# ---------------------------------------------------------------------------
WORKDIR /opt/cp2k-2024.2
RUN mkdir build && cd build && \
    echo "=== Starting CMake configure ===" && \
    cmake .. \
        -GNinja \
        -DCMAKE_INSTALL_PREFIX=${CE} \
        -DCMAKE_PREFIX_PATH="${CE}" \
        -DCP2K_USE_MPI=ON \
        -DCP2K_USE_DFTD4=ON \
        -DCP2K_USE_LIBINT2=OFF \
        -DCP2K_USE_LIBXC=ON \
        -DCP2K_USE_FFTW3=ON \
        -DCP2K_USE_LIBXSMM=ON \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_Fortran_COMPILER=mpifort \
        -DCMAKE_C_COMPILER=mpicc \
        -DCMAKE_CXX_COMPILER=mpicxx \
    > /tmp/cmake_configure.log 2>&1 \
    || { echo "=== CMAKE CONFIGURE FAILED ==="; \
         cat /tmp/cmake_configure.log | tr -cd '[:print:]\n\t'; exit 1; } && \
    echo "=== CMake configure summary ===" && \
    tail -40 /tmp/cmake_configure.log | tr -cd '[:print:]\n\t' && \
    echo "" && \
    echo "=== Building cp2k.psmp (MPI+OpenMP) — this takes 15-25 min ===" && \
    ninja -j$(nproc) cp2k.psmp > /tmp/build_psmp.log 2>&1 \
    || { echo "=== cp2k.psmp BUILD FAILED (last 50 lines) ==="; \
         tail -50 /tmp/build_psmp.log | tr -cd '[:print:]\n\t'; exit 1; } && \
    tail -5 /tmp/build_psmp.log && \
    echo "=== Building cp2k.ssmp (OpenMP-only, for version checks) ===" && \
    ninja -j$(nproc) cp2k.ssmp > /tmp/build_ssmp.log 2>&1 \
    || echo "WARNING: cp2k.ssmp not built (non-fatal, psmp is primary)" && \
    echo "=== Build complete, performing manual install ===" && \
    mkdir -p ${CE}/bin && \
    cp bin/cp2k.psmp ${CE}/bin/ && \
    (cp bin/cp2k.ssmp ${CE}/bin/ 2>/dev/null && echo "Installed cp2k.ssmp" \
     || echo "cp2k.ssmp not available") && \
    mkdir -p ${CE}/share/cp2k && \
    cp -r /opt/cp2k-2024.2/data ${CE}/share/cp2k/data && \
    echo "Installed CP2K data files: $(ls ${CE}/share/cp2k/data/ | wc -l) items" && \
    echo "--- Extracting libcp2k from build tree using ldd ---" && \
    LIBCP2K_LINE=$(ldd ${CE}/bin/cp2k.psmp 2>/dev/null | grep 'libcp2k' || true) && \
    echo "  ldd line: ${LIBCP2K_LINE:-EMPTY}" && \
    LIBCP2K_PATH=$(echo "$LIBCP2K_LINE" | awk '{print $3}') && \
    if [ -n "$LIBCP2K_PATH" ] && [ -e "$LIBCP2K_PATH" ]; then \
        LIBCP2K_DIR=$(dirname "$LIBCP2K_PATH"); \
        echo "  Found libcp2k dir: $LIBCP2K_DIR"; \
        cp -avL ${LIBCP2K_DIR}/libcp2k* ${CE}/lib/ 2>/dev/null || true; \
    else \
        echo "  ldd path not resolved, trying broad find with symlink support"; \
        find /opt/cp2k-2024.2/build -name 'libcp2k*' \( -type f -o -type l \) -ls; \
        find /opt/cp2k-2024.2/build -name 'libcp2k*' \( -type f -o -type l \) \
            -exec cp -avL {} ${CE}/lib/ \; ; \
    fi && \
    ls -la ${CE}/lib/libcp2k* \
    || { echo "FATAL: libcp2k.so not found — cannot proceed"; exit 1; } && \
    echo "--- Fixing RPATH on cp2k.psmp to point only to conda lib ---" && \
    patchelf --set-rpath "${CE}/lib" ${CE}/bin/cp2k.psmp && \
    echo "  New RPATH: $(patchelf --print-rpath ${CE}/bin/cp2k.psmp)" && \
    (patchelf --set-rpath "${CE}/lib" ${CE}/bin/cp2k.ssmp 2>/dev/null && \
     echo "  Fixed cp2k.ssmp RPATH too" || true) && \
    echo "--- Verifying cp2k.psmp dependencies (builder) ---" && \
    ldd ${CE}/bin/cp2k.psmp 2>&1 | head -40 && \
    if ldd ${CE}/bin/cp2k.psmp 2>/dev/null | grep -q 'not found'; then \
        echo "FATAL: Unresolved shared library dependencies:"; \
        ldd ${CE}/bin/cp2k.psmp | grep 'not found'; exit 1; \
    fi && \
    echo "=== CP2K installed — all dependencies resolved ==="

# ---------------------------------------------------------------------------
# VERIFY: D4 must be in the build flags. Fail the build otherwise.
# Use ssmp if available (no MPI init needed), else use mpirun for psmp.
# NOTE: OpenMPI 5.x uses PRTE runtime which refuses root by default.
#       We set env vars above AND use --allow-run-as-root flag.
# ---------------------------------------------------------------------------
# Run cp2k --version ONCE, save output, then check for dftd4 flag.
# Uses ssmp (no MPI init) if available, else mpirun with root-override flags.
RUN echo "=== CP2K version and flags ===" && \
    if [ -x "${CE}/bin/cp2k.ssmp" ]; then \
        ${CE}/bin/cp2k.ssmp --version > /tmp/cp2k_version.txt 2>&1; \
    else \
        mpirun --allow-run-as-root --np 1 --oversubscribe \
            ${CE}/bin/cp2k.psmp --version > /tmp/cp2k_version.txt 2>&1; \
    fi && \
    echo "--- Version output ---" && \
    cat /tmp/cp2k_version.txt | head -15 && \
    echo "--- Checking for dftd4 in cp2kflags ---" && \
    grep "cp2kflags" /tmp/cp2k_version.txt && \
    grep "cp2kflags" /tmp/cp2k_version.txt | grep -q "dftd4" && \
    echo "=== DFTD4 SUPPORT CONFIRMED ===" || \
    { echo "FATAL: DFTD4 not in build flags!"; \
      echo "Full version output:"; cat /tmp/cp2k_version.txt; exit 1; }

# Verify psmp (MPI+OpenMP) variant exists
RUN test -x ${CE}/bin/cp2k.psmp && \
    echo "=== cp2k.psmp (MPI+OMP) confirmed ===" || \
    { echo "FATAL: cp2k.psmp not found!"; ls -la ${CE}/bin/cp2k*; exit 1; }

# Clean up source tree and build artifacts (saves ~2GB in the image)
RUN rm -rf /opt/cp2k-2024.2

# Fix numpy/MDAnalysis ABI mismatch: conda-forge MDAnalysis binary was compiled
# against different numpy C headers. Rebuild MDAnalysis C extensions from source
# against the exact numpy installed in this env to eliminate the
# "numpy.ndarray size changed" RuntimeWarning.
# MUST happen BEFORE trim (which deletes .a static libs needed by the linker).
RUN ${CE}/bin/pip install --no-cache-dir \
        --force-reinstall --no-binary MDAnalysis MDAnalysis \
    && ${CE}/bin/pip install --no-cache-dir --upgrade "pint>=0.24" \
    && echo "=== MDAnalysis rebuilt from source + pint upgraded for numpy 2.x ==="

# Trim conda env (remove build artifacts not needed at runtime)
RUN find ${CE} -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true && \
    find ${CE} -type d -name 'tests'     -exec rm -rf {} + 2>/dev/null || true && \
    find ${CE} -name '*.pyc'             -delete        2>/dev/null || true && \
    find ${CE} -name '*.a'               -delete        2>/dev/null || true

# ---------------------------------------------------------------------------
# Stage 2: Runtime — lean image with only the conda env
# ---------------------------------------------------------------------------
FROM mambaorg/micromamba:1.5-jammy AS runtime

USER root

ENV DEBIAN_FRONTEND=noninteractive
ENV MAMBA_ROOT_PREFIX=/opt/conda
ENV PATH="${MAMBA_ROOT_PREFIX}/envs/cp2kenv/bin:${MAMBA_ROOT_PREFIX}/bin:${PATH}"
ENV CONDA_DEFAULT_ENV=cp2kenv

# Minimal runtime system packages + security updates
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        libgomp1 \
        openssh-client \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

# Copy the conda env with our source-built CP2K from builder
COPY --from=builder ${MAMBA_ROOT_PREFIX}/envs/cp2kenv ${MAMBA_ROOT_PREFIX}/envs/cp2kenv

# Register conda lib directory with dynamic linker (ensures libcp2k.so is found
# even if LD_LIBRARY_PATH is overridden by the container runtime)
RUN echo "${MAMBA_ROOT_PREFIX}/envs/cp2kenv/lib" > /etc/ld.so.conf.d/cp2kenv.conf && ldconfig

# Pip packages: security patches
RUN ${MAMBA_ROOT_PREFIX}/envs/cp2kenv/bin/pip install --no-cache-dir \
        pytest \
        "cryptography>=46.0.5" \
        "pillow>=12.1.1" \
    || true

# ---------------------------------------------------------------------------
# CP2K environment configuration
# ---------------------------------------------------------------------------
ENV CP2K_DATA_DIR=${MAMBA_ROOT_PREFIX}/envs/cp2kenv/share/cp2k/data
ENV CP2K_EXE=cp2k.psmp
ENV LD_LIBRARY_PATH="${MAMBA_ROOT_PREFIX}/envs/cp2kenv/lib"

ENV OMP_STACKSIZE=512m
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV KMP_AFFINITY=disabled

# OpenMPI: allow running as root inside containers
# OpenMPI 5.x uses PRTE runtime — need both OMPI and PRTE env vars
ENV OMPI_ALLOW_RUN_AS_ROOT=1
ENV OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1
ENV PRTE_ALLOW_RUN_AS_ROOT=1
ENV PRTE_ALLOW_RUN_AS_ROOT_CONFIRM=1
ENV OMPI_MCA_plm=isolated

# Matplotlib headless
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/matplotlib

# ---------------------------------------------------------------------------
# Application code
# ---------------------------------------------------------------------------
COPY cp2k_utils.py /usr/local/lib/cp2k_utils.py
RUN cp /usr/local/lib/cp2k_utils.py \
       ${MAMBA_ROOT_PREFIX}/envs/cp2kenv/lib/python3.11/site-packages/

COPY test_cp2k_utils.py /app/test_cp2k_utils.py

RUN mkdir -p /app/workdir /input /output /tmp/cp2k_scratch /tmp/matplotlib

WORKDIR /app/workdir

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
RUN ${MAMBA_ROOT_PREFIX}/envs/cp2kenv/bin/python -c \
    "import cp2k_utils; print('cp2k_utils OK')" && \
    ${MAMBA_ROOT_PREFIX}/envs/cp2kenv/bin/python -c \
    "import numpy, scipy, matplotlib, pandas, ase, pymatgen, MDAnalysis; print('Python stack OK')" && \
    ${MAMBA_ROOT_PREFIX}/envs/cp2kenv/bin/python -c \
    "from cp2k_input_tools.parser import CP2KInputParser; print('cp2k-input-tools OK')" && \
    echo "=== CP2K executables ===" && \
    ls -la ${MAMBA_ROOT_PREFIX}/envs/cp2kenv/bin/cp2k* && \
    echo "=== DFTD4 flag check (runtime) ===" && \
    echo "Checking for mpirun..." && \
    ls -la ${MAMBA_ROOT_PREFIX}/envs/cp2kenv/bin/mpirun 2>&1 || echo "mpirun not in conda bin" && \
    if [ -x "${MAMBA_ROOT_PREFIX}/envs/cp2kenv/bin/cp2k.ssmp" ]; then \
        echo "Using cp2k.ssmp (no MPI needed)" && \
        ${MAMBA_ROOT_PREFIX}/envs/cp2kenv/bin/cp2k.ssmp --version > /tmp/cp2k_ver.txt 2>&1; \
    elif [ -x "${MAMBA_ROOT_PREFIX}/envs/cp2kenv/bin/mpirun" ]; then \
        echo "Using mpirun from conda env (full path)" && \
        ${MAMBA_ROOT_PREFIX}/envs/cp2kenv/bin/mpirun \
            --allow-run-as-root --np 1 --oversubscribe \
            ${MAMBA_ROOT_PREFIX}/envs/cp2kenv/bin/cp2k.psmp --version > /tmp/cp2k_ver.txt 2>&1; \
    else \
        echo "WARNING: mpirun not found, trying cp2k.psmp directly" && \
        ${MAMBA_ROOT_PREFIX}/envs/cp2kenv/bin/cp2k.psmp --version > /tmp/cp2k_ver.txt 2>&1 || true; \
    fi && \
    echo "--- Version output ---" && \
    cat /tmp/cp2k_ver.txt 2>/dev/null | head -20 | tr -cd '[:print:]\n\t' && \
    grep "cp2kflags" /tmp/cp2k_ver.txt && \
    grep "cp2kflags" /tmp/cp2k_ver.txt | grep -q "dftd4" && \
    echo "=== DFTD4 verified in runtime image ===" && \
    echo "=== MPI ===" && \
    ${MAMBA_ROOT_PREFIX}/envs/cp2kenv/bin/mpirun --version 2>&1 | head -2 || echo "mpirun version check skipped" && \
    echo "=== CP2K data files ===" && \
    ls ${MAMBA_ROOT_PREFIX}/envs/cp2kenv/share/cp2k/data/ | head -10 && \
    echo "=== Shared library check (runtime) ===" && \
    ldd ${MAMBA_ROOT_PREFIX}/envs/cp2kenv/bin/cp2k.psmp 2>&1 | grep -E 'libcp2k|not found' || true && \
    if ldd ${MAMBA_ROOT_PREFIX}/envs/cp2kenv/bin/cp2k.psmp 2>/dev/null | grep -q 'not found'; then \
        echo "FATAL: Unresolved dependencies in runtime image:"; \
        ldd ${MAMBA_ROOT_PREFIX}/envs/cp2kenv/bin/cp2k.psmp | grep 'not found'; exit 1; \
    fi && \
    echo "ALL VERIFICATIONS PASSED"

CMD ["/bin/bash"]
