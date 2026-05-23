# syntax=docker/dockerfile:1.7
#
# Icarus Verilog v12 — RTL/SystemVerilog lint & syntax checking image.
#
# Distribution note: ships GPL-2.0 software (Icarus Verilog). The party
# that builds and distributes the resulting image becomes the GPL-2.0
# distributor. See ../../THIRD_PARTY_NOTICES.md.

ARG UBUNTU_TAG=noble-20250529
ARG IVERILOG_VERSION=v12_0
ARG APP_USER=app
ARG APP_UID=1000
ARG APP_GID=1000

# ---------------------------------------------------------------------
# Stage 1: builder — compile Icarus Verilog from source into /opt/iverilog
# ---------------------------------------------------------------------
FROM ubuntu:${UBUNTU_TAG} AS builder

ARG IVERILOG_VERSION
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates \
        build-essential \
        autoconf \
        automake \
        libtool \
        pkg-config \
        bison \
        flex \
        gperf \
        gawk \
        git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp/build
RUN git clone --depth 1 --branch "${IVERILOG_VERSION}" \
        https://github.com/steveicarus/iverilog.git . \
 && sh autoconf.sh \
 && ./configure --prefix=/opt/iverilog \
 && make -j"$(nproc)" \
 && make install \
 && install -D -m 0644 COPYING /opt/iverilog/share/doc/iverilog/COPYING

# ---------------------------------------------------------------------
# Stage 2: runtime — minimal Ubuntu + iverilog + non-root user
# ---------------------------------------------------------------------
FROM ubuntu:${UBUNTU_TAG}

ARG APP_USER
ARG APP_UID
ARG APP_GID

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PATH=/opt/iverilog/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Runtime system packages.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates \
        bash \
        coreutils \
        findutils \
        grep \
        sed \
        gawk \
        make \
        diffutils \
        less \
        procps \
 && rm -rf /var/lib/apt/lists/*

# Iverilog binaries (cached layer; independent of user setup below).
COPY --from=builder /opt/iverilog /opt/iverilog

# Non-root user and standard /app layout. Ubuntu's base image ships a
# default `ubuntu` user at UID/GID 1000; remove it before claiming that
# id range. Discovery mounts inputs at /mnt/input (ro) and outputs at
# /mnt/output (rw); pre-create them with the right ownership so non-root
# execution can write artefacts.
RUN if id -u ubuntu >/dev/null 2>&1; then userdel --remove ubuntu; fi \
 && groupadd --system --gid "${APP_GID}" "${APP_USER}" \
 && useradd  --system --uid "${APP_UID}" --gid "${APP_GID}" \
        --home-dir "/home/${APP_USER}" --create-home \
        --shell /bin/bash "${APP_USER}" \
 && mkdir -p /app /mnt/input /mnt/output \
 && chown -R "${APP_UID}:${APP_GID}" /app /mnt/input /output

WORKDIR /app
USER ${APP_USER}:${APP_USER}

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD iverilog -V >/dev/null 2>&1 || exit 1

LABEL org.opencontainers.image.title="iverilog" \
      org.opencontainers.image.description="Icarus Verilog v12 for RTL/SystemVerilog lint and syntax checking" \
      org.opencontainers.image.source="https://github.com/microsoft/discovery-catalog" \
      org.opencontainers.image.licenses="GPL-2.0-only" \
      org.opencontainers.image.base.name="docker.io/library/ubuntu:${UBUNTU_TAG}"

CMD ["/bin/bash"]


