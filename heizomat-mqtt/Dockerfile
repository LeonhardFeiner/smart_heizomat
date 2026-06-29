# Use a slim Python base image for a small footprint
FROM python:3.11-slim

# 1. Install system-level dependencies
# tesseract-ocr-deu is vital for reading German words like "Sollwerte"
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-deu \
    libglib2.0-0 \
    netpbm \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 2. Set the working directory
WORKDIR /app

# 3. Install Python dependencies
# We copy requirements.txt first to leverage Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy the application
COPY heizomat/ ./heizomat/
COPY app.py .

# Add this near the bottom of your Dockerfile
RUN mkdir -p /app/debug_crops

# 5. Runtime configuration
# Use -u for unbuffered logs so you see them in 'docker logs' instantly
ENV PYTHONUNBUFFERED=1

# 6. Start the script
CMD ["python", "app.py"]