ARG BASE_UV_IMAGE=ghcr.io/astral-sh/uv:debian-slim
ARG BASE_PYTHON_IMAGE=python:3.13-slim

FROM ${BASE_UV_IMAGE} AS uv

FROM ${BASE_PYTHON_IMAGE}

# Set the working directory in the container
WORKDIR /app

# Runtime + build deps:
# - libgl1/libglib2.0-0: opencv-python runtime
# - gcc/pkg-config/libcairo2-dev: native build dependencies used by some wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    pkg-config \
    libcairo2-dev \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy uv binaries from upstream image instead of curl installer
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=uv /uvx /usr/local/bin/uvx

# Keep Python behavior deterministic in containers
ENV PYTHONUNBUFFERED=1
ENV LUMINA_HOST=0.0.0.0
ENV UV_LINK_MODE=copy
ENV UV_PYTHON_DOWNLOADS=never

# Install dependencies first for better layer cache hit ratio
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Copy application sources
COPY . .

# Use the synced virtualenv by default
ENV PATH="/app/.venv/bin:${PATH}"

# Expose Gradio port
EXPOSE 7860

CMD ["python", "main.py"]
