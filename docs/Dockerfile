FROM node:24.15.0-alpine AS build
WORKDIR /workspace/docs
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginxinc/nginx-unprivileged:1.29.4-alpine
COPY --from=build /workspace/docs/.vitepress/dist /usr/share/nginx/html
EXPOSE 8080
