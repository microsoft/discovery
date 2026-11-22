FROM docker.io/openroad/orfs@sha256:ee88641037a1c8e3403203bdca2b6256bf44a7957fa26719c8463ba638d76f9d
USER root
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/OpenROAD-flow-scripts/tools/install/OpenROAD/bin:/OpenROAD-flow-scripts/tools/install/yosys/bin:${PATH}"
RUN mkdir -p /workdir /input /output /app  && command -v openroad >/dev/null  && command -v sta >/dev/null  && command -v klayout >/dev/null  && python3 --version  && openroad -version  && sta -version
LABEL org.discovery.image.parent.digest="sha256:ee88641037a1c8e3403203bdca2b6256bf44a7957fa26719c8463ba638d76f9d"

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/OpenROAD-flow-scripts/tools/install/OpenROAD/bin:${PATH}"
RUN mkdir -p /workdir /input /output /app
RUN command -v openroad >/dev/null || { echo "openroad missing"; exit 1; };  printf 'exit\n' > /tmp/p.tcl;  openroad -no_init -exit /tmp/p.tcl >/dev/null 2>&1 || true;  printf 'if {![llength [info commands read_upf]]} { exit 1 }\nexit\n' > /tmp/q.tcl;  openroad -no_init -exit /tmp/q.tcl || { echo "read_upf not available"; exit 1; }
COPY power_intent_upf_utils.py /app/power_intent_upf_utils.py
COPY run.py /app/run.py
COPY entrypoint.sh /app/entrypoint.sh
COPY cde_progress.py /app/cde_progress.py
COPY metric_classes.py /app/metric_classes.py
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
ENV PYTHONPATH=/app
COPY action_launcher.py /app/action_launcher.py
RUN python3 --version && command -v openroad >/dev/null
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "-u", "/app/run.py"]
