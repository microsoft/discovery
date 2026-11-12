ARG TOOLCHAIN_IMAGE=toolchain
FROM docker.io/ghdl/ghdl:5.1.1-gcc-ubuntu-22.04 AS ghdl5
FROM docker.io/verilator/verilator:v5.036 AS toolchain
ARG COCOTB_VERSION=2.0.1
ARG SFPY_VERSION=0.6.0
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        iverilog lcov python3 python3-dev python3-venv make g++ ca-certificates libgnat-10 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghdl5 /opt/ghdl /opt/ghdl
ENV GHDL_PREFIX=/opt/ghdl/lib/ghdl
RUN /opt/ghdl/bin/ghdl --version | head -1 | grep -qv mcode
# Python 3.10 retains sfpy compatibility; GHDL uses the GCC, not mcode, backend.
RUN python3 -m venv /opt/cocotb && \
    /opt/cocotb/bin/pip install --no-cache-dir "cocotb==${COCOTB_VERSION}" "sfpy==${SFPY_VERSION}" coverage vcdvcd python-constraint && \
    /opt/cocotb/bin/pip install --no-cache-dir --no-deps "cocotb_coverage==1.2.0" && \
    /opt/cocotb/bin/python -c "import cocotb; assert cocotb.__version__ == '${COCOTB_VERSION}'" && \
    /opt/cocotb/bin/python -c "import importlib.metadata as m, sfpy; assert m.version('sfpy') == '${SFPY_VERSION}'" && \
    /opt/cocotb/bin/python -c "import cocotb_coverage, coverage, vcdvcd"
ENV PATH=/opt/cocotb/bin:/opt/ghdl/bin:/usr/local/bin:$PATH

FROM ${TOOLCHAIN_IMAGE} AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
ENV HOME=/home/worker TMPDIR=/tmp TMP=/tmp TEMP=/tmp XDG_CACHE_HOME=/home/worker/.cache
RUN mkdir -p /input /output /workdir /app /home/worker /var/tmp /run /dev/shm
COPY *.py /app/
COPY params.schema.json /app/params.schema.json
COPY entrypoint.sh /app/entrypoint.sh
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
WORKDIR /workdir
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "-B", "-u", "/app/run.py", "--params-file", "/input/params.json"]
