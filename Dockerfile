FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

# libexpat1 : requise par osmium (src/initialize.py), absente de python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY lib/ lib/
COPY src/ src/
COPY assets/ assets/
COPY migrations/ migrations/
COPY alembic.ini .

RUN useradd --create-home --uid 1000 mysncf && chown -R mysncf:mysncf /app
USER mysncf

EXPOSE 8050

# Un seul worker et pas de --preload : le thread qui charge les horaires en mémoire démarre dans le worker
CMD ["gunicorn", "--chdir", "/app", "--pythonpath", "/app/src", "--workers", "1", "--threads", "8", "--timeout", "300", "--bind", "0.0.0.0:8050", "app:server"]
