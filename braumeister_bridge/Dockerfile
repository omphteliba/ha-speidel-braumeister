ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache python3 py3-aiohttp

COPY app /app

CMD ["python3", "-u", "/app/bridge.py"]
