FROM docker.io/library/debian:12-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc AS python-build
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
		python3 python3-dev python3-venv python3-pip python3-setuptools python3-wheel python3-tomli \
		g++ make ca-certificates libpng-dev libcurl4-openssl-dev libexpat1-dev zlib1g-dev && \
		rm -rf /var/lib/apt/lists/*
COPY install_python_sources.py python_sources.lock.json /opt/python-source-build/
COPY dependency-sources/ /opt/python-source-build/archives/
ARG PYTHON_SOURCES_OFFLINE=0
# Upstream strips debug symbols at link time. Avoid generating that discarded
# debug data in every translation unit; preserve the distribution's -O2 flags.
ENV KLAYOUT_SETUP_MULTICORE=4 CFLAGS=-g0 CXXFLAGS=-g0
RUN python3 -m venv --system-site-packages /opt/klayout && \
		if [ "${PYTHON_SOURCES_OFFLINE}" = "1" ]; then \
			/opt/klayout/bin/python /opt/python-source-build/install_python_sources.py --lock /opt/python-source-build/python_sources.lock.json --archives /opt/python-source-build/archives --offline; \
		else \
			/opt/klayout/bin/python /opt/python-source-build/install_python_sources.py --lock /opt/python-source-build/python_sources.lock.json --archives /opt/python-source-build/archives; \
		fi
FROM docker.io/library/debian:12-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends python3 libpng16-16 libcurl4 libexpat1 zlib1g && rm -rf /var/lib/apt/lists/*
COPY --from=python-build /opt/klayout /opt/klayout
ENV PATH=/opt/klayout/bin:$PATH
RUN python3 -c "import importlib.metadata as m, klayout.db; assert m.version('klayout') == '0.30.10'"
RUN mkdir -p /workdir /input /output /app
COPY dfm_utils.py /app/dfm_utils.py
COPY layout_geometry.py /app/layout_geometry.py
COPY capability_check.py /app/capability_check.py
COPY run.py /app/run.py
COPY entrypoint.sh /app/entrypoint.sh
COPY cde_progress.py /app/cde_progress.py
COPY metric_classes.py /app/metric_classes.py
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
ENV PYTHONPATH=/app
RUN python3 /app/capability_check.py
COPY action_launcher.py /app/action_launcher.py
RUN python3 --version && python3 -c "import klayout.db"
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "-u", "/app/run.py"]
