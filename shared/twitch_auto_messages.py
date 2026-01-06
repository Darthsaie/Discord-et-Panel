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
        self.auto_messages_enabled = True
        self.message_interval = 30  # minutes
        self.last_auto_message = {}
        
        # Messages pré-définis par défaut
        self.default_messages = [
            "Hey tout le monde ! DeadPool est là pour animer le chat ! 🎭",
            "Question du jour : Quel est votre film Marvel préféré ? 🦸‍♂️",
            "DeadPool vous souhaite un excellent stream ! 💪",
            "N'oubliez pas de follow pour ne rien rater ! 🚀",
            "Petit rappel : DeadPool répond aux mentions et aux mots-clés ! 💬",
            "Le chat est trop calme aujourd'hui... quelqu'un a une blague ? 😄",
            "DeadPool est en mode veille, mais prêt à déconner ! 😎",
            "Stream de qualité ? DeadPool approuve ! ✅",
            "Allez les gars, on fait du bon contenu ! 🎯",
            "DeadPool pense que ce stream mérite plus de viewers ! 📈"
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
                        self.auto_messages_enabled = config.get("enabled", True)
                        self.message_interval = config.get("interval", 30)
                        return config
        except Exception as e:
            print(f"⚠️ Erreur chargement config auto-messages: {e}")
            return None

    async def generate_ai_message(self, channel_name, viewer_count, stream_title):
        """Génère un message avec l'IA selon le contexte"""
        try:
            prompt = f"""
Tu es DeadPool, un bot Twitch décontracté et drôle.
Génère un message court (max 100 caractères) pour le chat de la chaîne "{channel_name}".
Contexte:
- Titre du stream: {stream_title or "Pas de titre"}
- Viewers: {viewer_count or "Inconnu"}
- Personnalité: Sarcastique, drôle, parfois absurde
- Ne sois PAS trop répétitif
- Varie les styles: question, blague, encouragement, interaction

Génère UN message uniquement, sans formatage spécial.
"""
            
            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Génère un message pour le chat"}
                ],
                max_tokens=150,
                temperature=0.9
            )
            
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"⚠️ Erreur génération IA: {e}")
            return random.choice(self.default_messages)

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
            # 70% de chance d'utiliser l'IA, 30% pour les messages par défaut
            if random.random() < 0.7:
                message = await self.generate_ai_message(channel_name, viewer_count, stream_title)
            else:
                message = random.choice(self.default_messages)
            
            self.last_auto_message[channel_id] = datetime.now()
            return message
            
        except Exception as e:
            print(f"⚠️ Erreur envoi message auto: {e}")
            return None

    def get_config_html(self):
        """Génère le HTML pour la configuration"""
        return f"""
        <div class="auto-messages-config">
            <h3>🤖 Messages Automatiques DeadPool</h3>
            
            <div class="config-section">
                <label>
                    <input type="checkbox" id="auto_messages_enabled" {'checked' if self.auto_messages_enabled else ''}>
                    Activer les messages automatiques
                </label>
                
                <div class="form-group">
                    <label for="message_interval">Intervalle (minutes):</label>
                    <input type="number" id="message_interval" value="{self.message_interval}" min="5" max="120">
                    <small>Un message sera envoyé toutes les X minutes</small>
                </div>
                
                <div class="form-group">
                    <label>Messages par défaut:</label>
                    <textarea id="default_messages" rows="5" placeholder="Un message par ligne...">{chr(10).join(self.default_messages)}</textarea>
                    <small>Messages utilisés si l'IA ne répond pas</small>
                </div>
                
                <div class="ai-settings">
                    <h4>🧠 Configuration IA</h4>
                    <div class="form-group">
                        <label for="ai_probability">Probabilité IA (%):</label>
                        <input type="range" id="ai_probability" min="0" max="100" value="70">
                        <span id="ai_probability_value">70%</span>
                        <small>Chance d'utiliser l'IA vs messages par défaut</small>
                    </div>
                    
                    <div class="form-group">
                        <label for="message_style">Style des messages:</label>
                        <select id="message_style">
                            <option value="fun">Drôle et décontracté</option>
                            <option value="engaging">Interactif et engageant</option>
                            <option value="supportive">Supportif et encourageant</option>
                            <option value="mixed">Mixte (aléatoire)</option>
                        </select>
                    </div>
                </div>
                
                <button onclick="saveAutoMessagesConfig()" class="btn-primary">
                    💾 Sauvegarder la configuration
                </button>
            </div>
        </div>
        
        <style>
        .auto-messages-config {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 24px;
            margin: 20px 0;
        }}
        
        .config-section {{
            display: flex;
            flex-direction: column;
            gap: 16px;
        }}
        
        .form-group {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        
        .ai-settings {{
            background: rgba(99, 102, 241, 0.1);
            border: 1px solid rgba(99, 102, 241, 0.3);
            border-radius: 8px;
            padding: 16px;
            margin-top: 16px;
        }}
        
        .auto-messages-config h3 {{
            color: var(--text-primary);
            margin: 0 0 20px 0;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        
        .auto-messages-config h4 {{
            color: var(--text-primary);
            margin: 0 0 12px 0;
        }}
        
        .auto-messages-config label {{
            color: var(--text-secondary);
            font-weight: 600;
        }}
        
        .auto-messages-config input, 
        .auto-messages-config select, 
        .auto-messages-config textarea {{
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 6px;
            padding: 8px 12px;
            color: var(--text-primary);
        }}
        
        .auto-messages-config textarea {{
            resize: vertical;
            font-family: monospace;
        }}
        
        .btn-primary {{
            background: var(--accent);
            color: white;
            border: none;
            border-radius: 8px;
            padding: 12px 24px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }}
        
        .btn-primary:hover {{
            background: var(--accent-glow);
            transform: translateY(-1px);
        }}
        
        .auto-messages-config small {{
            color: var(--text-secondary);
            font-size: 0.75rem;
            opacity: 0.7;
        }}
        </style>
        
        <script>
        function updateAIProbability(value) {{
            document.getElementById('ai_probability_value').textContent = value + '%';
        }}
        
        document.getElementById('ai_probability').addEventListener('input', (e) => {{
            updateAIProbability(e.target.value);
        }});
        
        async function saveAutoMessagesConfig() {{
            const config = {{
                enabled: document.getElementById('auto_messages_enabled').checked,
                interval: parseInt(document.getElementById('message_interval').value),
                default_messages: document.getElementById('default_messages').value.split('\\n').filter(m => m.trim()),
                ai_probability: parseInt(document.getElementById('ai_probability').value),
                message_style: document.getElementById('message_style').value
            }};
            
            try {{
                const response = await fetch('/api/bot/auto-messages/deadpool', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                    }},
                    body: JSON.stringify(config)
                }});
                
                if (response.ok) {{
                    showToast('Configuration sauvegardée !', 'success');
                }} else {{
                    showToast('Erreur lors de la sauvegarde', 'error');
                }}
            }} catch (error) {{
                showToast('Erreur: ' + error.message, 'error');
            }}
        }}
        </script>
        """
