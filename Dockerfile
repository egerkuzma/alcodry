FROM python:3.12-slim

# tzdata нужен zoneinfo: все даты считаются по Europe/Moscow, а в slim-образе
# базы часовых поясов нет.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ALCODRY_DB=/data/tracker.db

WORKDIR /srv

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY conftest.py ./
COPY app ./app
COPY tests ./tests

VOLUME /data
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
