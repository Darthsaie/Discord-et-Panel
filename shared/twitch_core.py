import os
import aiohttp
import asyncio
from twitchio.ext import commands
from openai import OpenAI

class TwitchBot(commands.Bot):
    def __init__(self, bot_key, system_prompt):
        # On récupère les clés depuis les variables d'environnement
        self.client_id = os.getenv("TWITCH_CLIENT_ID")
        self.client_secret = os.getenv("TWITCH_CLIENT_SECRET")
        self.bot_key = bot_key
        self.system_prompt = system_prompt
        
        # API Panel & OpenAI
        self.panel_url = os.getenv("PANEL_API_URL", "http://bots-panel:5000")
        self.panel_token = os.getenv("PANEL_API_TOKEN")
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        # Liste des chaînes rejointes
        self.joined_channels = set()

        # Initialisation Twitch
        super().__init__(
            token=os.getenv("TWITCH_OAUTH_TOKEN", "access_token_will_be_handled_internally"), # TwitchIO gère le refresh si on donne ID/Secret
            client_id=self.client_id,
            client_secret=self.client_secret,
            prefix='!',
            initial_channels=[]
        )

    async def event_ready(self):
        print(f"🟣 [{self.bot_key.upper()}] Connecté à Twitch en tant que {self.nick}")
        # Lancer la boucle de vérification des abonnements
        self.loop.create_task(self.sync_channels_loop())

    async def sync_channels_loop(self):
        """Vérifie toutes les 60s sur le Panel quels chaînes rejoindre"""
        while True:
            try:
                url = f"{self.panel_url}/api/bot/config/{self.bot_key}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params={"token": self.panel_token}) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            allowed = set(data.get("allowed_twitch_channels", []))
                            
                            # Celles qu'on doit rejoindre
                            to_join = list(allowed - self.joined_channels)
                            # Celles qu'on doit quitter
                            to_part = list(self.joined_channels - allowed)
                            
                            if to_join:
                                print(f"➕ [{self.bot_key}] Rejoint : {to_join}")
                                await self.join_channels(to_join)
                                self.joined_channels.update(to_join)
                                
                            if to_part:
                                print(f"➖ [{self.bot_key}] Quitte : {to_part}")
                                await self.part_channels(to_part)
                                self.joined_channels.difference_update(to_part)
                                
            except Exception as e:
                print(f"⚠️ Erreur Sync Twitch : {e}")
            
            await asyncio.sleep(60)

    async def event_message(self, message):
        # Ignorer ses propres messages
        if message.echo: return

        # Logique simple : Si on mentionne le bot ou un mot clé
        # Tu peux adapter ici : répondre à tout, ou seulement si mentionné
        trigger_words = [self.nick.lower(), self.bot_key.lower()]
        content = message.content.lower()
        
        should_reply = any(w in content for w in trigger_words)

        if should_reply:
            response = self.ask_gpt(message.content, message.author.name)
            await message.channel.send(f"@{message.author.name} {response}")

    def ask_gpt(self, user_msg, user_name):
        try:
            # On injecte le nom de l'utilisateur pour que l'IA soit plus personnelle
            prompt = f"{self.system_prompt}\n(Tu parles à {user_name} sur un chat Twitch. Sois bref (max 2 phrases).)"
            
            res = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_msg}
                ],
                max_tokens=100,
                temperature=0.8
            )
            return res.choices[0].message.content.strip()
        except Exception as e:
            print(f"Erreur GPT: {e}")
            return "Oups, mon cerveau a lagué !"