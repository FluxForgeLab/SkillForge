FROM node:22-alpine AS build

WORKDIR /src
COPY apps/web/package.json apps/web/pnpm-lock.yaml ./
ARG NPM_CONFIG_REGISTRY=https://registry.npmjs.org
ENV NPM_CONFIG_REGISTRY=${NPM_CONFIG_REGISTRY}
RUN corepack enable && pnpm install --frozen-lockfile
COPY apps/web ./
RUN pnpm build

FROM nginx:alpine
COPY deploy/web.nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html
