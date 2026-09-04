FROM python:3.12-slim

# System updates
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Create directories
RUN mkdir -p /app /output /input

# Install Python packages (dependency-light: numpy + scipy only)
RUN pip install --no-cache-dir \
    numpy==1.26.4 \
    scipy==1.14.1

# Copy utility library
COPY reverbtrust_utils.py /app/reverbtrust_utils.py

# Set working directory and Python path
WORKDIR /app
ENV PYTHONPATH="/app:${PYTHONPATH}"
ENV PYTHONUNBUFFERED=1

CMD ["python3"]
