# Multi-stage image for LifeOS. Build it from a lifeos-open checkout as the context:
#   docker build -f deploy/jenkins/lifeos.Dockerfile -t lifeos:local lifeos-open
#
# Stage 1 installs every dependency, stage 2 runs the bundle build, stage 3 keeps only what the server
# needs at run time and runs as the unprivileged node user.
FROM node:24.11.1-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM deps AS build
COPY . .
RUN npm run build

FROM node:24.11.1-bookworm-slim AS prod-deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

FROM node:24.11.1-bookworm-slim AS runtime
ENV NODE_ENV=production
WORKDIR /app
COPY --from=prod-deps /app/node_modules ./node_modules
COPY --from=build /app/build ./build
COPY --from=build /app/public ./public
COPY --from=build /app/package.json ./package.json
# The server reads its SQL migrations from this folder at start, relative to /app.
COPY --from=build /app/src/storage/migrations ./src/storage/migrations
# LifeOS keeps its state in directories under /app, so the node user must own that folder.
RUN chown node:node /app
USER node
EXPOSE 8787
CMD ["node", "build/server.mjs"]
