# The background worker runs from the API image with the `worker` command, so ingestion code,
# models and dependencies are identical in both. Build the API image first:
#   docker build -f services/api/Dockerfile -t blindspot-api .
#   docker build -f services/worker/Dockerfile -t blindspot-worker services/worker
ARG API_IMAGE=blindspot-api:latest
FROM ${API_IMAGE}
HEALTHCHECK NONE
CMD ["worker"]
