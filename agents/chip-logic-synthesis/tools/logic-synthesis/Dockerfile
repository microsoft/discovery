FROM docker.io/ghdl/synth:beta
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
RUN python3 --version
RUN ln -s /usr/local/bin/yosys-abc /usr/local/bin/abc
RUN mkdir -p /workdir /input /output /app
COPY logic_synthesis_utils.py /app/logic_synthesis_utils.py
COPY run.py /app/run.py
COPY entrypoint.sh /app/entrypoint.sh
COPY cde_progress.py /app/cde_progress.py
COPY metric_classes.py /app/metric_classes.py
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
ENV PYTHONPATH=/app
COPY action_launcher.py /app/action_launcher.py
RUN python3 --version && command -v yosys >/dev/null && command -v abc >/dev/null && command -v ghdl >/dev/null
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "-u", "/app/run.py"]
