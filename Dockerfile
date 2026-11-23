# SculptViseme cloud runner.
#
# The same backend that runs locally, packaged for any container
# host. Build and run:
#
#   docker build -t sculptviseme .
#   docker run -p 8077:8077 -e SV_API_TOKEN=<a-secret-you-choose> \
#       -e SV_CORS_ORIGINS=https://your-frontend.example \
#       -v sculptviseme-jobs:/app/var sculptviseme
#
# SV_API_TOKEN is strongly recommended: in cloud mode the service
# is reachable by others, and the token is what keeps job and
# export endpoints private. SV_CORS_ORIGINS lists the web origins
# allowed to call the runner from a browser (comma separated).
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/
COPY assets/ assets/

ENV SV_MODE=cloud \
    PYTHONPATH=/app/backend \
    CSS_JOBS_DIR=/app/var/jobs

EXPOSE 8077
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8077}"]
