FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

COPY bots/homer/main.py .
COPY shared ./shared

RUN pip install --no-cache-dir discord.py openai python-dotenv requests feedparser

CMD ["python", "main.py"]
