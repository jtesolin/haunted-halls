FROM node:24.18.0-bookworm-slim
WORKDIR /app
COPY --chown=node:node responses.ts server.ts ./
COPY --chown=node:node structured-contracts.json ./
USER node
EXPOSE 8080
CMD ["node", "server.ts"]
