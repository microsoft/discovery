FROM docker.io/verilator/verilator:v5.036@sha256:7e3809f5def31acb9746be550714bc991bae87dd687ac2939de183a541ed84c7 AS verilator5
FROM docker.io/ghdl/ghdl:5.1.1-gcc-ubuntu-24.04@sha256:9af5c2d0fab771bf57bc8cf8eeb7309c71374b629106ac68f452adb1d9060cb9
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DEBIAN_FRONTEND=noninteractive
COPY --from=verilator5 /usr/local/bin/verilator* /usr/local/bin/
COPY --from=verilator5 /usr/local/share/verilator /usr/local/share/verilator
RUN apt-get update && apt-get install -y --no-install-recommends \
		iverilog gcovr lcov python3 python3-dev python3-venv python3-pip \
		python3-setuptools python3-wheel python3-coverage python3-yaml python3-pytest \
		make g++ ccache perl ca-certificates tzdata && rm -rf /var/lib/apt/lists/*
COPY install_python_sources.py python_sources.lock.json /opt/python-source-build/
COPY dependency-sources/ /opt/python-source-build/archives/
ARG PYTHON_SOURCES_OFFLINE=0
RUN python3 -m venv --system-site-packages /opt/cocotb && \
		if [ "${PYTHON_SOURCES_OFFLINE}" = "1" ]; then \
			/opt/cocotb/bin/python /opt/python-source-build/install_python_sources.py --lock /opt/python-source-build/python_sources.lock.json --archives /opt/python-source-build/archives --offline; \
		else \
			/opt/cocotb/bin/python /opt/python-source-build/install_python_sources.py --lock /opt/python-source-build/python_sources.lock.json --archives /opt/python-source-build/archives; \
		fi && rm -rf /opt/python-source-build/archives
ENV PATH=/opt/cocotb/bin:/opt/ghdl/bin:/usr/local/bin:$PATH
COPY verify_simulator_toolchain.py /opt/verify_simulator_toolchain.py
RUN python3 /opt/verify_simulator_toolchain.py
RUN verilator --version | grep -F 'Verilator 5.036' && ghdl --version | grep -iq gcc && gcov --version && \
		python3 -c "import cocotb, cocotb_coverage.coverage, cocotb_coverage.crv, coverage, vcdvcd; assert cocotb.__version__ == '2.0.1'"
LABEL org.discovery.verilator.version="5.036" org.discovery.cocotb.version="2.0.1" org.discovery.cocotb-coverage.version="2.0"
RUN mkdir -p /workdir /input /output /app
LABEL org.discovery.image.parent.digest="sha256:7e3809f5def31acb9746be550714bc991bae87dd687ac2939de183a541ed84c7"

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
COPY functional_coverage_utils.py /app/functional_coverage_utils.py
COPY reachability_proof.py /app/reachability_proof.py
COPY run.py /app/run.py
COPY entrypoint.sh /app/entrypoint.sh
COPY cde_progress.py /app/cde_progress.py
COPY metric_classes.py /app/metric_classes.py
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
ENV PYTHONPATH=/app
RUN python3 --version && command -v verilator >/dev/null && command -v iverilog >/dev/null && command -v vvp >/dev/null && command -v ghdl >/dev/null && python3 -c "import cocotb, cocotb_coverage, coverage, vcdvcd"
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "-u", "/app/run.py"]
