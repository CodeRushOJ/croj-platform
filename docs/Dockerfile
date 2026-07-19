FROM node:24.15.0-alpine@sha256:d1b3b4da11eefd5941e7f0b9cf17783fc99d9c6fc34884a665f40a06dbdfc94f AS build
WORKDIR /workspace/docs
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN CODERUSHOJ_DOCS_LAST_UPDATED=false CODERUSHOJ_DOCS_BASE=/ pnpm build

FROM nginxinc/nginx-unprivileged:1.29.4-alpine@sha256:a6c4f61f456b85b8fdf7ec7ab28cc3e299440e6fb4a9dea520e5fd8fd440025e
COPY --from=build /workspace/docs/.vitepress/dist /usr/share/nginx/html
USER 101:101
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --quiet --output-document=- http://127.0.0.1:8080/ >/dev/null || exit 1
EXPOSE 8080
