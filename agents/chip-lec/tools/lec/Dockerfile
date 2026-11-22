FROM docker.io/library/debian:12-slim@sha256:5ae3c39ebd15e229dcedd5cee596b2497182493d41ff162e824ba13fc1b2b867
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends  curl ca-certificates xz-utils tar libgomp1 libtcl8.6 python3  && rm -rf /var/lib/apt/lists/*
ARG OSS_TAG=2026-08-25
ARG OSS_FILE=oss-cad-suite-linux-x64-20260825.tgz
RUN curl -fL --retry 8 --retry-delay 5 --retry-all-errors -C -  --connect-timeout 30 -o /tmp/oss.tgz  "https://github.com/YosysHQ/oss-cad-suite-build/releases/download/${OSS_TAG}/${OSS_FILE}"  && tar -xzf /tmp/oss.tgz -C /opt  && rm /tmp/oss.tgz
ENV PATH="/opt/oss-cad-suite/bin:${PATH}"
RUN apt-get update && apt-get install -y --no-install-recommends make python3-click  && rm -rf /var/lib/apt/lists/*
RUN for tool in sby yosys yosys-smtbmc z3; do  printf '#!/bin/sh\nexec /opt/oss-cad-suite/bin/%s "$@"\n' "$tool"  > "/usr/local/bin/$tool";  chmod +x "/usr/local/bin/$tool";  done
RUN set -eux;  yosys --version; eqy --version; sby --version; z3 --version;  ghdl --version | head -1; python3 --version;  y=$(yosys --version | sed -n 's/^Yosys \([0-9]*\.[0-9]*\).*/\1/p');  e=$(eqy --version 2>&1 | sed -n 's/^EQY v\([0-9]*\.[0-9]*\).*/\1/p');  s=$(sby --version 2>&1 | sed -n 's/^SBY v\([0-9]*\.[0-9]*\).*/\1/p');  test "$y" = "$e"; test "$y" = "$s";  command -v yosys-smtbmc >/dev/null;  command -v iverilog >/dev/null;  command -v make >/dev/null;  python3 -c "import click";  yosys -q -p 'plugin -i ghdl'
RUN mkdir -p /workdir /input /output /app
LABEL org.discovery.oss-cad-suite.tag="2026-08-25" org.discovery.image.parent.digest="sha256:5ae3c39ebd15e229dcedd5cee596b2497182493d41ff162e824ba13fc1b2b867"

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
RUN mkdir -p /app
COPY capability_check.py /app/capability_check.py
RUN python3 /app/capability_check.py
RUN mkdir -p /workdir /input /output /app
COPY rtl_frontend.py /app/rtl_frontend.py
COPY lec_utils.py /app/lec_utils.py
COPY run.py /app/run.py
COPY entrypoint.sh /app/entrypoint.sh
COPY cde_progress.py /app/cde_progress.py
COPY metric_classes.py /app/metric_classes.py
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
ENV PYTHONPATH=/app
COPY action_launcher.py /app/action_launcher.py
RUN python3 --version && command -v yosys >/dev/null && command -v eqy >/dev/null
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "-u", "/app/run.py"]
