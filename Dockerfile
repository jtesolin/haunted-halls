FROM node:24.18.0-bookworm-slim AS dependencies

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:24.18.0-bookworm-slim AS builder

WORKDIR /app
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN GOOGLE_CLIENT_ID=build-only-google-client-id \
	GOOGLE_CLIENT_SECRET=build-only-google-client-secret \
	NEXTAUTH_SECRET=build-only-nextauth-secret \
	npm run build

# Local-only development/debug stage. Must stay before `runner` so plain
# `docker build` and CI keep producing the production image by default.
FROM node:24.18.0-bookworm-slim AS development

ENV NODE_ENV=development
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

WORKDIR /app
COPY --from=dependencies --chown=node:node /app/node_modules ./node_modules
COPY --chown=node:node . .

# `node` is uid 1000, matching the typical WSL developer uid, so bind-mounted
# source stays writable from both sides.
RUN mkdir -p /app/.next && chown -R node:node /app

USER node
EXPOSE 3000 9229
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--inspect=0.0.0.0:9229"]

FROM node:24.18.0-bookworm-slim AS runner

ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

WORKDIR /app
COPY --from=builder --chown=node:node /app/public ./public
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

USER node
EXPOSE 3000
CMD ["node", "server.js"]