FROM docker.io/openroad/orfs@sha256:ee88641037a1c8e3403203bdca2b6256bf44a7957fa26719c8463ba638d76f9d
USER root
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/OpenROAD-flow-scripts/tools/install/OpenROAD/bin:/OpenROAD-flow-scripts/tools/install/yosys/bin:${PATH}"
RUN mkdir -p /workdir /input /output /app  && command -v openroad >/dev/null  && command -v sta >/dev/null  && command -v klayout >/dev/null  && python3 --version  && openroad -version  && sta -version
LABEL org.discovery.image.parent.digest="sha256:ee88641037a1c8e3403203bdca2b6256bf44a7957fa26719c8463ba638d76f9d"

ARG DISCOVERY_TOOL_SOURCE_DIGEST=sha256:4ddbb80c7bddda4f07c62f87780a2a2488480c6769fb02147f835079732ad761
LABEL org.discovery.tool.source.digest="${DISCOVERY_TOOL_SOURCE_DIGEST}" org.discovery.capability.macro-electrical-intent="v1"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
USER root
ENV PATH="/OpenROAD-flow-scripts/tools/install/OpenROAD/bin:/OpenROAD-flow-scripts/tools/install/yosys/bin:${PATH}"
RUN mkdir -p /workdir /input /output /app
COPY constraints_utils.py /app/constraints_utils.py
COPY sdc_author.py /app/sdc_author.py
COPY run.py /app/run.py
COPY entrypoint.sh /app/entrypoint.sh
COPY cde_progress.py /app/cde_progress.py
COPY metric_classes.py /app/metric_classes.py
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
ENV PYTHONPATH=/app
RUN python3 -c "import sys; sys.path.insert(0,'/app'); import sdc_author, constraints_utils;  assert hasattr(sdc_author,'author_sdc') and hasattr(sdc_author,'coverage');  assert hasattr(constraints_utils,'_author') and hasattr(constraints_utils,'_lint');  print('CONSTRAINTS_MODULES_OK')"  && (command -v sta >/dev/null || command -v openroad >/dev/null)  && echo "CONSTRAINTS_TOOLCHAIN_OK" > /opt/.constraints_ok
RUN python3 --version && command -v openroad >/dev/null && command -v sta >/dev/null && command -v yosys >/dev/null
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "-u", "/app/run.py"]
