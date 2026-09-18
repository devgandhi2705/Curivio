# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Build React frontend
# ─────────────────────────────────────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# Install dependencies (cached unless package*.json changes)
COPY frontend/package*.json ./
RUN npm ci --silent

# Copy source and build
COPY frontend/ ./

# API_URL is /api so nginx can proxy strip the prefix to the Python backend
ARG VITE_API_URL=/api
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Python runtime + nginx
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Install nginx and curl (curl used in start.sh health wait)
RUN apt-get update && apt-get install -y --no-install-recommends \
        nginx \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies (cached unless requiremnts.txt changes)
COPY requiremnts.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Headless Chromium for feed_v2's visual validator (tier-3 diagram render check).
# --with-deps pulls the shared libs python:3.11-slim lacks (libglib, libnss3, ...);
# --only-shell skips full Chrome. Browsers live outside /root so a non-root runtime
# user (HF Spaces runs uid 1000) can read them. Adds ~766 MB (362 MB apt + 267 MB
# browser + 137 MB pip package, measured 2026-09-18).
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN python -m playwright install --with-deps --only-shell chromium

# Backend source
COPY backend/ ./backend/

# Built frontend (from stage 1)
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# nginx configuration
COPY nginx.conf /etc/nginx/sites-available/default
RUN ln -sf /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default \
    && rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true \
    && cp /etc/nginx/sites-available/default /etc/nginx/conf.d/curivio.conf

# Startup script
COPY start.sh /start.sh
RUN chmod +x /start.sh

# Persistent data directory (HF Spaces mounts /data for persistence)
RUN mkdir -p /data /tmp/curivio

# ── Runtime environment ───────────────────────────────────────────────────────
# Secrets (GROQ_API_KEY, TINYFISH_API_KEY, AUTH_SECRET_KEY) must be set
# via HF Spaces secrets — never baked into the image.

ENV DB_PATH=/data/curivio.db
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# HF Spaces requires port 7860
EXPOSE 7860

CMD ["/start.sh"]
