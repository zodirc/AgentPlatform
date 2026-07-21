# syntax=docker/dockerfile:1

FROM node:20-alpine AS builder
# Keep monorepo-relative imports working (planSuggest → packages/contracts/...)
WORKDIR /workspace
ARG NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
ENV NPM_CONFIG_REGISTRY=${NPM_CONFIG_REGISTRY}
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate
COPY packages/contracts/plan_suggest /workspace/packages/contracts/plan_suggest
COPY services/web/package.json services/web/pnpm-lock.yaml /workspace/services/web/
WORKDIR /workspace/services/web
RUN pnpm install --frozen-lockfile
COPY services/web/index.html services/web/vite.config.ts services/web/tsconfig.json ./
COPY services/web/tailwind.config.js services/web/postcss.config.js ./
COPY services/web/src ./src
RUN ./node_modules/.bin/vite build

FROM nginx:alpine
COPY services/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /workspace/services/web/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
