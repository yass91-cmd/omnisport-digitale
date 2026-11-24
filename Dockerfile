FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home appuser

FROM base AS source
COPY backend /app/backend
COPY migrations /app/migrations
COPY alembic.ini /app/alembic.ini
COPY frontend/dist /app/frontend/dist
EXPOSE 8000

FROM base AS test
COPY backend/requirements-dev.txt /app/requirements-dev.txt
RUN python -m pip install --no-cache-dir --timeout 60 --retries 5 -r requirements-dev.txt
COPY --from=source /app/backend /app/backend
COPY --from=source /app/migrations /app/migrations
COPY --from=source /app/alembic.ini /app/alembic.ini
COPY --from=source /app/frontend/dist /app/frontend/dist
COPY tests /app/tests
COPY pyproject.toml /app/pyproject.toml
COPY scripts/smoke.py /app/scripts/smoke.py
CMD ["python", "-m", "pytest"]

FROM source AS runtime
USER 10001
CMD ["python", "-m", "uvicorn", "backend.app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
