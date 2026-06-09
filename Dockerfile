FROM node:24-bookworm-slim

WORKDIR /app

ENV NODE_ENV=production \
    PORT=10000 \
    PYTHON=/usr/bin/python3

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*

COPY package.json ./
COPY public ./public
COPY scripts ./scripts
COPY server.js ./

EXPOSE 10000
CMD ["node", "server.js"]
