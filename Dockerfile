# Staging image (G2-05, E-49): the API serving the built web app on the same origin.
# Rendering is never done here: clips are made by the customer's Agent (Q-15).
# Build args are public values only (Supabase URL + publishable key); secrets come from the host's env.

FROM node:24-alpine AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_PUBLISHABLE_KEY
ARG VITE_API_URL=same-origin
RUN npm run build

FROM python:3.14-slim AS api
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    WEB_DIST=/app/web APP_ENV=staging
WORKDIR /app
COPY services/api/pyproject.toml services/api/
COPY services/api/clipflow_api services/api/clipflow_api
RUN pip install ./services/api
COPY services/api/alembic.ini services/api/
COPY services/api/migrations services/api/migrations
COPY deploy/start.sh /app/start.sh
COPY --from=web /web/dist /app/web
ARG BUILD_ID=dev
ENV BUILD_ID=${BUILD_ID}
RUN useradd --system --uid 10001 app && chmod 0555 /app/start.sh
USER app
EXPOSE 8000
CMD ["/app/start.sh"]
