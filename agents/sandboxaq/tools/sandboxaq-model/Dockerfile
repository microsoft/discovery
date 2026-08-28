FROM mcr.microsoft.com/azurelinux/base/python:3.12

WORKDIR /app
RUN tdnf -y update && \
    tdnf -y install ca-certificates && \
    update-ca-trust && \
    tdnf clean all
RUN pip3 install --no-cache-dir requests

COPY run_action.py /app/run_action.py
ENTRYPOINT ["python3", "/app/run_action.py"]
