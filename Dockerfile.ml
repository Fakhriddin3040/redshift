# Image for the data and ML pipeline (ml/run_all.py). The repository is mounted
# at /app when it runs, so the results land in the working tree and are picked up
# by the application images built afterwards.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=300 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    MPLCONFIGDIR=/tmp/matplotlib \
    HOME=/tmp

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /bin/uv

WORKDIR /deps
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group ml --no-install-project \
    && chmod -R a+rX /opt/venv

WORKDIR /app
CMD ["python", "-m", "ml.run_all"]
