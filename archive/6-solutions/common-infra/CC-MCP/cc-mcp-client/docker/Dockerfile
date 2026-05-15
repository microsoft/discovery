FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir requests pyyaml

# Copy files
COPY entrypoint.py /app/entrypoint.py
COPY tool-definition.yaml /app/tool-definition.yaml
COPY start.sh /app/start.sh

RUN cd /app && \
    chmod +x entrypoint.py && \
    chmod +x /app/start.sh

#ENTRYPOINT ["python", "/app/entrypoint.py"]
