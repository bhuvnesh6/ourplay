FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py engine.py ./
COPY static ./static
RUN useradd -m app && mkdir -p /data && chown app /data
USER app
EXPOSE 4449
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request as u;u.urlopen('http://127.0.0.1:4449/health',timeout=3)"
# Single worker: game/presence state lives in-process. Threads handle many sockets.
CMD ["gunicorn","-k","gthread","-w","1","--threads","100","-b","0.0.0.0:4449","--timeout","120","app:app"]
