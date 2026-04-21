# Stage 1: Build Frontend
FROM --platform=$BUILDPLATFORM node:22-slim AS frontend-build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
ARG VITE_APP_TITLE
ENV VITE_APP_TITLE=$VITE_APP_TITLE
ARG VITE_COGNITO_USER_POOL_ID
ENV VITE_COGNITO_USER_POOL_ID=$VITE_COGNITO_USER_POOL_ID
ARG VITE_COGNITO_CLIENT_ID
ENV VITE_COGNITO_CLIENT_ID=$VITE_COGNITO_CLIENT_ID
# Strict memory limit for 1GB container
ENV NODE_OPTIONS="--max-old-space-size=768"
COPY frontend/ .
RUN npm run build

# Stage 2: Backend

FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
# Nginx for proxying, Supervisor for process management
RUN apt-get update && apt-get install -y \
    curl \
    git \
    nginx \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install uv (via pip is easiest)
RUN pip install --no-cache-dir uv

# Copy requirements
COPY backend/requirements.pip requirements.txt

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/migration_agent.py .
COPY backend/gateway_infra_utils.py .


# Copy frontend build
COPY --from=frontend-build /app/dist ./static

# Configure Nginx & Supervisor
# Remove default symlink if exists and copy our config
RUN rm -f /etc/nginx/sites-enabled/default
COPY backend/nginx.conf /etc/nginx/sites-enabled/default
COPY backend/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Expose port 8000 (Nginx)
EXPOSE 8000

ENV PYTHONUNBUFFERED=1

# Command to run Supervisor (which runs Nginx + Python)
CMD ["/usr/bin/supervisord"]
