# Blindspot Lab API + worker image. Build from the repository root:
#   docker build -f services/api/Dockerfile -t blindspot-api .
# The same image runs the API (default), the background worker (`worker`) or one-off CLI commands.
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MODEL_CACHE_DIR=/models \
    LOCAL_STORAGE_DIR=/data/storage

# OCR (tesseract), audio/video (ffmpeg) and slide rendering for previews (LibreOffice Impress).
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr ffmpeg libreoffice-impress fonts-dejavu-core curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app/services/api

# Install pinned dependencies first for layer caching. The application itself is not pip-installed:
# it runs from /app so it can find the migrations, demo pack and evaluation datasets beside it.
COPY services/api/pyproject.toml ./pyproject.toml
ARG INSTALL_EVAL=false
RUN python - <<'PY' > /tmp/requirements.txt
import os, tomllib
p = tomllib.load(open("pyproject.toml", "rb"))["project"]
deps = list(p["dependencies"])
if os.environ.get("INSTALL_EVAL", "false") == "true":
    deps += p["optional-dependencies"]["eval"]
print("\n".join(deps))
PY
RUN pip install -r /tmp/requirements.txt

COPY services/api/ ./
COPY database/ /app/database/
COPY demo/course-materials/ /app/demo/course-materials/
COPY evaluation/datasets/ /app/evaluation/datasets/
COPY evaluation/scripts/ /app/evaluation/scripts/

# Bake the local models into the image so the first upload does not wait for downloads.
ARG PRELOAD_MODELS=true
RUN if [ "$PRELOAD_MODELS" = "true" ]; then python -m app.cli warm-models; fi

RUN useradd --create-home --uid 10001 blindspot \
 && mkdir -p /data/storage /models \
 && chown -R blindspot:blindspot /data /models /app
USER blindspot

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD curl -fsS "http://localhost:${PORT:-8000}/api/health" || exit 1
ENTRYPOINT ["/app/services/api/docker-entrypoint.sh"]
CMD ["api"]
