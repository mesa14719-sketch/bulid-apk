FROM python:3.11-slim

# تثبيت Java 17
RUN apt-get update && apt-get install -y \
    openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# تثبيت مكتبات Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ البوت والأداة
COPY bot.py .
COPY APKPatcher.jar .

# مجلدات العمل
RUN mkdir -p sessions custom_files

ENV PYTHONUNBUFFERED=1

CMD ["python", "bot.py"]
