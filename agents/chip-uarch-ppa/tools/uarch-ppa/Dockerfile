FROM cgr.dev/chainguard/python:latest-dev@sha256:cf00203e9a81f254f1cdefdc0b0b22527d2cfbe0a884610605443c81d8b084bd
USER root
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
RUN mkdir -p /workdir /input /output /app
RUN python3 --version
LABEL org.discovery.image.parent.digest="sha256:cf00203e9a81f254f1cdefdc0b0b22527d2cfbe0a884610605443c81d8b084bd"

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
COPY uarch_ppa_utils.py /app/uarch_ppa_utils.py
COPY run.py /app/run.py
COPY entrypoint.sh /app/entrypoint.sh
COPY cde_progress.py /app/cde_progress.py
COPY metric_classes.py /app/metric_classes.py
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
ENV PYTHONPATH=/app
COPY action_launcher.py /app/action_launcher.py
RUN python3 --version
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "-u", "/app/run.py"]
