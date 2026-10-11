FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# Run unprivileged. Bind-mounted data dirs must be writable by uid 1000 (chown 1000:1000 ./data).
RUN useradd --uid 1000 --create-home vault && mkdir /data && chown vault /data
USER vault

ENV VAULT_DATA_DIR=/data
VOLUME /data
EXPOSE 8420

# One worker: the embedding model and the job thread live in this process.
CMD ["uvicorn", "vault.main:app", "--host", "0.0.0.0", "--port", "8420", "--proxy-headers", "--forwarded-allow-ips", "*"]
