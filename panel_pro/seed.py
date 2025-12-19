from sqlalchemy.orm import Session
from app import app, User, Guild, BotType, Subscription
from datetime import datetime, timedelta
import os

with Session(app.engine) as s:
    # 1) user "seed" (obligatoire car subscriptions.user_id est NOT NULL)
    u = s.query(User).filter_by(discord_id='seed').first()
    if not u:
        u = User(discord_id='seed', username='Seed User', avatar_url=None,
                 access_token=None, refresh_token=None, is_owner=True)
        s.add(u); s.commit()

    # 2) types de bots
    bots = [('arthur','Arthur'), ('cartman','Cartman'), ('deadpool','Deadpool'), ('yoda','Yoda')]
    for k,n in bots:
        if not s.query(BotType).filter_by(key=k).first():
            s.add(BotType(key=k, name=n))
    s.commit()

    # 3) guild
    gid = os.environ['GUILD_ID']
    gname = os.environ.get('GUILD_NAME', 'Dev Guild')
    g = s.query(Guild).filter_by(discord_id=gid).first()
    if not g:
        g = Guild(discord_id=gid, name=gname, owner_discord_id=u.discord_id)
        s.add(g); s.commit()

    # 4) abonnements en essai 15j (un par bot)
    for k,_ in bots:
        bot = s.query(BotType).filter_by(key=k).first()
        exists = s.query(Subscription).filter_by(guild_id=g.id, bot_type_id=bot.id).first()
        if not exists:
            s.add(Subscription(
                user_id=u.id, guild_id=g.id, bot_type_id=bot.id,
                status='trial',
                start_at=datetime.utcnow(),
                trial_until=datetime.utcnow() + timedelta(days=15)
            ))
    s.commit()

print("Seed OK")
