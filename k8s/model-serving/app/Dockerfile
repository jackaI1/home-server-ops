# Small image for the stub model server. It runs as a fixed non-root user.
FROM python:3.12-slim

RUN useradd --uid 10001 --no-create-home app
WORKDIR /srv
COPY server.py .

ENV PORT=8080 \
    MODEL_LOAD_SECONDS=2 \
    PYTHONUNBUFFERED=1
USER 10001
EXPOSE 8080
ENTRYPOINT ["python", "/srv/server.py"]
