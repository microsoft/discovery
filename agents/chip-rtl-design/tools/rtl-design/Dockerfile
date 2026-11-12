ARG TOOLCHAIN_IMAGE=toolchain
FROM ghdl/synth:beta AS toolchain
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DEBIAN_FRONTEND=noninteractive
RUN python3 --version && yosys --version
# Keep the formatter pin identical to rtl-lint.
ARG VERIBLE_VER=v0.0-4141-g09a245fe
ADD https://github.com/chipsalliance/verible/releases/download/${VERIBLE_VER}/verible-${VERIBLE_VER}-linux-static-x86_64.tar.gz /tmp/verible.tar.gz
RUN mkdir -p /opt/verible \
    && tar -xzf /tmp/verible.tar.gz -C /opt/verible --strip-components=1 \
    && ln -sf /opt/verible/bin/* /usr/local/bin/ \
    && rm -f /tmp/verible.tar.gz

# Override only to reuse an already provisioned, compatible local toolchain.
FROM ${TOOLCHAIN_IMAGE} AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
ENV HOME=/home/worker TMPDIR=/tmp TMP=/tmp TEMP=/tmp XDG_CACHE_HOME=/home/worker/.cache
RUN mkdir -p /input /output /workdir /app /home/worker /var/tmp /run /dev/shm
COPY *.py /app/
COPY params.schema.json /app/params.schema.json
COPY entrypoint.sh /app/entrypoint.sh
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
RUN python3 -B /app/capability_check.py
WORKDIR /workdir
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "-B", "-u", "/app/run.py", "--params-file", "/input/params.json"]
