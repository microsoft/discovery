# Use Azure Linux 3 with Python 3.12
FROM mcr.microsoft.com/azurelinux/base/python:3.12

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies using tdnf (Azure Linux 3 package manager)
RUN tdnf update -y && tdnf install -y \
    python3-pip \
    shadow-utils \
    ca-certificates \
    && tdnf clean all

# Create requirements.txt for Python dependencies
COPY requirements.txt .

# Install Python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy the Python script and startup script
COPY run.py .
COPY start.sh .

# Make the scripts executable
RUN chmod +x run.py start.sh

# Create a non-root user for security
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
# USER appuser

# Expose common ports (adjust as needed)
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python3 -c "import pymongo; print('OK')" || exit 1

# Default command (can be overridden)
CMD ["./start.sh"]