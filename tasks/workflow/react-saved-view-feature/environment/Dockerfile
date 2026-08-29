FROM studio-moser/harness-testing-node:0.1.0

COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

COPY . .
