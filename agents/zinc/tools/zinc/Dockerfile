FROM python:3.11-slim

LABEL maintainer="Discovery Platform"
LABEL description="ZINC22 / CartBlanche database access agent for molecular structure search and retrieval"

WORKDIR /app

# Install Python dependencies
RUN pip install --no-cache-dir requests==2.33.0

# Copy helper library
COPY zinc_utils.py /app/zinc_utils.py

# Ensure /app is on the Python path so scripts can import zinc_utils
ENV PYTHONPATH=/app:$PYTHONPATH

# Non-root user for security
RUN useradd -m -s /bin/bash zinc_user
USER zinc_user

CMD ["python3"]