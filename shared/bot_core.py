import os, aiohttp, discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from openai import OpenAI
from collections import deque 

# Import hybride
from shared.fight_club import start_fight, register_vote, announce_result

load_dotenv()

class UltimateBot(commands.Bot):
    def __init__(self, bot_key, token_env_var, system_prompt):
        intents = discord.Intents.default()
        intents.message_content = True
        
        # On garde le prefix "!" juste pour tes outils admin
        super().__init__(command_prefix="!", intents=intents)

        self.bot_key = bot_key
        self.token_env_var = token_env_var
        self.system_prompt = system_prompt
        
        self.panel_url = os.getenv("PANEL_API_URL")
        self.panel_token = os.getenv("PANEL_API_TOKEN")
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
        
        self.allowed_guilds = set()
        self.conversation_history = {}

    async def setup_hook(self):
        self.refresh_allowed_guilds.start()
        print(f"[{self.bot_key.capitalize()}] Moteur Slash démarré (MODE SERVEUR UNIQUEMENT).")

    @tasks.loop(seconds=60)
    async def refresh_allowed_guilds(self):
        if not (self.panel_url and self.panel_token): return
        url = self.panel_url.rstrip("/") + f"/api/bot/config/{self.bot_key}"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, params={"token": self.panel_token}, timeout=10) as r:
                    if r.status == 200:
                        data = await r.json()
                        self.allowed_guilds = {int(x) for x in data.get("allowed_guild_ids", [])}
        except Exception as e:
            print(f"[{self.bot_key}] Erreur sync panel : {e}")

    async def is_allowed(self, guild_id: int | None) -> bool:
        # Note: guild_id est None en DM, donc cette fonction retournera False indirectement via check_access
        if guild_id is None: return False 
        if not self.allowed_guilds:
            await self.refresh_allowed_guilds()
        return guild_id in self.allowed_guilds

    # --- SÉCURITÉ SLASH COMMANDS (Bloque les DMs) ---
    async def check_access(self, interaction: discord.Interaction) -> bool:
        # 1. Blocage des Messages Privés
        if not interaction.guild:
            await interaction.response.send_message(
                "❌ **Désolé !** Je ne fonctionne que sur un serveur Discord, pas en privé.", 
                ephemeral=True
            )
            return False

        # 2. Vérification de l'abonnement du serveur
        if not await self.is_allowed(interaction.guild.id):
            await interaction.response.send_message(
                f"⛔ Abonnement inactif pour **{self.bot_key.capitalize()}** sur ce serveur. Go panel !", 
                ephemeral=True
            )
            return False
        return True

    # --- IA & MÉMOIRE ---
    async def get_gpt_reply(self, channel_id, user_msg):
        if channel_id not in self.conversation_history:
            self.conversation_history[channel_id] = deque(maxlen=6)
        
        history = self.conversation_history[channel_id]
        history.append({"role": "user", "content": user_msg})
        messages_payload = [{"role": "system", "content": self.system_prompt}] + list(history)

        try:
            response = self.openai_client.chat.completions.create(
                model=self.openai_model, messages=messages_payload, temperature=0.8, max_tokens=250
            )
            bot_reply = response.choices[0].message.content.strip()
            history.append({"role": "assistant", "content": bot_reply})
            return bot_reply
        except Exception as e:
            print(f"Erreur GPT: {e}")
            return "Oups, j'ai perdu le fil (Erreur API)."

    async def on_message(self, message):
        if message.author.bot: return
        await self.process_commands(message) # Pour !sync et !clean

        # --- BLOCAGE DES DMs (Chatbot) ---
        if isinstance(message.channel, discord.DMChannel):
            # On ignore ou on répond une fois. Ici, je propose de répondre gentiment.
            # Si tu veux le silence total, remplace par : return
            await message.channel.send("❌ Je ne discute pas en privé. Ajoute-moi sur un serveur !")
            return
        # ---------------------------------

        # Chatbot classique (Mentions uniquement sur serveur maintenant)
        is_mentioned = self.user in message.mentions

        if is_mentioned:
            # Vérif abonnement serveur
            if not await self.is_allowed(message.guild.id):
                await message.channel.send(f"⛔ Pas d'abonnement actif.")
                return
            
            clean_text = message.content.replace(f"<@{self.user.id}>", "").strip() or "Salut !"
            async with message.channel.typing():
                reply = await self.get_gpt_reply(message.channel.id, clean_text)
                await message.channel.send(reply)

    def register_common_commands(self):
        
        # === OUTILS ADMIN ===
        @self.command(name="sync")
        async def _sync(ctx):
            if not ctx.guild: return await ctx.send("Pas de sync en DM.")
            self.tree.copy_global_to(guild=ctx.guild)
            await self.tree.sync(guild=ctx.guild)
            await ctx.send("✅ Commandes Slash rechargées !")

        @self.command(name="clean")
        async def _clean(ctx):
            if not ctx.guild: return await ctx.send("Pas de clean en DM.")
            self.tree.clear_commands(guild=ctx.guild)
            await self.tree.sync(guild=ctx.guild)
            await ctx.send("🧹 Commandes serveur nettoyées.")

        @self.command(name="panel_refresh")
        async def _refresh(ctx):
            if not ctx.guild: return
            await self.refresh_allowed_guilds()
            await ctx.reply("✅ Sync Panel forcée.")

        # === SLASH COMMANDS ===
        
        @self.tree.command(name="duel", description="Lancer un duel")
        @app_commands.describe(p1="Combattant 1", p2="Combattant 2")
        async def slash_duel(interaction: discord.Interaction, p1: str, p2: str):
            if await self.check_access(interaction):
                await interaction.response.defer()
                await start_fight(interaction, custom_fight=f"{p1} VS {p2}")

        @self.tree.command(name="duel_random", description="Combat aléatoire IA")
        async def slash_duel_random(interaction: discord.Interaction):
            if await self.check_access(interaction):
                await interaction.response.defer()
                await start_fight(interaction)

        @self.tree.command(name="vote", description="Voter pour un combattant")
        async def slash_vote(interaction: discord.Interaction, choix: str):
            if await self.check_access(interaction):
                msg = register_vote(interaction.channel_id, interaction.user, choix)
                await interaction.response.send_message(msg, ephemeral=True)

        @self.tree.command(name="dis", description="Parler avec le bot")
        async def slash_talk(interaction: discord.Interaction, message: str):
            if await self.check_access(interaction):
                await interaction.response.defer()
                reply = await self.get_gpt_reply(interaction.channel_id, message)
                await interaction.followup.send(reply)

    def run_bot(self):
        self.register_common_commands()
        token = os.getenv(self.token_env_var)
        if not token: raise ValueError(f"Token manquant pour {self.token_env_var}")
        self.run(token)