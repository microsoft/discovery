FROM python:3.12-slim

# System updates
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Create directories
RUN mkdir -p /app /output /input

# Install Python packages
RUN pip install --no-cache-dir \
    numpy==1.26.4 \
    scipy==1.14.1 \
    statsmodels==0.14.4 \
    scikit-learn==1.5.2 \
    pandas==2.2.3 \
    matplotlib==3.9.3 \
    seaborn==0.13.2 \
    pingouin==0.5.5 \
    plotly==5.24.1 \
    jinja2==3.1.4

# Copy utility library
COPY statagent_utils.py /app/statagent_utils.py

# Set working directory and Python path
WORKDIR /app
ENV PYTHONPATH="/app:${PYTHONPATH}"
ENV PYTHONUNBUFFERED=1

CMD ["python3"]
