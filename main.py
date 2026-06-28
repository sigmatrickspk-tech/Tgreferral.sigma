import logging
import sqlite3
import re
import json
import random
import string
import asyncio
import threading
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler,
    MessageHandler, Filters, CallbackContext
)
from config import BOT_TOKEN, ADMIN_IDS, DB_PATH
from captcha_solver import CaptchaSolver
from telethon import TelegramClient

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== TELEGRAM API FOR REAL REFERRAL EXECUTION ==========
# Get from https://my.telegram.org/apps
TELEGRAM_API_ID = 123456  # REPLACE THIS
TELEGRAM_API_HASH = "YOUR_API_HASH"  # REPLACE THIS
TELEGRAM_PHONE = "+1234567890"  # REPLACE WITH YOUR PHONE

telethon_client = TelegramClient('referral_session', TELEGRAM_API_ID, TELEGRAM_API_HASH)
captcha_solver = None

# ========== HELPERS ==========

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def is_banned(user_id):
    conn = get_db()
    u = conn.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return u and u['is_banned'] == 1

def is_admin(user_id):
    conn = get_db()
    u = conn.execute("SELECT is_admin FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return (u and u['is_admin'] == 1) or user_id in ADMIN_IDS

def check_force_join(user_id, context):
    conn = get_db()
    channels = conn.execute("SELECT * FROM force_channels").fetchall()
    conn.close()
    if not channels:
        return True, []
    not_joined = []
    for ch in channels:
        try:
            m = context.bot.get_chat_member(chat_id=ch['channel_id'], user_id=user_id)
            if m.status in ['left', 'kicked']:
                not_joined.append(ch)
        except:
            not_joined.append(ch)
    return len(not_joined) == 0, not_joined

def force_join_kb(not_joined):
    kb = []
    for ch in not_joined:
        u = ch['channel_username'].lstrip('@')
        kb.append([InlineKeyboardButton(f"📢 Join {ch['channel_name']}", url=f"https://t.me/{u}")])
    kb.append([InlineKeyboardButton("✅ I've Joined", callback_data="check_join")])
    return InlineKeyboardMarkup(kb)

def reset_daily(user_id):
    conn = get_db()
    u = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    if u:
        today = date.today().isoformat()
        if u['daily_reset_date'] != today:
            conn.execute("UPDATE users SET daily_referrals=0, daily_reset_date=? WHERE user_id=?", (today, user_id))
            conn.commit()
    conn.close()

def gen_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def parse_link(link):
    m = re.match(r'https?://t\.me/(\w+)\?start=(\w+)', link.strip())
    if m: return m.group(1), m.group(2)
    m = re.search(r't\.me/(\w+)\?start=(\w+)', link.strip())
    if m: return m.group(1), m.group(2)
    return None, None

async def execute_real_ref(bot_username, ref_code):
    global telethon_client, captcha_solver
    try:
        if not telethon_client.is_connected():
            await telethon_client.connect()
            if not await telethon_client.is_user_authorized():
                return {'success': False, 'error': 'Not authorized'}
        if captcha_solver is None:
            captcha_solver = CaptchaSolver(telethon_client)
        return await captcha_solver.solve_bot_captcha(bot_username, ref_code)
    except Exception as e:
        return {'success': False, 'error': str(e)[:200]}

def run_async_ref(bot_username, ref_code):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(execute_real_ref(bot_username, ref_code))
    finally:
        loop.close()

# ========== START ==========

def start(update: Update, context: CallbackContext):
    user = update.effective_user
    uid = user.id
    if is_banned(uid):
        update.message.reply_text("❌ You are banned.")
        return
    
    joined, not_joined = check_force_join(uid, context)
    if not joined:
        update.message.reply_text("⚠️ Join channels first:", reply_markup=force_join_kb(not_joined))
        return
    
    conn = get_db()
    existing = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    if not existing:
        conn.execute("INSERT INTO users (user_id, username, first_name, joined_date, daily_reset_date) VALUES (?,?,?,?,?)",
                     (uid, user.username, user.first_name, datetime.now().isoformat(), date.today().isoformat()))
        conn.commit()
        args = context.args
        if args and args[0].isdigit() and int(args[0]) != uid:
            ref_id = int(args[0])
            conn.execute("UPDATE users SET referred_by=? WHERE user_id=?", (ref_id, uid))
            bonus = int(conn.execute("SELECT value FROM settings WHERE key='referral_bonus_coins'").fetchone()['value'])
            conn.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (bonus, ref_id))
            ref_msg = conn.execute("SELECT value FROM settings WHERE key='referral_message'").fetchone()['value']
            conn.commit()
            try:
                context.bot.send_message(chat_id=ref_id, text=ref_msg.format(referred_name=user.first_name))
            except:
                pass
        conn.commit()
    conn.close()
    
    welcome = conn.execute("SELECT value FROM settings WHERE key='welcome_message'").fetchone()['value']
    conn.close()
    
    kb = [
        [InlineKeyboardButton("📊 My Stats", callback_data="my_stats")],
        [InlineKeyboardButton("🔗 Submit Referral Link", callback_data="submit_link")],
        [InlineKeyboardButton("💰 Balance & Buy Coins", callback_data="buy_coins")],
        [InlineKeyboardButton("🎁 Promocodes", callback_data="promocodes")],
        [InlineKeyboardButton("👥 Refer Friends", callback_data="refer_friends")],
    ]
    if is_admin(uid):
        kb.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])
    
    update.message.reply_text(welcome.format(name=user.first_name), reply_markup=InlineKeyboardMarkup(kb))

