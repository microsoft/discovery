FROM python:3.10-slim

WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN python -m pip install -r requirements.txt

# Copy the rest of the application code
COPY . .

# Run the main Python script
CMD ["python", "main.py"]