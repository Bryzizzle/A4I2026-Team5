FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt /srv/frontend/requirements.txt
RUN pip install --no-cache-dir -r /srv/frontend/requirements.txt
COPY . /srv/frontend/
ENV PYTHONUNBUFFERED=1
# --loop asyncio: Google's async clients can fail an internal assert under uvloop.
CMD exec uvicorn frontend.app:app --host 0.0.0.0 --port ${PORT:-8080} --loop asyncio --timeout-keep-alive 75
