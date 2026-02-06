FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir discord.py openai python-dotenv requests feedparser twitchio==2.10.0

COPY shared ./shared
COPY bots/deadpool/main.py .
COPY bots/deadpool/main_twitch.py .

CMD ["python", "main.py"]
