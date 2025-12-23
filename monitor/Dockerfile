# Dockerfile to containerize the monitor script (middleware/src/monitor.py)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5050

WORKDIR /app

# Install minimal system deps (needed by some Python packages)
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python deps (include Flask explicitly)
COPY ../requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt flask

# Copy monitor source
COPY src /app

EXPOSE ${PORT}

CMD ["python", "monitor.py"]
