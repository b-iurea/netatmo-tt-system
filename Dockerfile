FROM python:3.12-slim

# Evita bytecode e buffering nei log
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Crea directory dell'app
WORKDIR /app

# Copia solo le dipendenze
COPY requirements.txt /app/

# Installa dipendenze
RUN pip install --no-cache-dir -r requirements.txt

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Copia il resto del codice
COPY ./src /app/

# # Comando di avvio
ENTRYPOINT ["/entrypoint.sh"]