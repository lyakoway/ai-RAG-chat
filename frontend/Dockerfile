# --- Build stage ---
FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# Vite вшивает VITE_* на этапе сборки (как NEXT_PUBLIC_* в lyako-way).
ARG VITE_YANDEX_METRIKA_ID=
ARG VITE_GA4_MEASUREMENT_ID=
ENV VITE_YANDEX_METRIKA_ID=$VITE_YANDEX_METRIKA_ID \
    VITE_GA4_MEASUREMENT_ID=$VITE_GA4_MEASUREMENT_ID
RUN npm run build

# --- Serve stage (nginx serves static build + proxies /api) ---
FROM nginx:1.27-alpine
# Rendered to /etc/nginx/conf.d/default.conf at startup by the nginx
# entrypoint. Only BACKEND_HOSTPORT is substituted, so nginx's own
# $host/$uri/$remote_addr variables in the template are left intact.
ENV BACKEND_HOSTPORT=backend:8000 \
    NGINX_ENVSUBST_FILTER=BACKEND_HOSTPORT
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
