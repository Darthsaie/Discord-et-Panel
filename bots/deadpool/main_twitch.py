import os
import asyncio
from shared.twitch_core import TwitchBot
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    bot = TwitchBot(
        bot_key="deadpool",
        system_prompt="Tu es Deadpool. Tu brises le 4eme mur. Tu es sarcastique, violent et drôle. Tu te moques des gens tout en leur donnant l'info."
    )
    bot.run()
