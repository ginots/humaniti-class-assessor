FROM python:3.14-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 BROWSER_ASSET_DIR=/app/browser-assets HOST=0.0.0.0 PORT=8000
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY scripts/prepare_browser_assets.py ./scripts/prepare_browser_assets.py
RUN python scripts/prepare_browser_assets.py
COPY assessment.py server.py ./
COPY static ./static
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["python", "server.py"]
