FROM python:3.14-slim AS build
WORKDIR /build
COPY requirements.lock .
RUN python -m pip install --no-cache-dir --prefix=/install -r requirements.lock
COPY src ./src
COPY scripts/build.py ./scripts/build.py
RUN python scripts/build.py

FROM python:3.14-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DATA_DIR=/app/storage/data BACKUP_DIR=/app/storage/backups PYTHONPATH=/app/src
WORKDIR /app
COPY --from=build /install /usr/local
COPY --from=build /build/dist/redline.pyz ./redline.pyz
COPY --from=build /build/src ./src
RUN groupadd --gid 10001 bot && useradd --uid 10001 --gid bot --no-create-home bot \
    && mkdir -p /app/storage/data /app/storage/backups && chown -R bot:bot /app/storage
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 CMD ["python", "-m", "redline.health"]
CMD ["python", "redline.pyz"]

