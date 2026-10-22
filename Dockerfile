FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt && \
    find /usr/local -name "moment*.min.js" -exec sed -i '/sourceMappingURL=.*\.map/d' {} + 2>/dev/null || true && \
    python -c 'import os, flower; p = os.path.join(os.path.dirname(flower.__file__), "static", "js"); dummy = b"{\"version\":3,\"file\":\"moment.min.js\",\"sources\":[],\"mappings\":\"\"}"; open(os.path.join(p, "moment.min.js.map"), "wb").write(dummy); open(os.path.join(p, "moment-2.29.4.min.js.map"), "wb").write(dummy)' 2>/dev/null || true



# Copy application source code
COPY . .

# Create storage directories
RUN mkdir -p /app/storage/uploads /app/storage/artifacts /app/storage/thumbnails

EXPOSE 5001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5001"]
