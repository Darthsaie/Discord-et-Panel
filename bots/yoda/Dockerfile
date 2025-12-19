FROM python:3.11-slim

WORKDIR /app

# Installation des outils système
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Copie des fichiers (Yoda)
COPY bots/yoda/main.py .
COPY shared ./shared
COPY .env .env

# Installation des dépendances
RUN pip install discord.py openai python-dotenv requests feedparser

CMD ["python", "main.py"]