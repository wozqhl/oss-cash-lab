# stdlib-only Python image; bind 0.0.0.0; USER 65532
FROM python:3.12-alpine
WORKDIR /app
RUN adduser -D -u 65532 -H app
COPY --chown=65532:65532 pyproject.toml README.md ./
COPY --chown=65532:65532 src ./src
COPY --chown=65532:65532 config.example.json ./config.example.json
COPY --chown=65532:65532 openapi ./openapi
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV FEISHU_VERIFY_TOKEN=mvp-token
ENV FEISHU_ENCRYPT_KEY=mvp-encrypt
ENV DINGTALK_TOKEN=mvp-dt-token
ENV DINGTALK_SECRET=mvp-dt-secret
ENV WECOM_TOKEN=mvp-wc-token
RUN mkdir -p /app/data && chown 65532:65532 /app/data
USER 65532
EXPOSE 8790
# image HEALTHCHECK → /health (liveness; not /ready — drain/circuit/queue would flap)
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8790/health || exit 1
CMD ["python", "-m", "cn_work_agent", "serve", "--host", "0.0.0.0", "--port", "8790", "--config", "config.example.json", "--audit", "data/audit.jsonl"]
