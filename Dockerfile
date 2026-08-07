FROM python:3.12-slim

# PYTHONUNBUFFERED es imprescindible: sin él, los logs de la app se quedan en el
# buffer de stdout y `docker logs` no muestra nada hasta que se llena. Sería
# repetir exactamente el punto ciego que costó horas de diagnóstico en Render.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Las dependencias en una capa aparte: cambiar el .py no reinstala todo.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY instagram_autorespuesta.py .

# Sin root dentro del contenedor: si alguien encuentra un agujero en Flask, no
# aterriza como root.
RUN useradd --create-home --uid 10001 bot
USER bot

EXPOSE 8000

# Mismos flags de logging que el Procfile de Render, por la misma razón.
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "instagram_autorespuesta:app"]
