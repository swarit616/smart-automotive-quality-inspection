FROM node:22-alpine AS build
WORKDIR /web
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
# nginx image renders /etc/nginx/templates/*.template with envsubst at start-up (API_KEY, BACKEND_URL)
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /web/dist /usr/share/nginx/html
ENV BACKEND_URL=http://backend:8000
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=4s --retries=3 CMD wget -qO- http://127.0.0.1/health || exit 1
