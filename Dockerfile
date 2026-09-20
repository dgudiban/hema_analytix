# Dockerfile for Hugging Face Spaces (Docker SDK).
# HF Spaces runs the container on port 7860.
FROM python:3.11-slim

WORKDIR /app

# Tesseract powers the OCR path for scanned PDFs and report images.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7860

WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
