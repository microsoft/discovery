FROM python:3.12-slim
WORKDIR /app
COPY app.py /app/app.py
COPY demo.py /app/demo.py
COPY routes.py /app/routes.py
COPY server.py /app/server.py
RUN pip install fastapi fastmcp sse-starlette uvicorn
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
EXPOSE 5000
CMD ["python", "server.py"]
