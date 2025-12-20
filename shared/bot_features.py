import os
import requests
import datetime
import discord
import feedparser
import random
import asyncio
from discord import app_commands
from discord.ext import tasks
from shared.bot_core import UltimateBot

# --- IMPORTS DES FONCTIONNALITÉS ---
from shared.debate import run_debate 
from shared.quiz import start_quiz, check_answer, get_top_scores
from shared.recap import generate_recap
from shared.clash import clash_user 

# --- CONFIGURATION API ---
PANEL_API_URL = "http://bots-panel:5000/api/bot/tasks" 
PANEL_API_TOKEN = os.getenv("PANEL_API_TOKEN", "change_me_please")
OPENWEATHER_KEY = "4ab04c88d8182cc1480e1525eaf95fad"

RSS_MAP = {
    "gaming": "https://www.jeuxvideo.com/rss/rss.xml",
    "crypto": "https://fr.cryptonews.com/news/feed",
    "tech": "https://www.frandroid.com/feed",
    "world": "https://www.lemonde.fr/rss/une.xml"
}

# --- FONCTIONS UTILITAIRES ---
def get_real_weather(city):
    if not city: city = "Paris"
    city_clean = city.strip().lower().title() 
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city_clean},fr&appid={OPENWEATHER_KEY}&units=metric&lang=fr"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            return {
                "temp": round(data['main']['temp']),
                "desc": data['weather'][0]['description'],
                "city": data['name']
            }
    except: pass
    return None

def get_real_news(category):
    rss_url = RSS_MAP.get(category, RSS_MAP["gaming"])
    try:
        feed = feedparser.parse(rss_url)
        if feed.entries:
            entry = random.choice(feed.entries[:5])
            img_url = "https://i.imgur.com/Q7q12s3.jpg"
            if 'media_content' in entry: img_url = entry.media_content[0]['url']
            elif 'links' in entry:
                for l in entry.links:
                    if l.type.startswith('image/'): img_url = l.href; break
            return {"title": entry.title, "desc": entry.summary, "link": entry.link, "image": img_url}
    except: pass
    return None

def get_random_meme():
    subreddits_fr = ['rance', 'moi_dlvv', 'FrenchMemes']
    try:
        choix = random.choice(subreddits_fr)
        r = requests.get(f"https://meme-api.com/gimme/{choix}", timeout=2)
        if r.status_code == 200:
            data = r.json()
            if not data.get("nsfw", False) and data.get("url"):
                return {"title": data["title"], "image": data["url"], "author": data["author"], "subreddit": data["subreddit"]}
    except: pass
    try:
        r = requests.get("https://meme-api.com/gimme", timeout=4)
        if r.status_code == 200:
            data = r.json()
            if not data.get("nsfw", False):
                return {"title": data["title"], "image": data["url"], "author": data["author"], "subreddit": data["subreddit"]}
    except: pass
    return None

