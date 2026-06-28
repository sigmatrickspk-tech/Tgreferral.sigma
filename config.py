import sqlite3
import os

# Bot Configuration
BOT_TOKEN = "8651241172:AAG6dwblqW-_mmWVq13RkkjQXEmEW2DSE3M"  # Replace with your bot token from @BotFather
ADMIN_IDS = [8278238550]  # Replace with your Telegram user ID

# Database path
DB_PATH = "referral_bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT,
                  first_name TEXT,
                  joined_date TEXT,
                  coins INTEGER DEFAULT 0,
                  referrals_done INTEGER DEFAULT 0,
                  daily_referrals INTEGER DEFAULT 0,
                  daily_reset_date TEXT,
                  referred_by INTEGER,
                  is_banned INTEGER DEFAULT 0,
                  is_admin INTEGER DEFAULT 0)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS referral_links
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  link TEXT,
                  bot_username TEXT,
                  ref_code TEXT,
                  total_referrals INTEGER DEFAULT 0,
                  daily_limit INTEGER DEFAULT 10,
                  created_at TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS promocodes
                 (code TEXT PRIMARY KEY,
                  coins INTEGER,
                  max_uses INTEGER,
                  current_uses INTEGER DEFAULT 0,
                  created_by INTEGER,
                  is_active INTEGER DEFAULT 1)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS force_channels
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  channel_id TEXT,
                  channel_username TEXT,
                  channel_name TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS giveaways
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  prize_coins INTEGER,
                  winners_count INTEGER,
                  participants TEXT DEFAULT '[]',
                  winners TEXT DEFAULT '[]',
                  is_active INTEGER DEFAULT 1,
                  created_at TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY,
                  value TEXT)''')
    
    defaults = [
        ('welcome_message', 'Welcome {name}! Use /start to begin earning coins by referring bots.'),
        ('referral_message', '🎉 You earned 1 coin for referring {referred_name}!'),
        ('daily_limit', '10'),
        ('coins_per_referral', '1'),
        ('referral_bonus_coins', '1'),
    ]
    for key, value in defaults:
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
    
    conn.commit()
    conn.close()

init_db()
