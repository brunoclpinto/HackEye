# JS gate image for tools/check.sh: pinned node + eslint (tools/js/package.json, package-lock.json). Independent of hackeye-rnd.
# node_modules live in /opt/js, outside the /rnd bind mount; tools/js/eslint.config.js finds them through NODE_PATH.
FROM node:22.23.5-bookworm-slim
WORKDIR /opt/js
COPY tools/js/package.json tools/js/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
ENV NODE_PATH=/opt/js/node_modules PATH=/opt/js/node_modules/.bin:$PATH
WORKDIR /rnd
ENTRYPOINT []