# --- CLASSE SUPRÊME ---
class BotWithFeatures(UltimateBot):
    def __init__(self, bot_key, token_env_var, system_prompt, persona_name, initial_activity=None):
        super().__init__(bot_key=bot_key, token_env_var=token_env_var, system_prompt=system_prompt)
        self.persona_name = persona_name
        self.initial_activity = initial_activity
        self.last_run_minute = None

    async def setup_hook(self):
        await super().setup_hook()
        self.add_feature_commands()
        
        # Statut
        if self.initial_activity:
            await self.change_presence(activity=discord.Game(name=self.initial_activity))
            
        # Auto-Sync
        self.loop.create_task(self.startup_sync())

        print(f"💀 [{self.persona_name.upper()}] Features, Scheduler & Activity activés.")
        self.scheduler_loop.start()

    async def startup_sync(self):
        await self.wait_until_ready()
        print("🔄 Début de l'Auto-Sync des commandes...")
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                print(f"  ✅ Commandes synchronisées pour : {guild.name}")
            except Exception as e:
                print(f"  ❌ Erreur sync {guild.name}: {e}")
        print("✅ Auto-Sync terminé !")

    # --- ÉCOUTE DES MESSAGES ---
    async def on_message(self, message):
        if message.author.bot: return
        
        # Quiz
        is_quiz_resp = await check_answer(message, self.openai_client, self.persona_name)
        if is_quiz_resp: return 

        await super().on_message(message)

    # --- IA PERSONNALISÉE ---
    async def generate_persona_text(self, context_text, context_type):
        try:
            sys_prompt = f"Tu es {self.persona_name}. "
            if context_type == "news": sys_prompt += "Présente cette news en une phrase courte, drôle et percutante en français."
            elif context_type == "meteo": sys_prompt += "Présente la météo en une seule phrase drôle ou cynique en français."
            elif context_type == "meme": sys_prompt += "Réagis à ce meme en une phrase courte en français."
            
            response = self.openai_client.chat.completions.create(
                model=self.openai_model,
                messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": context_text}],
                temperature=0.8, max_tokens=150
            )
            return response.choices[0].message.content.strip()
        except: return f"🤖 **Info** (Mon IA dort)."

    async def send_feature_message(self, channel, feature_type, param=None):
        try:
            if feature_type == 'news':
                cat = param if param else 'gaming'
                news = get_real_news(cat)
                if news:
                    intro = await self.generate_persona_text(f"Titre: {news['title']}. Résumé: {news['desc']}", "news")
                    embed = discord.Embed(title=news['title'], url=news['link'], color=0x5865F2)
                    embed.set_image(url=news['image'])
                    embed.set_footer(text=f"{self.persona_name} News | {cat.upper()}")
                    await channel.send(f"🎙️ **{intro}**", embed=embed)
            elif feature_type == 'meteo':
                city = param if param else 'Paris'
                weather = get_real_weather(city)
                if weather:
                    ctx = f"Ville: {weather['city']}. Ciel: {weather['desc']}. Température: {weather['temp']}°C."
                    intro = await self.generate_persona_text(ctx, "meteo")
                    embed = discord.Embed(title=f"☁️ Météo : {weather['city']}", color=0xFFA500)
                    embed.add_field(name="🌡️ Temp", value=f"**{weather['temp']}°C**", inline=True)
                    embed.add_field(name="👀 Ciel", value=f"{weather['desc'].capitalize()}", inline=True)
                    await channel.send(f"🎙️ **{intro}**", embed=embed)
            elif feature_type == 'meme':
                meme = get_random_meme()
                if meme:
                    intro = await self.generate_persona_text(f"Titre meme: {meme['title']}", "meme")
                    embed = discord.Embed(title=meme['title'], color=0xFF4500)
                    embed.set_image(url=meme['image'])
                    embed.set_footer(text=f"Via r/{meme['subreddit']}")
                    await channel.send(f"😂 **{intro}**", embed=embed)
        except Exception as e: print(f"Erreur d'envoi : {e}")

    # --- COMMANDES SLASH ---
    def add_feature_commands(self):
        @self.tree.command(name="news", description="Affiche une news")
        @app_commands.describe(categorie="Catégorie (gaming, crypto, tech, world)")
        async def slash_news(interaction: discord.Interaction, categorie: str = "gaming"):
            if await self.check_access(interaction):
                await interaction.response.defer()
                await self.send_feature_message(interaction.channel, 'news', categorie)
                await interaction.followup.send("✅", ephemeral=True)

        @self.tree.command(name="meteo", description="Affiche la météo")
        @app_commands.describe(ville="Nom de la ville")
        async def slash_meteo(interaction: discord.Interaction, ville: str):
            if await self.check_access(interaction):
                await interaction.response.defer()
                await self.send_feature_message(interaction.channel, 'meteo', ville)
                await interaction.followup.send("✅", ephemeral=True)

        @self.tree.command(name="meme", description="Affiche un meme")
        async def slash_meme(interaction: discord.Interaction):
            if await self.check_access(interaction):
                await interaction.response.defer()
                await self.send_feature_message(interaction.channel, 'meme')
                await interaction.followup.send("✅", ephemeral=True)

        @self.tree.command(name="debat", description="Lancer un débat entre deux bots")
        @app_commands.describe(sujet="Le thème du débat", bot1="Combattant 1", bot2="Combattant 2")
        @app_commands.choices(bot1=[app_commands.Choice(name=k.capitalize(), value=k) for k in ["homer","cartman","deadpool","yoda"]], 
                              bot2=[app_commands.Choice(name=k.capitalize(), value=k) for k in ["homer","cartman","deadpool","yoda"]])
        async def slash_debat(interaction: discord.Interaction, sujet: str, bot1: app_commands.Choice[str], bot2: app_commands.Choice[str]):
            if await self.check_access(interaction):
                await interaction.response.defer()
                await run_debate(interaction, self.openai_client, self.openai_model, sujet, bot1.value, bot2.value)

        @self.tree.command(name="quiz", description="Lancer un quiz de culture générale")
        async def slash_quiz(interaction: discord.Interaction):
            if await self.check_access(interaction):
                await interaction.response.defer()
                await start_quiz(interaction, self.openai_client, self.persona_name)

        # --- MODIFICATION ICI : AJOUT DU LIEN VERS LE PANEL ---
        @self.tree.command(name="classement", description="Voir le top des joueurs du Quiz")
        async def slash_classement(interaction: discord.Interaction):
            if await self.check_access(interaction):
                top = get_top_scores()
                txt = "**🏆 CLASSEMENT QUIZ (TOP 5)**\n"
                for i, (uid, score) in enumerate(top, 1):
                    txt += f"{i}. <@{uid}> : **{score} pts**\n"
                if not top: txt += "Aucun score pour l'instant."
                
                # Le lien magique qui redirige vers ton panel
                txt += "\n🔗 **Voir tout le classement :** https://panel.4ubot.fr/leaderboard"
                
                await interaction.response.send_message(txt)

        @self.tree.command(name="recap", description="Génère un Flash Info des dernières discussions")
        async def slash_recap(interaction: discord.Interaction):
            if await self.check_access(interaction):
                await interaction.response.defer()
                await generate_recap(interaction, self.openai_client, self.persona_name)

        @self.tree.command(name="clash", description="Clash un membre du serveur")
        async def slash_clash(interaction: discord.Interaction, victime: discord.User):
            if await self.check_access(interaction):
                await interaction.response.defer()
                await clash_user(interaction, self.openai_client, self.persona_name, victime)

    # --- SCHEDULER ---
    @tasks.loop(seconds=10)
    async def scheduler_loop(self):
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        current_day = now.strftime("%A").lower()
        current_time = now.strftime("%H:%M")
        if current_time == self.last_run_minute: return
        self.last_run_minute = current_time
        try:
            url = f"{PANEL_API_URL}/{self.bot_key}"
            resp = requests.get(url, params={"token": PANEL_API_TOKEN}, timeout=3)
            if resp.status_code == 200:
                for t in resp.json():
                    guild_id = int(t.get('guild_discord_id', 0))
                    if not await self.is_allowed(guild_id): continue
                    if ((t['day_of_week'] == current_day) if t['day_of_week'] else True) and (t['time_of_day'] == current_time):
                        print(f"✅ [{self.persona_name}] Tâche {t['task_type']} détectée !")
                        channel = self.get_channel(int(t['channel_id']))
                        if channel: await self.send_feature_message(channel, t['task_type'], t.get('task_param'))
        except Exception as e: print(f"❌ Erreur Scheduler : {e}")
    
    @scheduler_loop.before_loop
    async def before_scheduler(self): await self.wait_until_ready()