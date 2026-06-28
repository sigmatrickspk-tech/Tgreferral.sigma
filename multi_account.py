import asyncio
import logging
import sqlite3
import random
import time
import json
from telethon import TelegramClient, functions
from telethon.errors import (
    FloodWaitError, PhoneNumberBannedError, SessionPasswordNeededError
)
from captcha_solver import CaptchaSolver
from config import DB_PATH

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== CONFIG ==========
API_ID = 123456  # REPLACE
API_HASH = "YOUR_API_HASH"  # REPLACE

class ReferralAccount:
    """Single Telegram account used for sending referrals"""
    
    def __init__(self, phone, session_name=None):
        self.phone = phone
        self.session = session_name or f"acc_{phone.replace('+', '')}"
        self.client = TelegramClient(self.session, API_ID, API_HASH)
        self.ready = False
        self.banned = False
        self.daily_count = 0
        self.last_used = 0
        self.user_id = None
    
    async def connect(self):
        try:
            await self.client.connect()
            if not await self.client.is_user_authorized():
                await self.client.send_code_request(self.phone)
                code = input(f"📱 Code for {self.phone}: ")
                try:
                    await self.client.sign_in(self.phone, code)
                except SessionPasswordNeededError:
                    pwd = input(f"🔑 2FA for {self.phone}: ")
                    await self.client.sign_in(password=pwd)
            me = await self.client.get_me()
            self.user_id = me.id
            self.ready = True
            logger.info(f"✅ Account ready: {me.phone or me.username} (ID: {me.id})")
            return True
        except PhoneNumberBannedError:
            logger.error(f"❌ BANNED: {self.phone}")
            self.banned = True
            return False
        except Exception as e:
            logger.error(f"❌ Failed {self.phone}: {e}")
            return False
    
    async def send_referral(self, bot_username, ref_code):
        if not self.ready or self.banned:
            return {'success': False, 'error': 'Account not ready'}
        
        try:
            solver = CaptchaSolver(self.client)
            result = await solver.solve_bot_captcha(bot_username, ref_code)
            self.daily_count += 1
            self.last_used = time.time()
            
            # Random delay 2-5s between accounts
            await asyncio.sleep(random.uniform(2, 5))
            
            return result
            
        except FloodWaitError as e:
            logger.warning(f"⏳ Flood {self.phone}: {e.seconds}s")
            await asyncio.sleep(e.seconds)
            return {'success': False, 'error': f'Flood {e.seconds}s'}
        except Exception as e:
            logger.error(f"❌ Error {self.phone}: {e}")
            return {'success': False, 'error': str(e)[:200]}
    
    async def disconnect(self):
        if self.client:
            await self.client.disconnect()
            self.ready = False


class AccountPool:
    """Manages multiple Telegram accounts for referral farming"""
    
    def __init__(self):
        self.accounts = []
        self.queue = []
        self.running = False
        self.stats = {
            'total_sent': 0,
            'total_success': 0,
            'total_failed': 0,
            'captchas_solved': 0,
            'channels_joined': 0
        }
    
    def add_account(self, phone):
        acc = ReferralAccount(phone)
        self.accounts.append(acc)
        return acc
    
    def add_accounts_from_file(self, filepath):
        """Load accounts from file, one phone per line"""
        with open(filepath) as f:
            for line in f:
                phone = line.strip()
                if phone:
                    self.add_account(phone)
    
    async def connect_all(self):
        tasks = [acc.connect() for acc in self.accounts]
        results = await asyncio.gather(*tasks)
        ready = sum(1 for r in results if r)
        logger.info(f"📊 {ready}/{len(self.accounts)} accounts ready")
        return ready
    
    async def get_available_account(self):
        if not self.accounts:
            return None
        
        # Round-robin with cooldown check
        for _ in range(len(self.accounts) * 2):
            for acc in self.accounts:
                if acc.ready and not acc.banned:
                    if time.time() - acc.last_used > 3:  # 3s cooldown
                        return acc
            await asyncio.sleep(1)
        
        # If all busy, wait
        await asyncio.sleep(3)
        return await self.get_available_account()
    
    def add_to_queue(self, bot_username, ref_code, count=1, user_id=None):
        self.queue.append({
            'bot': bot_username,
            'code': ref_code,
            'count': count,
            'user_id': user_id
        })
        logger.info(f"📝 Queued: {count}x @{bot_username}?start={ref_code}")
    
    async def process_queue(self):
        self.running = True
        while self.running and self.queue:
            job = self.queue.pop(0)
            
            for i in range(job['count']):
                acc = await self.get_available_account()
                if not acc:
                    logger.error("❌ No available accounts!")
                    break
                
                logger.info(f"🎯 [{acc.phone}] Sending: @{job['bot']}?start={job['code']} ({i+1}/{job['count']})")
                
                result = await acc.send_referral(job['bot'], job['code'])
                
                self.stats['total_sent'] += 1
                
                if result.get('success'):
                    self.stats['total_success'] += 1
                    if result.get('solved'):
                        self.stats['captchas_solved'] += 1
                    if result.get('channels_joined'):
                        self.stats['channels_joined'] += len(result['channels_joined'])
                    
                    # Update DB
                    conn = sqlite3.connect(DB_PATH)
                    conn.execute(
                        "UPDATE referral_links SET total_referrals = total_referrals + 1 "
                        "WHERE bot_username=? AND ref_code=?",
                        (job['bot'], job['code'])
                    )
                    conn.commit()
                    conn.close()
                    
                    logger.info(f"✅ SUCCESS [{acc.phone}] @{job['bot']}")
                else:
                    self.stats['total_failed'] += 1
                    logger.warning(f"❌ FAILED [{acc.phone}] @{job['bot']}: {result.get('error', 'Unknown')}")
                
                # Random delay between referrals
                await asyncio.sleep(random.uniform(3, 8))
            
            # Delay between different jobs
            await asyncio.sleep(random.uniform(5, 10))
        
        self.running = False
        logger.info(f"📊 Queue complete: {self.stats}")
    
    async def disconnect_all(self):
        self.running = False
        tasks = [acc.disconnect() for acc in self.accounts if acc.ready]
        await asyncio.gather(*tasks)
        logger.info("🔌 All accounts disconnected")
    
    def get_stats(self):
        return self.stats


# ========== STANDALONE USAGE ==========

async def main():
    pool = AccountPool()
    
    # Add accounts (one per SIM/virtual number)
    pool.add_account("+1234567890")
    pool.add_account("+1234567891")
    pool.add_account("+1234567892")
    
    # Or load from file
    # pool.add_accounts_from_file("accounts.txt")
    
    ready = await pool.connect_all()
    if ready == 0:
        logger.error("❌ No accounts available!")
        return
    
    # Queue up referrals
    pool.add_to_queue("TargetBot", "ref_ABC123", count=5)
    pool.add_to_queue("AnotherBot", "start_XYZ", count=3)
    
    # Process everything
    await pool.process_queue()
    
    # Show results
    logger.info(f"Final Stats: {pool.get_stats()}")
    
    await pool.disconnect_all()


if __name__ == "__main__":
    asyncio.run(main())
