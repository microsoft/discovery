FROM docker.io/openroad/orfs@sha256:ee88641037a1c8e3403203bdca2b6256bf44a7957fa26719c8463ba638d76f9d
USER root
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/OpenROAD-flow-scripts/tools/install/OpenROAD/bin:/OpenROAD-flow-scripts/tools/install/yosys/bin:${PATH}"
RUN mkdir -p /workdir /input /output /app  && command -v openroad >/dev/null  && command -v sta >/dev/null  && command -v klayout >/dev/null  && python3 --version  && openroad -version  && sta -version
LABEL org.discovery.image.parent.digest="sha256:ee88641037a1c8e3403203bdca2b6256bf44a7957fa26719c8463ba638d76f9d"

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
USER root
ENV PATH="/OpenROAD-flow-scripts/tools/install/OpenROAD/bin:${PATH}"
RUN mkdir -p /workdir /input /output /app
COPY gds_assembly_utils.py /app/gds_assembly_utils.py
COPY run.py /app/run.py
COPY entrypoint.sh /app/entrypoint.sh
COPY cde_progress.py /app/cde_progress.py
COPY metric_classes.py /app/metric_classes.py
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
ENV PYTHONPATH=/app
RUN python3 --version && command -v openroad >/dev/null && command -v klayout >/dev/null
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "-u", "/app/run.py"]
