# Optional packaging. Native Windows execution is the verified baseline.
FROM python:3.14.5-slim
WORKDIR /app
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt \
    && useradd --uid 10001 --create-home fusewall \
    && mkdir /data && chown fusewall:fusewall /data
COPY --chown=fusewall:fusewall fusewall ./fusewall
USER fusewall
EXPOSE 8765
CMD ["python", "-m", "fusewall", "serve", "--data-dir", "/data", "--host", "0.0.0.0"]
