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
RUN mkdir -p /opt/gatecheck && cd /opt/gatecheck  && yosys -q -p 'plugin -i ghdl'  && printf '%s\n'  'module gate(input clk, input [3:0] d, output reg [3:0] q);'  '  always @(posedge clk) q <= d;'  '`ifdef FORMAL'  '  reg pv = 1'"'"'b0;'  '  always @(posedge clk) pv <= 1'"'"'b1;'  '  always @(posedge clk)'  '    if (pv)'  '      g_coherent: assert ((((q ^ $past(q)) & ((q ^ $past(q)) - 1)) == 0));'  '`endif'  'endmodule' > gate.sv  && printf '%s\n'  '[options]' 'mode bmc' 'depth 6' ''  '[engines]' 'smtbmc z3' ''  '[script]' 'read_verilog -sv -formal gate.sv' 'prep -top gate' ''  '[files]' 'gate.sv' > gate.sby  && { sby -f gate.sby > gate.out 2>&1 || true; }  && grep -q 'DONE (FAIL' gate.out  && grep -q 'g_coherent' gate.out  && echo "FORMAL_TOOLCHAIN_OK" > /opt/.formal_ok
RUN mkdir -p /workdir /input /output /app
COPY rtl_frontend.py /app/rtl_frontend.py
COPY cdc_rdc_utils.py /app/cdc_rdc_utils.py
COPY cdc_formal.py /app/cdc_formal.py
COPY domain_formal.py /app/domain_formal.py
COPY formal_capability_check.py /app/formal_capability_check.py
COPY run.py /app/run.py
COPY entrypoint.sh /app/entrypoint.sh
COPY cde_progress.py /app/cde_progress.py
COPY metric_classes.py /app/metric_classes.py
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
RUN python3 /app/formal_capability_check.py
ENV PYTHONPATH=/app
RUN python3 --version && command -v yosys >/dev/null && command -v yosys-smtbmc >/dev/null && command -v z3 >/dev/null
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "-u", "/app/run.py"]
