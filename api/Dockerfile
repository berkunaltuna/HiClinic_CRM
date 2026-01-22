FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg (binary wheel usually works; keep build deps minimal)
RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app /app/app
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
COPY entrypoint.sh /app/entrypoint.sh

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

RUN chmod +x /app/entrypoint.sh

CMD ["/app/entrypoint.sh"]
