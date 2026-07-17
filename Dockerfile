# Use official lightweight Python image
FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies (build tools for numpy/scikit-learn if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir pymongo dnspython

# Copy project files
COPY . .

# Expose FastAPI service port
EXPOSE 8000

# Execute server command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
