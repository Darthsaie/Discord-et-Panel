import os
import aiohttp
import asyncio
import logging
from twitchio.ext import commands
from openai import OpenAI
from .twitch_auto_messages import TwitchAutoMessages

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
        
        # Système de messages automatiques
        self.auto_messages = TwitchAutoMessages(bot_key, self.panel_url, self.panel_token)
        
        # Liste des chaînes rejointes
        self.joined_channels = set()

        logging.basicConfig(level=logging.INFO)
        logging.getLogger("twitchio").setLevel(logging.INFO)

        print(f"🚀 [{self.bot_key.upper()}] Démarrage bot Twitch (IRC)", flush=True)

        token = os.getenv(f"TWITCH_OAUTH_TOKEN_{self.bot_key.upper()}") or os.getenv("TWITCH_OAUTH_TOKEN")
        if not token:
            raise ValueError(
                "TWITCH_OAUTH_TOKEN manquant (.env). Requis pour Twitch IRC (TwitchIO 2.x). "
            )

        super().__init__(
            token=token,
            prefix='!',
            initial_channels=[]
        )

    async def event_ready(self):
        bot_name = getattr(self, "nick", None) or "Unknown"
        print(f"🟣 [{self.bot_key.upper()}] Connecté à Twitch en tant que {bot_name}", flush=True)
        
        # Charger la configuration initiale
        await self.auto_messages.load_config_from_panel()
        
        # Lancer les boucles
        asyncio.create_task(self.sync_channels_loop())
        asyncio.create_task(self.auto_messages_loop())
        asyncio.create_task(self.scheduled_tasks_loop())

    async def sync_channels_loop(self):
        while True:
            try:
                url = f"{self.panel_url}/api/bot/config/{self.bot_key}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params={"token": self.panel_token}) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            allowed = {str(x).strip().lower() for x in data.get("allowed_twitch_channels", []) if str(x).strip()}

                            to_join = list(allowed - self.joined_channels)
                            to_part = list(self.joined_channels - allowed)
                            
                            if to_join:
                                print(f"➕ [{self.bot_key}] Rejoint : {to_join}", flush=True)
                                await self.join_channels(to_join)
                                self.joined_channels.update(to_join)
                                
                            if to_part:
                                print(f"➖ [{self.bot_key}] Quitte : {to_part}", flush=True)
                                await self.part_channels(to_part)
                                self.joined_channels.difference_update(to_part)
            except Exception as e:
                print(f"⚠️ Erreur Sync Twitch : {e}", flush=True)
            
            await asyncio.sleep(60)

    async def event_message(self, message):
        if message.echo: return
        # print(f"💬 [{self.bot_key}] #{message.channel.name} {message.author.name}: {message.content}")

        trigger_words = [self.nick.lower(), self.bot_key.lower()]
        content = message.content.lower()
        should_reply = any(w in content for w in trigger_words)

        if should_reply:
            response = self.ask_gpt(message.content, message.author.name)
            await message.channel.send(f"@{message.author.name} {response}")

    def ask_gpt(self, user_msg, user_name):
        try:
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

    async def auto_messages_loop(self):
        """Boucle de messages automatiques"""
        while True:
            try:
                # --- RECHARGEMENT CONFIG DYNAMIQUE ---
                await self.auto_messages.load_config_from_panel()
                
                # Si désactivé, on attend juste 1 minute avant de revérifier la config
                if not self.auto_messages.auto_messages_enabled:
                    await asyncio.sleep(60)
                    continue

                for channel_id in self.joined_channels:
                    try:
                        channel = self.get_channel(channel_id)
                        if channel:
                            # Tenter d'envoyer le message viewer count
                            message = await self.auto_messages.send_auto_message(
                                channel.name, 
                                channel_id,
                                viewer_count=getattr(channel, 'viewer_count', None),
                                stream_title=getattr(channel, 'title', None)
                            )
                            
                            if message:
                                await channel.send(message)
                                print(f"🤖 [{self.bot_key.upper()}] Annonce viewers sur {channel.name}: {message}")
                    except Exception as e:
                        print(f"⚠️ Erreur message auto sur {channel_id}: {e}")
                        
            except Exception as e:
                print(f"⚠️ Erreur boucle messages auto: {e}")
            
            # Attente de sécurité (boucle principale)
            await asyncio.sleep(60)

    async def scheduled_tasks_loop(self):
        """Boucle pour exécuter les tâches planifiées depuis le Panel (Table SQL)"""
        # Cette boucle gère les tâches uniques, pas la récurrence automatique configurée ci-dessus
        while True:
            try:
                url = f"{self.panel_url}/api/bot/tasks/{self.bot_key}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params={"token": self.panel_token}) as resp:
                        if resp.status == 200:
                            tasks = await resp.json()
                            # ... logique tâches SQL existante (non utilisée pour l'auto-message viewers) ...
            except Exception as e:
                print(f"⚠️ Erreur boucle tâches planifiées: {e}")
            await asyncio.sleep(300)