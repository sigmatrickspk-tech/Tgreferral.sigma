# 🤖 Telegram Referral Bot

Full-featured Telegram bot that makes **valid referrals** to any Telegram bot by:
- Sending `/start CODE` to target bots
- **Solving CAPTCHAs** (math, text, number, button click)
- **Auto-joining channels** required for verification
- Making referrals look **100% real**

## 📋 Features

### User Features
- 🔗 Submit any bot's referral link
- ✅ Auto CAPTCHA solving (math, text, number, buttons)
- 📢 Auto-join required channels for valid referrals
- 💰 Coin system (buy from admin, earn via referrals)
- 👥 Refer friends to earn free coins
- 🎁 Promocode redemption
- 🎲 Giveaway participation
- 📊 Personal stats tracking

### Admin Features
- ⚙️ Full admin panel with buttons
- 💰 Send/remove coins from users
- 👤 View any user's stats
- 📢 Broadcast messages to all users
- 🔇 Ban/unban users
- 📡 Force join channels (add/remove/list)
- 🎁 Create giveaways & pick winners
- 🔑 Create/list/disable promocodes
- ⚙️ Customize welcome/referral messages
- 📊 Global bot statistics

## 🚀 Quick Start

### 1. Get Credentials

| What | Where | Notes |
|------|-------|-------|
| Bot Token | [@BotFather](https://t.me/BotFather) | Create new bot, get token |
| Your User ID | [@userinfobot](https://t.me/userinfobot) | To set yourself as admin |
| API ID + Hash | [my.telegram.org](https://my.telegram.org/apps) | For Telethon (sending referrals) |
| Phone Number | Your SIM / virtual number | For Telethon account |

### 2. Configure

Edit `config.py`:
```python
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # From BotFather
ADMIN_IDS = [123456789]  # Your Telegram ID
