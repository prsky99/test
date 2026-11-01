FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements-storage-postgres.txt requirements-runtime.lock requirements-build.lock ./
RUN apt-get update \
    && apt-get install --no-install-recommends --yes build-essential libpq-dev \
    && apt-mark manual libpq5 \
    && python -m pip install --no-cache-dir --require-hashes -r requirements-build.lock \
    && python -m pip install --no-cache-dir --require-hashes --no-build-isolation -r requirements-runtime.lock \
    && python -m pip uninstall --yes setuptools wheel packaging \
    && python -m pip check \
    && apt-get purge --yes --auto-remove build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -u 10001 app && mkdir -p /data && chown app /data
COPY agent_market ./agent_market
COPY scripts/audit_stored_tokens.py ./scripts/audit_stored_tokens.py
USER app
ENV GATEWAY_DB=/data/gateway.sqlite3 HOST=0.0.0.0 PORT=8200
EXPOSE 8200 8400
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8200/health')"
CMD ["python", "-m", "agent_market.gateway.server"]
