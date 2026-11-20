FROM docker.io/library/debian:12-slim
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends  ngspice xschem python3 ca-certificates  && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /workdir /input /output /app
COPY analog_spice_utils.py /app/analog_spice_utils.py
COPY run.py /app/run.py
COPY entrypoint.sh /app/entrypoint.sh
COPY cde_progress.py /app/cde_progress.py
COPY metric_classes.py /app/metric_classes.py
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
ENV PYTHONPATH=/app
COPY action_launcher.py /app/action_launcher.py
RUN python3 --version && command -v ngspice >/dev/null && command -v xschem >/dev/null
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "-u", "/app/run.py"]
