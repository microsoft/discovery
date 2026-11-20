FROM docker.io/ghdl/ghdl:5.1.1-gcc-ubuntu-24.04
ARG COCOTB_VERSION=2.0.1
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ARG VERILATOR_VERSION=v5.036
ARG BUILD_JOBS=2
RUN DEBIAN_FRONTEND=noninteractive apt-get update &&  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends  iverilog gcovr lcov python3 python3-dev python3-venv make g++ perl ca-certificates tzdata  git autoconf flex bison libfl-dev help2man &&  apt-get clean && rm -rf /var/lib/apt/lists/* &&  ghdl --version &&  (ghdl --version | grep -iq "gcc" || (echo "FATAL: ghdl is not the GCC back-end (gcov unavailable)" && exit 1)) &&  gcov --version | head -1
RUN git clone --depth 1 --branch "${VERILATOR_VERSION}" https://github.com/verilator/verilator /tmp/verilator &&  cd /tmp/verilator && autoconf && ./configure && make -j"${BUILD_JOBS}" && make install &&  cd / && rm -rf /tmp/verilator &&  verilator --version &&  verilator --version | awk '{split($2,v,"."); if (v[1] < 5 || (v[1]==5 && v[2] < 36)) { print "FATAL: Verilator " $2 " < 5.036 (cocotb 2.x needs >=5.036)"; exit 1 }}'
RUN python3 -m venv /opt/cocotb &&  /opt/cocotb/bin/pip install --no-cache-dir "cocotb==${COCOTB_VERSION}" coverage vcdvcd python-constraint &&  /opt/cocotb/bin/pip install --no-cache-dir --no-deps "cocotb_coverage==1.2.0" &&  /opt/cocotb/bin/python -c "import cocotb; assert cocotb.__version__ == '${COCOTB_VERSION}'" &&  /opt/cocotb/bin/python -c "import cocotb_coverage, coverage, vcdvcd"
ENV PATH=/opt/cocotb/bin:/opt/ghdl/bin:/usr/local/bin:$PATH
LABEL org.discovery.cocotb.version="2.0.1" org.discovery.ghdl.backend="gcc-13.3-self-consistent-gcov"
RUN mkdir -p /workdir /input /output /app
COPY rtl_frontend.py /app/rtl_frontend.py
COPY code_coverage_utils.py /app/code_coverage_utils.py
COPY reachability_proof.py /app/reachability_proof.py
COPY run.py /app/run.py
COPY entrypoint.sh /app/entrypoint.sh
COPY cde_progress.py /app/cde_progress.py
COPY metric_classes.py /app/metric_classes.py
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
ENV PYTHONPATH=/app
RUN python3 --version && command -v verilator >/dev/null && command -v iverilog >/dev/null && command -v vvp >/dev/null && command -v ghdl >/dev/null && command -v gcov >/dev/null && command -v gcovr >/dev/null && python3 -c "import cocotb, cocotb_coverage, coverage, vcdvcd"
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "-u", "/app/run.py"]
