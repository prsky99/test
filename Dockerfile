FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -r -u 10001 app && mkdir -p /data && chown app /data
COPY agent_market ./agent_market
USER app
ENV GATEWAY_DB=/data/gateway.sqlite3 HOST=0.0.0.0 PORT=8200
EXPOSE 8200
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8200/health')"
CMD ["python", "-m", "agent_market.gateway.server"]
