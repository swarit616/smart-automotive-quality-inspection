FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY ml ./ml
RUN useradd --create-home --uid 10001 inspector && mkdir -p /app/data /app/models && chown -R inspector /app
USER inspector

ENV DATA_DIR=/app/data MODEL_DIR=/app/models MODEL_WEIGHTS_PATH=/app/models/best.onnx
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
