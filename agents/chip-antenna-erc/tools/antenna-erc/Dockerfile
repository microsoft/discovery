FROM docker.io/openroad/orfs@sha256:ee88641037a1c8e3403203bdca2b6256bf44a7957fa26719c8463ba638d76f9d
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DEBIAN_FRONTEND=noninteractive
USER root
ENV PATH="/OpenROAD-flow-scripts/tools/install/OpenROAD/bin:${PATH}"
ARG MAGIC_REF=9fd4ee57386c08346b20389a55e4eb9d32553979
ARG MAGIC_SHA256=dcdfdd40058b4f2029cce20d12e0225ae415fda42d3980eafbbfe53ba54fc6e9
RUN apt-get update && apt-get install -y --no-install-recommends  git build-essential m4 tcsh csh  tcl-dev tk-dev libcairo2-dev libncurses-dev  libx11-dev mesa-common-dev libglu1-mesa-dev ca-certificates curl  && mkdir -p /opt/magic-build  && curl --fail --location "https://codeload.github.com/RTimothyEdwards/magic/tar.gz/${MAGIC_REF}" -o /opt/magic-build/source.tar.gz  && echo "${MAGIC_SHA256}  /opt/magic-build/source.tar.gz" | sha256sum -c -  && tar -xzf /opt/magic-build/source.tar.gz -C /opt/magic-build  && cd "/opt/magic-build/magic-${MAGIC_REF}"  && test "$(cat VERSION)" = "8.3.693"  && ./configure --prefix=/usr/local  && make -j1  && make install  && cd / && rm -rf /opt/magic-build /var/lib/apt/lists/*  && test "$(magic --version)" = "8.3.693"
RUN mkdir -p /workdir /input /output /app
COPY antenna_erc_utils.py /app/antenna_erc_utils.py
COPY run.py /app/run.py
COPY entrypoint.sh /app/entrypoint.sh
COPY cde_progress.py /app/cde_progress.py
COPY metric_classes.py /app/metric_classes.py
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
ENV PYTHONPATH=/app
COPY action_launcher.py /app/action_launcher.py
RUN python3 --version && command -v klayout >/dev/null && command -v magic >/dev/null
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "-u", "/app/run.py"]
