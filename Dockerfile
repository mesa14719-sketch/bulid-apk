FROM python:3.11-slim

# Java 21 (Debian Trixie لا يدعم Java 17)
RUN apt-get update && apt-get install -y \
    openjdk-21-jre-headless \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
ENV PATH=$JAVA_HOME/bin:$PATH

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .
COPY APKPatcher.jar .

RUN mkdir -p sessions custom_files

ENV PYTHONUNBUFFERED=1

CMD ["python", "bot.py"]
