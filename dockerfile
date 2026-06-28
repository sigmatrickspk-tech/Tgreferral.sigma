FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py main.py captcha_solver.py multi_account.py ./
COPY referral_bot.db /app/

# For Telethon session files
VOLUME /app/sessions

CMD ["python", "main.py"]
