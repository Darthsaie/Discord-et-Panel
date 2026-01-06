FROM python:3.11-slim

WORKDIR /app

# On installe les outils système de base
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# On installe les librairies Python
# AJOUT DE 'feedparser' ICI vvv
RUN pip install discord.py openai python-dotenv requests feedparser twitchio==2.10.0

# On copie le code
COPY shared ./shared
COPY bots/deadpool/main.py .
COPY bots/deadpool/main_twitch.py .
COPY .env .env

CMD ["python", "main.py"]