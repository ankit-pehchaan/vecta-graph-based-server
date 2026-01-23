# Production Dockerfile for Vecta Server
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application code
COPY ./api ./api
COPY ./agents ./agents
COPY ./auth ./auth
COPY ./nodes ./nodes
COPY ./memory ./memory
COPY ./orchestrator ./orchestrator
COPY ./services ./services
COPY ./prompts ./prompts
COPY ./app ./app
COPY ./alembic ./alembic
COPY ./config.py ./config.py
# Copy alembic.ini if it exists (optional)
COPY ./alembic.in[i] ./

# Create logs directory
RUN mkdir -p /app/logs /app/tmp

# Expose port
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:80/health || exit 1

# Run with production settings (no reload)
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "80"]
