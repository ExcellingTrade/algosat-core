# Multi-stage Docker build for Algosat trading system
FROM python:3.11-slim as base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash algosat
WORKDIR /home/algosat

# Development stage
FROM base as development
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN pip install pytest pytest-asyncio pytest-mock black isort flake8
USER algosat
CMD ["python", "-m", "uvicorn", "api.enhanced_main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# Production build stage
FROM base as builder
COPY requirements.txt .
RUN pip install --user -r requirements.txt

# Production stage
FROM python:3.11-slim as production

# Install runtime dependencies only
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash algosat

# Copy Python packages from builder
COPY --from=builder /root/.local /home/algosat/.local

# Set up application
WORKDIR /home/algosat/app
COPY --chown=algosat:algosat . .

# Set PATH to include user's local bin
ENV PATH=/home/algosat/.local/bin:$PATH

USER algosat

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Run application
CMD ["python", "-m", "uvicorn", "api.enhanced_main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
