FROM python:3.11-slim

# Set timezone & working directory
ENV TZ=Asia/Jakarta
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies if any needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# Install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

EXPOSE 3114

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "3114"]
