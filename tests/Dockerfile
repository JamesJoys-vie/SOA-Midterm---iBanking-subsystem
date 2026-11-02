# Load-test toolbox: seed/reset, Locust, pytest race tests, invariant checker.
# Used by docker-compose.loadtest.yml (profile "loadtest"); ./tests is mounted, so edits need no rebuild.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --retries 10 --timeout 120 -r /tmp/requirements.txt
WORKDIR /tests/load
