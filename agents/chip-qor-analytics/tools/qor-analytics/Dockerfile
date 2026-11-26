FROM docker.io/library/python:3.13-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
ENV HOME=/home/worker TMPDIR=/workdir TMP=/workdir TEMP=/workdir XDG_CACHE_HOME=/home/worker/.cache
RUN mkdir -p /input /output /workdir /app /home/worker /run
COPY run.py qor_analytics_utils.py qor_stats.py capability_check.py cde_progress.py metric_classes.py /app/
COPY params.schema.json /app/params.schema.json
COPY tests /app/tests
COPY entrypoint.sh /app/entrypoint.sh
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh && python3 -B /app/capability_check.py
WORKDIR /workdir
RUN python3 --version
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "-B", "-u", "/app/run.py", "--params-file", "/input/params.json"]
