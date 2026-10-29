# One generic image recipe for every Python service.
# Build context = ./backend ; choose the service with --build-arg SERVICE_DIR=services/<name> (or gateway, scripts)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/srv
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared ./shared
ARG SERVICE_DIR
COPY ${SERVICE_DIR} ./service
COPY infra/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
WORKDIR /srv/service
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
