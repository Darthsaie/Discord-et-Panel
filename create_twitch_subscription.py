#!/usr/bin/env python3
"""
Script pour créer la guild et subscription Twitch pour deadpool_4ubot
"""

import sys
import os
sys.path.append('/app/panel_pro')

# Importer depuis le module app
import app
from app import Guild, Subscription, BotType
from sqlalchemy import select
from sqlalchemy.orm import Session

def create_twitch_guild_and_subscription():
    with Session(app.engine) as db:
        # 1. Vérifier/Créer la guild Twitch
        guild = db.scalar(select(Guild).where(Guild.discord_id == 1418676924))
        if not guild:
            print("📝 Création de la guild Twitch deadpool_4ubot...")
            guild = Guild(
                discord_id=1418676924,
                name='deadpool_4ubot',
                platform='twitch'
            )
            db.add(guild)
            db.commit()
            print(f"✅ Guild créée avec ID: {guild.id}")
        else:
            print(f"📋 Guild existante: {guild.name} (Platform: {guild.platform})")
        
        # 2. Vérifier/Créer le bot_type deadpool
        bot_type = db.scalar(select(BotType).where(BotType.key == 'deadpool'))
        if not bot_type:
            print("📝 Création du bot_type deadpool...")
            bot_type = BotType(
                key='deadpool',
                name='DeadPool',
                description='Bot sarcastique et drôle'
            )
            db.add(bot_type)
            db.commit()
            print(f"✅ BotType créé avec ID: {bot_type.id}")
        else:
            print(f"📋 BotType existant: {bot_type.name}")
        
        # 3. Vérifier/Créer la subscription
        existing_sub = db.scalar(
            select(Subscription).where(
                Subscription.guild_id == guild.id,
                Subscription.bot_type_id == bot_type.id
            )
        )
        
        if not existing_sub:
            print("📝 Création de la subscription...")
            subscription = Subscription(
                guild_id=guild.id,
                bot_type_id=bot_type.id,
                status='active',
                tier='premium'
            )
            db.add(subscription)
            db.commit()
            print(f"✅ Subscription créée avec ID: {subscription.id}")
        else:
            print(f"📋 Subscription existante: {existing_sub.status}")
        
        print("\n🎯 Configuration terminée !")
        print(f"📊 Guild ID: {guild.id}")
        print(f"🤖 Bot Type ID: {bot_type.id}")
        print("🔄 Le bot devrait maintenant rejoindre votre chaîne Twitch")

if __name__ == "__main__":
    create_twitch_guild_and_subscription()
