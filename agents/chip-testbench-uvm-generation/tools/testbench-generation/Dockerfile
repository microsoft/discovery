FROM docker.io/verilator/verilator:v5.036@sha256:7e3809f5def31acb9746be550714bc991bae87dd687ac2939de183a541ed84c7
ARG VERILATOR_VERSION=5.036
ARG COCOTB_VERSION=2.0.1
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends  iverilog ghdl lcov python3 python3-dev python3-venv make g++ perl ca-certificates &&  apt-get clean && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/cocotb &&  /opt/cocotb/bin/pip install --no-cache-dir "cocotb==${COCOTB_VERSION}" coverage vcdvcd python-constraint &&  /opt/cocotb/bin/pip install --no-cache-dir --no-deps "cocotb_coverage==1.2.0" &&  verilator --version | grep -F "Verilator ${VERILATOR_VERSION}" &&  /opt/cocotb/bin/python -c "import cocotb; assert cocotb.__version__ == '${COCOTB_VERSION}'" &&  /opt/cocotb/bin/python -c "import cocotb_coverage, coverage, vcdvcd"
ENV PATH=/opt/cocotb/bin:/usr/local/bin:$PATH
LABEL org.discovery.verilator.version="5.036" org.discovery.cocotb.version="2.0.1"
RUN mkdir -p /workdir /input /output /app
LABEL org.discovery.image.parent.digest="sha256:7e3809f5def31acb9746be550714bc991bae87dd687ac2939de183a541ed84c7"

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
COPY testbench_generation_utils.py /app/testbench_generation_utils.py
COPY simulator_select.py /app/simulator_select.py
COPY mutation.py /app/mutation.py
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
