import os
import aiohttp
import asyncio
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

        # Obtenir ou utiliser le token OAuth
        token = os.getenv("TWITCH_OAUTH_TOKEN")
        if not token:
            print("⚠️ TWITCH_OAUTH_TOKEN non défini, utilisation de l'authentification automatique...")
            # TwitchIO peut gérer l'auth avec client_id/secret
            token = None

        # Initialisation Twitch
        super().__init__(
            token=token,  # Token OAuth ou None pour auth auto
            client_id=self.client_id,
            client_secret=self.client_secret,
            bot_id=os.getenv("TWITCH_BOT_ID"),  # Ajout du bot_id requis
            prefix='!',
            initial_channels=[]
        )

    async def event_ready(self):
        bot_name = getattr(self.user, 'name', 'Unknown') if self.user else 'Unknown'
        print(f"🟣 [{self.bot_key.upper()}] Connecté à Twitch en tant que {bot_name}")
        
        # Charger la configuration des messages automatiques
        await self.auto_messages.load_config_from_panel()
        
        # Lancer la boucle de vérification des abonnements
        asyncio.create_task(self.sync_channels_loop())
        
        # Lancer la boucle de messages automatiques
        asyncio.create_task(self.auto_messages_loop())
        
        # Lancer la boucle de tâches planifiées
        asyncio.create_task(self.scheduled_tasks_loop())

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
                                try:
                                    await self.join_channels(to_join)
                                    self.joined_channels.update(to_join)
                                except AttributeError:
                                    # Si join_channels n'existe pas, essayer une autre méthode
                                    print(f"⚠️ join_channels non disponible, tentative alternative...")
                                    for channel_id in to_join:
                                        try:
                                            # Essayer de rejoindre avec le nom de chaîne
                                            channel = self.get_channel(channel_id)
                                            if channel:
                                                print(f"✅ Canal {channel_id} trouvé et rejoint")
                                                self.joined_channels.add(channel_id)
                                            else:
                                                print(f"⚠️ Canal {channel_id} non trouvé")
                                        except Exception as e:
                                            print(f"⚠️ Erreur canal {channel_id}: {e}")
                                
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

    async def auto_messages_loop(self):
        """Boucle de messages automatiques toutes les X minutes"""
        while True:
            try:
                # Parcourir toutes les chaînes rejointes
                for channel_id in self.joined_channels:
                    try:
                        # Récupérer les infos de la chaîne
                        channel = self.get_channel(channel_id)
                        if channel:
                            # Envoyer un message automatique
                            message = await self.auto_messages.send_auto_message(
                                channel.name, 
                                channel_id,
                                viewer_count=getattr(channel, 'viewer_count', None),
                                stream_title=getattr(channel, 'title', None)
                            )
                            
                            if message:
                                await channel.send(message)
                                print(f"🤖 [{self.bot_key.upper()}] Message auto sur {channel.name}: {message}")
                                
                    except Exception as e:
                        print(f"⚠️ Erreur message auto sur {channel_id}: {e}")
                        
            except Exception as e:
                print(f"⚠️ Erreur boucle messages auto: {e}")
            
            # Attendre avant le prochain cycle
            await asyncio.sleep(self.auto_messages.message_interval * 60)

    async def scheduled_tasks_loop(self):
        """Boucle pour exécuter les tâches planifiées depuis le Panel"""
        while True:
            try:
                # Récupérer les tâches planifiées pour ce bot
                url = f"{self.panel_url}/api/bot/tasks/{self.bot_key}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params={"token": self.panel_token}) as resp:
                        if resp.status == 200:
                            tasks = await resp.json()
                            
                            # Traiter chaque tâche
                            for task in tasks:
                                if task.get("task_type") == "auto_messages":
                                    await self.handle_auto_messages_task(task)
                                elif task.get("task_type") == "news":
                                    await self.handle_news_task(task)
                                elif task.get("task_type") == "meteo":
                                    await self.handle_meteo_task(task)
                                elif task.get("task_type") == "meme":
                                    await self.handle_meme_task(task)
                        
            except Exception as e:
                print(f"⚠️ Erreur boucle tâches planifiées: {e}")
            
            # Vérifier toutes les 5 minutes
            await asyncio.sleep(300)

    async def handle_auto_messages_task(self, task):
        """Gère une tâche de messages automatiques"""
        try:
            task_param = task.get("task_param", "")
            if not task_param:
                return
                
            # Trouver la chaîne correspondante
            target_channel_id = task_param
            channel = self.get_channel(target_channel_id)
            
            if channel:
                # Envoyer un message automatique sur cette chaîne
                message = await self.auto_messages.send_auto_message(
                    channel.name,
                    target_channel_id,
                    viewer_count=getattr(channel, 'viewer_count', None),
                    stream_title=getattr(channel, 'title', None)
                )
                
                if message:
                    await channel.send(message)
                    print(f"🤖 [{self.bot_key.upper()}] Message planifié sur {channel.name}: {message}")
                    
        except Exception as e:
            print(f"⚠️ Erreur tâche auto-messages: {e}")

    async def handle_news_task(self, task):
        """Gère une tâche de news"""
        # Implémenter la logique pour les news RSS
        print(f"📰 [{self.bot_key.upper()}] Tâche news non implémentée")

    async def handle_meteo_task(self, task):
        """Gère une tâche de météo"""
        # Implémenter la logique pour la météo
        print(f"☁️ [{self.bot_key.upper()}] Tâche météo non implémentée")

    async def handle_meme_task(self, task):
        """Gère une tâche de meme"""
        # Implémenter la logique pour les memes
        print(f"😂 [{self.bot_key.upper()}] Tâche meme non implémentée")