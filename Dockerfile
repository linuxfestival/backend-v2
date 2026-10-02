FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python manage.py check

RUN addgroup --system django \
    && adduser --system --ingroup django django \
    && mkdir -p /app/static /app/media \
    && chown -R django:django /app \
    && chmod +x /app/entrypoint.sh

USER django

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/schema/', timeout=3)" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
