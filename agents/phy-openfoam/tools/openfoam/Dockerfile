# Pinned by digest (ubuntu:24.04 as pulled for the validated build); update deliberately.
FROM docker.io/library/ubuntu:24.04@sha256:78d4744ead1f5b19b04d0df558ab182a5300903900755e515b2ca4d10eb2044d AS foundation

ARG DEBIAN_FRONTEND=noninteractive
ARG OPENFOAM_PACKAGE_VERSION=20260724
ARG OPENFOAM_PACKAGE_SHA256=1dfa8d381011342ca5c2496c07402fb85a1bacd9b8600b2cc701afab42e23f59

# Foundation's own package, NOT OpenCFD's similarly named distribution. The
# default version predates the reference campaign. Both version and bytes freeze.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl python3 python3-venv \
       libglu1-mesa libxrender1 libxcursor1 libxft2 libxinerama1 libgomp1 \
    && curl --fail --location --retry 3 \
       "https://dl.openfoam.org/ubuntu/dists/noble/main/binary-amd64/openfoam14_${OPENFOAM_PACKAGE_VERSION}_amd64.deb" \
       --output /tmp/openfoam14.deb \
    && echo "${OPENFOAM_PACKAGE_SHA256}  /tmp/openfoam14.deb" | sha256sum --check --strict \
    && apt-get install -y --no-install-recommends /tmp/openfoam14.deb \
    && rm -f /tmp/openfoam14.deb \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/physics-venv \
    && /opt/physics-venv/bin/pip install --no-cache-dir \
       'numpy==2.4.6' 'pydantic==2.13.4' 'matplotlib==3.10.*' 'gmsh==4.13.*' \
    && groupadd --gid 10001 physics \
    && useradd --uid 10001 --gid 10001 --create-home physics

LABEL org.opencontainers.image.title="phy-openfoam Foundation 14 physics worker"
LABEL org.opencontainers.image.description="CLIO-led execution; independently authored contracts and diagnostics"
LABEL org.opencontainers.image.licenses="MIT AND GPL-3.0-or-later AND GPL-2.0-or-later"
LABEL org.opencontainers.image.version="0.2.1"

FROM foundation AS runtime
COPY pyproject.toml /opt/physics-src/pyproject.toml
COPY LICENSE THIRD_PARTY_NOTICES.md /opt/physics-src/
COPY LICENSES /opt/physics-src/LICENSES
COPY src /opt/physics-src/src
COPY entrypoint.sh /opt/physics-entrypoint.sh
RUN /opt/physics-venv/bin/pip install --no-cache-dir --no-deps /opt/physics-src \
    && chmod 0555 /opt/physics-entrypoint.sh \
    && mkdir -p /input /output /workdir \
    && chown 10001:10001 /output /workdir \
    && /opt/physics-venv/bin/pip freeze > /opt/physics-src/sbom-python.txt \
    && dpkg-query -W -f='${Package} ${Version}\n' > /opt/physics-src/sbom-dpkg.txt
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp/matplotlib
USER 10001:10001
WORKDIR /output
ENTRYPOINT ["/bin/bash", "/opt/physics-entrypoint.sh"]
CMD ["python", "-m", "discovery_physics.worker", "/input", "/output"]