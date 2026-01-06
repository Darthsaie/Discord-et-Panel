import os
import json
import random
import asyncio
from datetime import datetime, timedelta
from openai import OpenAI

class TwitchAutoMessages:
    def __init__(self, bot_key, panel_url, panel_token):
        self.bot_key = bot_key
        self.panel_url = panel_url
        self.panel_token = panel_token
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.auto_messages_enabled = False
        self.message_interval = 30  # minutes
        self.last_auto_message = {}
        self.default_messages = [
            "Le chat est calme... trop calme.",
            "Deadpool est là, mais vous êtes où ?"
        ]

    async def load_config_from_panel(self):
        """Charge la configuration depuis le panel"""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                url = f"{self.panel_url}/api/bot/auto-messages/{self.bot_key}"
                async with session.get(url, params={"token": self.panel_token}) as resp:
                    if resp.status == 200:
                        config = await resp.json()
                        self.auto_messages_enabled = config.get("enabled", False)
                        self.message_interval = config.get("interval", 30)
                        return config
        except Exception as e:
            print(f"⚠️ Erreur chargement config auto-messages: {e}")
            return None

    async def generate_ai_message(self, channel_name, viewer_count, stream_title):
        """Génère une annonce de viewers avec le style Deadpool"""
        try:
            # On s'assure d'avoir un nombre
            count = viewer_count if viewer_count is not None else 0
            
            prompt = f"""
Tu es Deadpool, sur le chat Twitch de la chaîne "{channel_name}".
Tâche : Annonce le nombre actuel de viewers ({count}) aux spectateurs.

Contraintes :
1. Tu DOIS mentionner le chiffre {count} explicitement.
2. Sois drôle, brise le 4ème mur.
3. Si le chiffre est bas, moque-toi gentiment. S'il est haut, sois faussement impressionné.
4. Fais court (une seule phrase).
"""
            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.8
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"⚠️ Erreur IA: {e}")
            return f"Deadpool ici : On est {viewer_count or 0} à regarder ce massacre !"

    def should_send_message(self, channel_id):
        """Vérifie si on doit envoyer un message auto"""
        if not self.auto_messages_enabled:
            return False
            
        now = datetime.now()
        last_time = self.last_auto_message.get(channel_id)
        
        if not last_time:
            return True
            
        time_diff = now - last_time
        return time_diff.total_seconds() >= (self.message_interval * 60)

    async def send_auto_message(self, channel_name, channel_id, viewer_count=None, stream_title=None):
        """Envoie un message automatique"""
        if not self.should_send_message(channel_id):
            return False
            
        try:
            message = await self.generate_ai_message(channel_name, viewer_count, stream_title)
            
            self.last_auto_message[channel_id] = datetime.now()
            return message
            
        except Exception as e:
            print(f"⚠️ Erreur envoi message auto: {e}")
            return None