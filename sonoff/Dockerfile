# Dockerfile to containerize the temperature-corrector script
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_PORT=8080

WORKDIR /app

# Install minimal system deps (needed by some Python packages)
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy source code
COPY src /app

# Expose Flask port for health checks
EXPOSE 8080

CMD ["python", "temperature-corrector.py"]
