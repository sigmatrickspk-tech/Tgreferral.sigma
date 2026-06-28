#!/bin/bash

echo "=========================================="
echo "  Telegram Referral Bot - Auto Deploy"
echo "=========================================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python3 not found. Installing...${NC}"
    apt update && apt install -y python3 python3-pip
fi

# Install dependencies
echo -e "${YELLOW}📦 Installing dependencies...${NC}"
pip3 install -r requirements.txt

# Check config
if ! grep -q "YOUR_BOT_TOKEN_HERE" config.py; then
    echo -e "${GREEN}✅ Bot token configured${NC}"
else
    echo -e "${RED}⚠️  Edit config.py and set your BOT_TOKEN and ADMIN_IDS${NC}"
fi

# Create systemd service
echo -e "${YELLOW}⚙️  Creating systemd service...${NC}"
cat > /etc/systemd/system/referral-bot.service << 'EOF'
[Unit]
Description=Telegram Referral Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/referral_bot
ExecStart=/usr/bin/python3 /root/referral_bot/main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable referral-bot
systemctl start referral-bot

echo -e "${GREEN}=========================================="
echo "  ✅ Deployment Complete!"
echo "=========================================="
echo ""
echo "Commands:"
echo "  Start:   systemctl start referral-bot"
echo "  Stop:    systemctl stop referral-bot"
echo "  Status:  systemctl status referral-bot"
echo "  Logs:    journalctl -u referral-bot -f"
echo "==========================================${NC}"