# ========== REFERRAL LINK HANDLER ==========

def handle_referral(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    text = update.message.text
    if is_banned(uid):
        update.message.reply_text("❌ You are banned.")
        return
    
    joined, not_joined = check_force_join(uid, context)
    if not joined:
        update.message.reply_text("⚠️ Join channels first:", reply_markup=force_join_kb(not_joined))
        return
    
    reset_daily(uid)
    
    bot_un, ref_code = parse_link(text)
    if not bot_un or not ref_code:
        update.message.reply_text("❌ Invalid link. Use: `https://t.me/BotName?start=CODE`", parse_mode=ParseMode.MARKDOWN)
        return
    
    if bot_un.lower() == context.bot.username.lower():
        update.message.reply_text("❌ Cannot refer this bot itself.")
        return
    
    conn = get_db()
    daily_limit = int(conn.execute("SELECT value FROM settings WHERE key='daily_limit'").fetchone()['value'])
    user = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    
    if user['daily_referrals'] >= daily_limit:
        conn.close()
        update.message.reply_text(f"❌ Daily limit ({daily_limit}) reached. Try tomorrow!")
        return
    
    if user['coins'] < 1:
        conn.close()
        update.message.reply_text("❌ Not enough coins! Each referral costs 1 coin. Buy from admin or refer friends.")
        return
    
    # Deduct coin, save link
    conn.execute("UPDATE users SET coins = coins - 1, daily_referrals = daily_referrals + 1 WHERE user_id=?", (uid,))
    existing = conn.execute("SELECT * FROM referral_links WHERE user_id=? AND bot_username=? AND ref_code=?", (uid, bot_un, ref_code)).fetchone()
    if existing:
        conn.execute("UPDATE referral_links SET total_referrals = total_referrals + 1 WHERE id=?", (existing['id'],))
    else:
        conn.execute("INSERT INTO referral_links (user_id, link, bot_username, ref_code, total_referrals, created_at) VALUES (?,?,?,?,1,?)",
                     (uid, text, bot_un, ref_code, datetime.now().isoformat()))
    conn.commit()
    user = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    conn.close()
    
    update.message.reply_text(
        f"🔄 **Processing referral...**\n\n🤖 Bot: @{bot_un}\n🔑 Code: `{ref_code}`\n💰 1 coin deducted\n\n"
        f"⏳ Sending referral + solving captcha...\n_Takes 10-30 seconds_",
        parse_mode=ParseMode.MARKDOWN
    )
    
    def bg_work():
        try:
            result = run_async_ref(bot_un, ref_code)
            if result.get('success'):
                context.bot.send_message(
                    chat_id=uid,
                    text=f"✅ **Referral Successful!** 🎉\n\n🤖 @{bot_un}\n🔑 `{ref_code}`\n"
                         f"🧩 Captcha: {'✅ Solved' if result.get('solved') else 'N/A'}\n"
                         f"📢 Channels joined: {len(result.get('channels_joined', []))}\n\n"
                         f"📊 Today: {user['daily_referrals']}/{daily_limit}\n💰 Balance: {user['coins']} coins",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                conn2 = get_db()
                conn2.execute("UPDATE users SET coins = coins + 1, daily_referrals = daily_referrals - 1 WHERE user_id=?", (uid,))
                conn2.commit()
                conn2.close()
                err = result.get('details', result.get('error', 'Unknown'))
                context.bot.send_message(
                    chat_id=uid,
                    text=f"❌ **Referral Failed**\n\n🤖 @{bot_un}\n🔑 `{ref_code}`\nReason: {err[:200]}\n\n💳 1 coin refunded.",
                    parse_mode=ParseMode.MARKDOWN
                )
        except Exception as e:
            try:
                conn2 = get_db()
                conn2.execute("UPDATE users SET coins = coins + 1, daily_referrals = daily_referrals - 1 WHERE user_id=?", (uid,))
                conn2.commit()
                conn2.close()
                context.bot.send_message(chat_id=uid, text=f"❌ Error: {e}. 1 coin refunded.")
            except:
                pass
    
    threading.Thread(target=bg_work, daemon=True).start()

# ========== CALLBACK HANDLER ==========

def button_handler(update: Update, context: CallbackContext):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data
    
    if is_banned(uid):
        q.answer("Banned.", show_alert=True)
        return
    
    joined, not_joined = check_force_join(uid, context)
    if not joined and data != "check_join":
        q.edit_message_text("⚠️ Join channels first:", reply_markup=force_join_kb(not_joined))
        return
    
    if data == "check_join":
        joined, not_joined = check_force_join(uid, context)
        if joined:
            q.answer("✅ Thanks!")
            q.edit_message_text("✅ Joined! Use /start")
        else:
            q.edit_message_text("⚠️ Still need to join:", reply_markup=force_join_kb(not_joined))
        return
    
    elif data == "my_stats":
        conn = get_db()
        u = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        if u:
            links = conn.execute("SELECT COUNT(*) FROM referral_links WHERE user_id=?", (uid,)).fetchone()[0]
            refs = conn.execute("SELECT SUM(total_referrals) FROM referral_links WHERE user_id=?", (uid,)).fetchone()[0] or 0
            q.edit_message_text(
                f"📊 **Your Stats**\n\n🆔 `{uid}`\n👤 {u['first_name']}\n💰 Coins: **{u['coins']}**\n"
                f"📋 Links: {links}\n🔁 Referrals: {int(refs)}\n📅 Today: {u['daily_referrals']}/10\n"
                f"👥 Referred by: {u['referred_by'] if u['referred_by'] else 'None'}",
                parse_mode=ParseMode.MARKDOWN
            )
        conn.close()
        return
    
    elif data == "submit_link":
        q.edit_message_text(
            "🔗 **Submit a Referral Link**\n\n"
            "Send me a Telegram bot referral link and I'll:\n"
            "✅ Send `/start CODE` to the target bot\n"
            "✅ Solve CAPTCHAs (math, text, number, buttons)\n"
            "✅ Auto-join required channels\n"
            "✅ Make your referral look **100% real**\n\n"
            "**Format:** `https://t.me/BotName?start=CODE`\n"
            "**Cost:** 1 coin per referral\n"
            "**Limit:** 10 per day\n\n_Send the link now!_",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    elif data == "buy_coins":
        conn = get_db()
        u = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        conn.close()
        coins = u['coins'] if u else 0
        q.edit_message_text(
            f"💰 **Balance: {coins} coins**\n\n"
            "**Buy coins:** Contact admin\n"
            "**Free coins:**\n• Refer friends (1 coin each)\n• Redeem promocodes: /redeem CODE\n• Join giveaways",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    elif data == "promocodes":
        conn = get_db()
        codes = conn.execute("SELECT * FROM promocodes WHERE is_active=1").fetchall()
        conn.close()
        if not codes:
            q.edit_message_text("🎁 No active promocodes.")
        else:
            txt = "🎁 **Promocodes**\n\n"
            for c in codes[:10]:
                rem = c['max_uses'] - c['current_uses']
                txt += f"🔑 `{c['code']}` — **{c['coins']} coins** ({rem}/{c['max_uses']} left)\n"
            txt += "\nUse: /redeem CODE"
            q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN)
        return
    
    elif data == "refer_friends":
        link = f"https://t.me/{context.bot.username}?start={uid}"
        q.edit_message_text(
            f"👥 **Refer Friends**\n\nShare your link. Get **1 coin** per referral!\n\n🔗 `{link}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # ====== ADMIN ======
    elif data.startswith("admin_"):
        if not is_admin(uid):
            q.answer("⛔ Unauthorized!", show_alert=True)
            return
        
        action = data.replace("admin_", "")
        
        if action == "panel":
            kb = [
                [InlineKeyboardButton("💰 Send Coins", callback_data="admin_send_coins")],
                [InlineKeyboardButton("💸 Remove Coins", callback_data="admin_remove_coins")],
                [InlineKeyboardButton("👤 User Stats", callback_data="admin_user_stats")],
                [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
                [InlineKeyboardButton("🔇 Ban User", callback_data="admin_ban")],
                [InlineKeyboardButton("🔊 Unban User", callback_data="admin_unban")],
                [InlineKeyboardButton("📡 Force Join Channels", callback_data="admin_channels")],
                [InlineKeyboardButton("🎁 Giveaways", callback_data="admin_giveaway")],
                [InlineKeyboardButton("🔑 Promocodes", callback_data="admin_promocode")],
                [InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings")],
                [InlineKeyboardButton("📊 Global Stats", callback_data="admin_global")],
                [InlineKeyboardButton("« Back", callback_data="back_main")],
            ]
            q.edit_message_text("⚙️ **Admin Panel**", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
        
        elif action == "global":
            conn = get_db()
            tu = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            tc = conn.execute("SELECT SUM(coins) FROM users").fetchone()[0] or 0
            tr = conn.execute("SELECT SUM(total_referrals) FROM referral_links").fetchone()[0] or 0
            tb = conn.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0]
            conn.close()
            kb = [[InlineKeyboardButton("« Back", callback_data="admin_panel")]]
            q.edit_message_text(
                f"📊 **Global Stats**\n\n👥 Users: {tu}\n💰 Total coins: {int(tc)}\n🔁 Referrals: {int(tr)}\n🚫 Banned: {tb}",
                reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN
            )
        
        elif action in ["send_coins", "remove_coins", "user_stats", "broadcast", "ban", "unban", 
                         "add_channel", "remove_channel", "create_giveaway", "create_promo",
                         "disable_promo", "set_welcome", "set_refmsg", "set_dailylimit"]:
            prompts = {
                "send_coins": "💰 Send coins. Format: `user_id amount`\nExample: `123456789 50`",
                "remove_coins": "💸 Remove coins. Format: `user_id amount`\nExample: `123456789 20`",
                "user_stats": "👤 Send user ID.\nExample: `123456789`",
                "broadcast": "📢 Send message to broadcast to ALL users:",
                "ban": "🔇 Send user ID to ban.\nExample: `123456789`",
                "unban": "🔊 Send user ID to unban.\nExample: `123456789`",
                "add_channel": "➕ Format: `channel_id channel_username channel_name`\nExample: `-100123 @my_channel My Channel`",
                "remove_channel": "❌ Send channel ID or username.\nExample: `-100123456789`",
                "create_giveaway": "🎁 Format: `prize_coins winners`\nExample: `100 3`",
                "create_promo": "🔑 Format: `coins max_uses [custom_code]`\nExample: `50 20` or `100 5 SUMMER`",
                "disable_promo": "❌ Send promocode to disable.\nExample: `SUMMER`",
                "set_welcome": "📝 Send new welcome message. Use `{name}` placeholder.",
                "set_refmsg": "📝 Send new referral message. Use `{referred_name}` placeholder.",
                "set_dailylimit": "📊 Send number for daily limit.\nExample: `10`",
            }
            context.user_data['admin_action'] = action
            q.edit_message_text(prompts.get(action, "Send details:"), parse_mode=ParseMode.MARKDOWN)
        
        elif action == "channels":
            kb = [
                [InlineKeyboardButton("➕ Add", callback_data="admin_add_channel")],
                [InlineKeyboardButton("❌ Remove", callback_data="admin_remove_channel")],
                [InlineKeyboardButton("📋 List", callback_data="admin_list_channels")],
                [InlineKeyboardButton("« Back", callback_data="admin_panel")],
            ]
            q.edit_message_text("📡 **Force Join Channels**", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
        
        elif action == "list_channels":
            conn = get_db()
            chs = conn.execute("SELECT * FROM force_channels").fetchall()
            conn.close()
            if not chs:
                kb = [[InlineKeyboardButton("« Back", callback_data="admin_channels")]]
                q.edit_message_text("No channels.", reply_markup=InlineKeyboardMarkup(kb))
                return
            txt = "📋 **Channels**\n\n"
            for ch in chs:
                txt += f"📢 **{ch['channel_name']}**\nID: `{ch['channel_id']}`\nUsername: {ch['channel_username']}\n\n"
            kb = [[InlineKeyboardButton("« Back", callback_data="admin_channels")]]
            q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
        
        elif action == "giveaway":
            kb = [
                [InlineKeyboardButton("➕ Create", callback_data="admin_create_giveaway")],
                [InlineKeyboardButton("🎲 Pick Winners", callback_data="admin_pick_winners")],
                [InlineKeyboardButton("« Back", callback_data="admin_panel")],
            ]
            q.edit_message_text("🎁 **Giveaways**", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
        
        elif action == "pick_winners":
            conn = get_db()
            gs = conn.execute("SELECT * FROM giveaways WHERE is_active=1").fetchall()
            conn.close()
            if not gs:
                q.edit_message_text("No active giveaways.")
                return
            txt = "Select giveaway:\n\n"
            kb = []
            for g in gs:
                txt += f"#{g['id']}: {g['prize_coins']} coins, {g['winners_count']} winners\n"
                kb.append([InlineKeyboardButton(f"Pick #{g['id']}", callback_data=f"pick_{g['id']}")])
            kb.append([InlineKeyboardButton("« Back", callback_data="admin_giveaway")])
            q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
        
        elif data.startswith("pick_"):
            gid = int(data.replace("pick_", ""))
            conn = get_db()
            g = conn.execute("SELECT * FROM giveaways WHERE id=?", (gid,)).fetchone()
            if not g or not g['is_active']:
                q.edit_message_text("Giveaway not found.")
                conn.close()
                return
            parts = json.loads(g['participants'])
            if not parts:
                q.edit_message_text("No participants.")
                conn.close()
                return
            wc = min(g['winners_count'], len(parts))
            winners = random.sample(parts, wc)
            conn.execute("UPDATE giveaways SET winners=?, is_active=0 WHERE id=?", (json.dumps(winners), gid))
            for w in winners:
                conn.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (g['prize_coins'], w))
                try:
                    context.bot.send_message(chat_id=w, text=f"🎉 You won **{g['prize_coins']} coins** in giveaway #{gid}!", parse_mode=ParseMode.MARKDOWN)
                except:
                    pass
            conn.commit()
            conn.close()
            q.edit_message_text(f"✅ Winners: `{', '.join([str(w) for w in winners])}`\nEach got {g['prize_coins']} coins!")
        
        elif action == "promocode":
            kb = [
                [InlineKeyboardButton("➕ Create", callback_data="admin_create_promo")],
                [InlineKeyboardButton("📋 List", callback_data="admin_list_promo")],
                [InlineKeyboardButton("❌ Disable", callback_data="admin_disable_promo")],
                [InlineKeyboardButton("« Back", callback_data="admin_panel")],
            ]
            q.edit_message_text("🔑 **Promocodes**", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
        
        elif action == "list_promo":
            conn = get_db()
            codes = conn.execute("SELECT * FROM promocodes ORDER BY is_active DESC").fetchall()
            conn.close()
            if not codes:
                kb = [[InlineKeyboardButton("« Back", callback_data="admin_promocode")]]
                q.edit_message_text("No promocodes.", reply_markup=InlineKeyboardMarkup(kb))
                return
            txt = "🔑 **All Promocodes**\n\n"
            for c in codes:
                st = "✅" if c['is_active'] else "❌"
                txt += f"{st} `{c['code']}` — {c['coins']} coins ({c['current_uses']}/{c['max_uses']})\n"
            kb = [[InlineKeyboardButton("« Back", callback_data="admin_promocode")]]
            q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
        
        elif action == "settings":
            kb = [
                [InlineKeyboardButton("📝 Welcome Message", callback_data="admin_set_welcome")],
                [InlineKeyboardButton("📝 Referral Message", callback_data="admin_set_refmsg")],
                [InlineKeyboardButton("📊 Daily Limit", callback_data="admin_set_dailylimit")],
                [InlineKeyboardButton("« Back", callback_data="admin_panel")],
            ]
            q.edit_message_text("⚙️ **Settings**", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)
    
    elif data == "back_main":
        u = update.effective_user
        conn = get_db()
        w = conn.execute("SELECT value FROM settings WHERE key='welcome_message'").fetchone()['value']
        conn.close()
        kb = [
            [InlineKeyboardButton("📊 My Stats", callback_data="my_stats")],
            [InlineKeyboardButton("🔗 Submit Referral Link", callback_data="submit_link")],
            [InlineKeyboardButton("💰 Balance & Buy Coins", callback_data="buy_coins")],
            [InlineKeyboardButton("🎁 Promocodes", callback_data="promocodes")],
            [InlineKeyboardButton("👥 Refer Friends", callback_data="refer_friends")],
        ]
        if is_admin(uid):
            kb.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])
        q.edit_message_text(w.format(name=u.first_name), reply_markup=InlineKeyboardMarkup(kb))

# ========== MESSAGE HANDLER ==========

def handle_msg(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    text = update.message.text
    if is_banned(uid):
        update.message.reply_text("❌ Banned.")
        return
    
    joined, not_joined = check_force_join(uid, context)
    if not joined:
        update.message.reply_text("⚠️ Join channels:", reply_markup=force_join_kb(not_joined))
        return
    
    action = context.user_data.get('admin_action')
    
    # Admin actions
    if action and is_admin(uid):
        conn = get_db()
        
        if action == "send_coins":
            try:
                p = text.split()
                tid, amt = int(p[0]), int(p[1])
                conn.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (amt, tid))
                conn.commit()
                update.message.reply_text(f"✅ Sent {amt} coins to `{tid}`", parse_mode=ParseMode.MARKDOWN)
                try: context.bot.send_message(chat_id=tid, text=f"💰 You received **{amt} coins** from admin!", parse_mode=ParseMode.MARKDOWN)
                except: pass
            except: update.message.reply_text("❌ Format: `user_id amount`", parse_mode=ParseMode.MARKDOWN)
        
        elif action == "remove_coins":
            try:
                p = text.split()
                tid, amt = int(p[0]), int(p[1])
                conn.execute("UPDATE users SET coins = MAX(0, coins - ?) WHERE user_id=?", (amt, tid))
                conn.commit()
                update.message.reply_text(f"✅ Removed {amt} coins from `{tid}`", parse_mode=ParseMode.MARKDOWN)
            except: update.message.reply_text("❌ Format: `user_id amount`", parse_mode=ParseMode.MARKDOWN)
        
        elif action == "user_stats":
            try:
                tid = int(text.strip())
                u = conn.execute("SELECT * FROM users WHERE user_id=?", (tid,)).fetchone()
                if u:
                    update.message.reply_text(
                        f"👤 **Stats**\n\n🆔 `{u['user_id']}`\n👤 {u['first_name']}\n"
                        f"📛 @{u['username'] or 'None'}\n💰 {u['coins']}\n📅 {u['joined_date']}\n"
                        f"🚫 {'Banned' if u['is_banned'] else 'No'}\n👥 Referred by: {u['referred_by'] or 'None'}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    update.message.reply_text("❌ Not found.")
            except: update.message.reply_text("❌ Invalid ID.")
        
        elif action == "broadcast":
            users = conn.execute("SELECT user_id FROM users WHERE is_banned=0").fetchall()
            sent = failed = 0
            for u in users:
                try:
                    context.bot.send_message(chat_id=u['user_id'], text=text)
                    sent += 1
                except: failed += 1
            update.message.reply_text(f"📢 Broadcast: ✅ {sent} sent, ❌ {failed} failed")
        
        elif action == "ban_user":
            try:
                tid = int(text.strip())
                conn.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (tid,))
                conn.commit()
                update.message.reply_text(f"✅ Banned `{tid}`", parse_mode=ParseMode.MARKDOWN)
            except: update.message.reply_text("❌ Invalid ID.")
        
        elif action == "unban_user":
            try:
                tid = int(text.strip())
                conn.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (tid,))
                conn.commit()
                update.message.reply_text(f"✅ Unbanned `{tid}`", parse_mode=ParseMode.MARKDOWN)
            except: update.message.reply_text("❌ Invalid ID.")
        
        elif action == "add_channel":
            try:
                p = text.split()
                if len(p) >= 3:
                    conn.execute("INSERT INTO force_channels (channel_id, channel_username, channel_name) VALUES (?,?,?)",
                                 (p[0], p[1], ' '.join(p[2:])))
                    conn.commit()
                    update.message.reply_text(f"✅ Added channel")
                else:
                    update.message.reply_text("❌ Format: `channel_id channel_username channel_name`", parse_mode=ParseMode.MARKDOWN)
            except Exception as e: update.message.reply_text(f"❌ {e}")
        
        elif action == "remove_channel":
            try:
                ident = text.strip()
                conn.execute("DELETE FROM force_channels WHERE channel_id=? OR channel_username=?", (ident, ident))
                conn.commit()
                update.message.reply_text(f"✅ Removed matching channel.")
            except: update.message.reply_text("❌ Error.")
        
        elif action == "create_giveaway":
            try:
                p = text.split()
                prize, winners = int(p[0]), int(p[1])
                conn.execute("INSERT INTO giveaways (prize_coins, winners_count, created_at) VALUES (?,?,?)",
                             (prize, winners, datetime.now().isoformat()))
                conn.commit()
                update.message.reply_text(f"✅ Giveaway: {prize} coins, {winners} winners")
            except: update.message.reply_text("❌ Format: `prize_coins winners`", parse_mode=ParseMode.MARKDOWN)
        
        elif action == "create_promo":
            try:
                p = text.split()
                if len(p) == 2:
                    coins, mu = int(p[0]), int(p[1])
                    code = gen_code()
                elif len(p) >= 3:
                    coins, mu = int(p[0]), int(p[1])
                    code = p[2].upper()
                else:
                    update.message.reply_text("❌ Format: `coins max_uses [code]`", parse_mode=ParseMode.MARKDOWN)
                    conn.close()
                    context.user_data.pop('admin_action', None)
                    return
                conn.execute("INSERT INTO promocodes (code, coins, max_uses, created_by) VALUES (?,?,?,?)",
                             (code, coins, mu, uid))
                conn.commit()
                update.message.reply_text(f"✅ Promocode `{code}` — {coins} coins, {mu} uses", parse_mode=ParseMode.MARKDOWN)
            except Exception as e: update.message.reply_text(f"❌ {e}")
        
        elif action == "disable_promo":
            code = text.strip().upper()
            conn.execute("UPDATE promocodes SET is_active=0 WHERE code=?", (code,))
            conn.commit()
            update.message.reply_text(f"✅ Disabled `{code}`", parse_mode=ParseMode.MARKDOWN)
        
        elif action == "set_welcome":
            conn.execute("UPDATE settings SET value=? WHERE key='welcome_message'", (text,))
            conn.commit()
            update.message.reply_text("✅ Welcome message updated!")
        
        elif action == "set_refmsg":
            conn.execute("UPDATE settings SET value=? WHERE key='referral_message'", (text,))
            conn.commit()
            update.message.reply_text("✅ Referral message updated!")
        
        elif action == "set_dailylimit":
            conn.execute("UPDATE settings SET value=? WHERE key='daily_limit'", (text.strip(),))
            conn.commit()
            update.message.reply_text(f"✅ Daily limit set to {text.strip()}")
        
        conn.close()
        context.user_data.pop('admin_action', None)
        return
    
    # Handle referral links
    if 't.me/' in text and 'start=' in text:
        handle_referral(update, context)
        return
    
    # Handle /redeem
    if text.startswith('/redeem '):
        code = text.replace('/redeem ', '').strip().upper()
        conn = get_db()
        p = conn.execute("SELECT * FROM promocodes WHERE code=? AND is_active=1", (code,)).fetchone()
        if not p:
            update.message.reply_text("❌ Invalid or expired code.")
            conn.close()
            return
        if p['current_uses'] >= p['max_uses']:
            update.message.reply_text("❌ Code fully used.")
            conn.close()
            return
        conn.execute("UPDATE promocodes SET current_uses = current_uses + 1 WHERE code=?", (code,))
        conn.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (p['coins'], uid))
        conn.commit()
        conn.close()
        update.message.reply_text(f"🎉 **Redeemed!** You got **{p['coins']} coins**!", parse_mode=ParseMode.MARKDOWN)
        return
    
    if text.startswith('/redeem'):
        update.message.reply_text("Usage: `/redeem CODE`", parse_mode=ParseMode.MARKDOWN)
        return
    
    update.message.reply_text("Send a referral link like `https://t.me/BotName?start=CODE` or use /start", parse_mode=ParseMode.MARKDOWN)

# ========== MAIN ==========

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_msg))
    
    # Start Telethon in background
    def start_telethon():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            telethon_client.start(phone=TELEGRAM_PHONE)
            logger.info("✅ Telethon client ready")
        except Exception as e:
            logger.error(f"❌ Telethon: {e}")
    
    threading.Thread(target=start_telethon, daemon=True).start()
    
    updater.start_polling()
    logger.info("🤖 Bot is running...")
    updater.idle()

if __name__ == '__main__':
    main()
