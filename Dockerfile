# Python service image — used by both `api` and `app` services.
# CMD is not set here; docker-compose overrides per service.
FROM python:3.13-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install deps before copying source so this layer is cached between code changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Copy source
COPY . .

# Install the project itself (editable not needed in containers)
RUN uv sync --frozen --no-dev
