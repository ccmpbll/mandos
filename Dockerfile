FROM python:3.12-slim
ARG VERSION=dev
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MANDOS_DB=/data/mandos.db MANDOS_JOBS=/data/jobs MANDOS_VERSION=${VERSION}
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/* \
 && (useradd -u 99 -g 100 -M -d /opt/mandos mandos 2>/dev/null || useradd -M -d /opt/mandos mandos)
WORKDIR /opt/mandos
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py start.sh ./
COPY static ./static
COPY examples ./examples
COPY tools ./tools
RUN mkdir -p /data && chown -R 99:100 /data
USER 99:100
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=4)"
ENTRYPOINT ["/opt/mandos/start.sh"]
