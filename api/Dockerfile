FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /srv

# Insurance if any dep lacks a wheel; pysweph ships a 3.13 manylinux wheel so
# this is usually unused at build time.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# App + your engine + the adapter (which carries the pysweph compat shim).
COPY app ./app
COPY engine_app.py maha_jyotish_cloud_engine.py ./

EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY:-1}"]
