FROM mcr.microsoft.com/azurelinux/base/python:3.12 AS base
WORKDIR /app
RUN pip install --no-cache-dir azure-identity azure-ai-ml requests python-dotenv pyyaml
COPY ./app /app/
RUN chmod +x /app/retro.py