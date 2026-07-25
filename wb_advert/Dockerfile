FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY wb_advert/requirements.txt /app/wb_advert/requirements.txt
RUN pip install --no-cache-dir -r /app/wb_advert/requirements.txt

COPY wb_advert /app/wb_advert
COPY data/pilot /app/data/pilot

ENV PYTHONPATH=/app
ENV WB_ADVERT_PILOT_DATA=/app/data/pilot
ENV WB_ADVERT_PILOT_CONFIG=/app/data/pilot/config.yaml

EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://127.0.0.1:8081/api/advert/health || exit 1

CMD ["uvicorn", "wb_advert.app:app", "--host", "0.0.0.0", "--port", "8081"]
