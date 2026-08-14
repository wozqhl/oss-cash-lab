# stdlib-only Node image; bind 0.0.0.0; USER node
FROM node:20-alpine
WORKDIR /app
COPY --chown=node:node package.json ./
COPY --chown=node:node src ./src
COPY --chown=node:node config ./config
COPY --chown=node:node openapi ./openapi
ENV NODE_ENV=production
RUN mkdir -p /app/data && chown node:node /app/data
USER node
EXPOSE 8787
# image HEALTHCHECK → /health (liveness; not /ready — drain/circuit/queue would flap)
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8787/health || exit 1
CMD ["node", "src/cli.js", "serve", "--host", "0.0.0.0", "--port", "8787", "--config", "config/policy.compose.json", "--audit", "data/audit.jsonl"]
