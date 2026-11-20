FROM docker.io/library/debian:12-slim
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends  python3 python3-pip &&  pip3 install --no-cache-dir --break-system-packages "klayout==0.30.10" &&  apt-get purge -y python3-pip && apt-get autoremove -y &&  apt-get clean && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /workdir /input /output /app
COPY dfm_utils.py /app/dfm_utils.py
COPY layout_geometry.py /app/layout_geometry.py
COPY capability_check.py /app/capability_check.py
COPY run.py /app/run.py
COPY entrypoint.sh /app/entrypoint.sh
COPY cde_progress.py /app/cde_progress.py
COPY metric_classes.py /app/metric_classes.py
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
ENV PYTHONPATH=/app
RUN python3 /app/capability_check.py
COPY action_launcher.py /app/action_launcher.py
RUN python3 --version && python3 -c "import klayout.db"
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "-u", "/app/run.py"]
