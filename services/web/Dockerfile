# syntax=docker/dockerfile:1
# BR5 (docs/38): install keyed on package.json+lock; src COPY after pnpm install.
# deps stage = pnpm install only (anchored as agent-platform-web:deps).

FROM node:20-alpine AS deps
# Keep monorepo-relative imports working (planSuggest → packages/contracts/...)
WORKDIR /workspace
# Default: China npm mirror. CI overrides to registry.npmjs.org (npmmirror hangs
# on GitHub-hosted runners and can burn the full 2h job budget).
ARG NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
ENV NPM_CONFIG_REGISTRY=${NPM_CONFIG_REGISTRY} \
    # npmmirror 偶发 502/超时：多试几次，仍失败再回退官方源
    PNPM_FETCH_RETRIES=5 \
    PNPM_FETCH_RETRY_MINTIMEOUT=20000 \
    PNPM_FETCH_RETRY_MAXTIMEOUT=120000 \
    PNPM_NETWORK_CONCURRENCY=8
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate
COPY packages/contracts/plan_suggest /workspace/packages/contracts/plan_suggest
COPY services/web/package.json services/web/pnpm-lock.yaml /workspace/services/web/
WORKDIR /workspace/services/web
# BuildKit store cache: if deps layer is GC'd and re-RUN, packages stay local.
# Primary registry (often npmmirror) → on failure fall back to registry.npmjs.org.
RUN --mount=type=cache,id=pnpm-store,target=/root/.local/share/pnpm/store \
    set -eux; \
    if pnpm install --frozen-lockfile; then \
      echo "deps: pnpm install ok via ${NPM_CONFIG_REGISTRY}"; \
    else \
      echo "deps: primary registry failed → fallback https://registry.npmjs.org"; \
      NPM_CONFIG_REGISTRY=https://registry.npmjs.org pnpm install --frozen-lockfile; \
    fi

FROM deps AS builder
COPY services/web/index.html services/web/vite.config.ts services/web/tsconfig.json ./
COPY services/web/tailwind.config.js services/web/postcss.config.js ./
COPY services/web/public ./public
COPY services/web/src ./src
RUN ./node_modules/.bin/vite build

FROM nginx:alpine
COPY services/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /workspace/services/web/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
