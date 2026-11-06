FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY telemetry ./telemetry
CMD ["uvicorn", "telemetry.main:app", "--host", "0.0.0.0", "--port", "8000"]
