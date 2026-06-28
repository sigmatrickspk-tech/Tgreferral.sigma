import asyncio
import logging
import re
import random
import time
from telethon import TelegramClient, functions
from telethon.tl.types import (
    KeyboardButtonCallback, KeyboardButtonUrl, ReplyInlineMarkup
)
from telethon.errors import FloodWaitError, RPCError

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CaptchaSolver:
    """
    Handles CAPTCHA solving for Telegram bot referrals.
    Supports: button CAPTCHAs, math CAPTCHAs, text CAPTCHAs, number CAPTCHAs, channel joins
    """
    
    def __init__(self, client: TelegramClient):
        self.client = client
    
    async def solve_bot_captcha(self, bot_username: str, ref_code: str) -> dict:
        """
        Complete the full referral flow: send /start, detect captcha, solve it, join channels
        
        Returns:
            {
                'success': bool,
                'captcha_type': str | None,
                'solved': bool,
                'channels_joined': list,
                'details': str
            }
        """
        result = {
            'success': False,
            'captcha_type': None,
            'solved': False,
            'channels_joined': [],
            'details': ''
        }
        
        try:
            bot = await self.client.get_entity(bot_username)
            
            # Send the /start command with referral code
            msg = await self.client.send_message(bot, f"/start {ref_code}")
            logger.info(f"📤 Sent /start {ref_code} to @{bot_username}")
            
            # Wait for bot response
            await asyncio.sleep(random.uniform(2, 4))
            
            # Get the bot's response messages
            async for response in self.client.iter_messages(bot, limit=10):
                if response.id <= msg.id:
                    continue
                
                response_text = response.text or ""
                buttons = self._extract_buttons(response)
                
                logger.info(f"🤖 Bot says: {response_text[:150]}")
                
                # ====== DETECT AND HANDLE CAPTCHA TYPES ======
                
                # 1. CHANNEL JOIN REQUIRED
                if await self._is_channel_join_request(response_text, buttons):
                    channels = self._extract_channels(response_text, buttons)
                    result['captcha_type'] = 'channel_join'
                    
                    for channel_info in channels:
                        joined = await self._join_channel(channel_info)
                        if joined:
                            result['channels_joined'].append(
                                channel_info.get('username', str(channel_info))
                            )
                    
                    # After joining, click "Joined" button or resend /start
                    await asyncio.sleep(random.uniform(2, 4))
                    
                    # Look for a "Joined" / "Done" / "✅" button
                    done_button = self._find_verification_button(buttons)
                    if done_button:
                        await self._click_callback_button(bot, response, done_button)
                    else:
                        await self.client.send_message(bot, "/start")
                    
                    await asyncio.sleep(random.uniform(2, 3))
                    continue
                
                # 2. CALLBACK / INLINE BUTTON CAPTCHA
                if buttons and self._is_button_captcha(response_text, buttons):
                    result['captcha_type'] = 'button'
                    
                    # Try clicking "Verify", "I'm human", "Start", the only button, etc.
                    target_btn = self._find_verify_button(buttons)
                    if target_btn:
                        await self._click_callback_button(bot, response, target_btn)
                        result['solved'] = True
                        logger.info(f"✅ Clicked button: {target_btn['text']}")
                        await asyncio.sleep(random.uniform(1.5, 3))
                        continue
                
                # 3. MATH CAPTCHA (e.g. "3 + 5 = ?")
                if self._is_math_captcha(response_text):
                    result['captcha_type'] = 'math'
                    answer = self._solve_math(response_text)
                    if answer is not None:
                        await self.client.send_message(bot, str(answer))
                        result['solved'] = True
                        logger.info(f"✅ Solved math captcha: {answer}")
                        await asyncio.sleep(random.uniform(1.5, 3))
                        continue
                
                # 4. TEXT CAPTCHA (e.g. "type: ABCD123")
                text_answer = self._solve_text_captcha(response_text)
                if text_answer:
                    result['captcha_type'] = 'text'
                    await self.client.send_message(bot, text_answer)
                    result['solved'] = True
                    logger.info(f"✅ Solved text captcha: {text_answer}")
                    await asyncio.sleep(random.uniform(1.5, 3))
                    continue
                
                # 5. NUMBER CAPTCHA (e.g. "press 7")
                number_answer = self._extract_number(response_text)
                if number_answer:
                    result['captcha_type'] = 'number'
                    await self.client.send_message(bot, str(number_answer))
                    result['solved'] = True
                    logger.info(f"✅ Solved number captcha: {number_answer}")
                    await asyncio.sleep(random.uniform(1.5, 3))
                    continue
                
                # 6. MULTI-STEP: More buttons after first action
                if buttons:
                    more_btn = self._find_continue_button(buttons)
                    if more_btn:
                        await self._click_callback_button(bot, response, more_btn)
                        await asyncio.sleep(random.uniform(1.5, 3))
                        continue
            
            # ====== FINAL VERIFICATION ======
            await asyncio.sleep(random.uniform(2, 4))
            success = await self._verify_referral_success(bot)
            
            if success:
                result['success'] = True
                result['details'] = 'Referral verified successfully'
            else:
                # Check last message for success keywords
                async for final_msg in self.client.iter_messages(bot, limit=3):
                    if final_msg.id <= msg.id:
                        continue
                    final_text = final_msg.text or ""
                    if any(word in final_text.lower() for word in [
                        'welcome', 'success', 'confirmed', 'verified',
                        'complete', 'approved', 'bonus', 'earned',
                        'referral accepted', 'points added', 'coins added',
                        'you are in', 'done', 'congratulations'
                    ]):
                        result['success'] = True
                        result['details'] = final_text[:200]
                        break
            
            if result['success']:
                logger.info(f"✅ Referral to @{bot_username} SUCCESSFUL!")
            else:
                logger.warning(f"⚠️ Referral to @{bot_username} may have failed")
            
        except FloodWaitError as e:
            logger.warning(f"⏳ Flood wait: {e.seconds}s")
            result['details'] = f"Flood wait: {e.seconds}s"
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            result['details'] = str(e)[:200]
        
        return result
    
    def _extract_buttons(self, message):
        """Extract all buttons from a message"""
        buttons = []
        if message.reply_markup:
            for row in message.reply_markup.rows:
                for btn in row.buttons:
                    btn_info = {
                        'text': btn.text,
                        'type': 'callback' if hasattr(btn, 'data') else 'url' if hasattr(btn, 'url') else 'unknown'
                    }
                    if hasattr(btn, 'data'):
                        btn_info['data'] = btn.data
                    if hasattr(btn, 'url'):
                        btn_info['url'] = btn.url
                    buttons.append(btn_info)
        return buttons
    
    async def _is_channel_join_request(self, text, buttons):
        """Detect if bot is asking to join channels"""
        text_lower = text.lower()
        
        # Text indicators
        indicators = [
            'join', 'subscribe', 'channel', 'must join', 'please join',
            'follow', 'click to join', 'join our', 'join the'
        ]
        
        if any(ind in text_lower for ind in indicators):
            return True
        
        # Button indicators
        for btn in buttons:
            btn_lower = btn['text'].lower()
            if any(ind in btn_lower for ind in ['join', 'subscribe', 'channel', 'follow']):
                return True
        
        return False
    
    def _extract_channels(self, text, buttons):
        """Extract channel usernames from text and buttons"""
        channels = []
        
        # Extract from text: @username
        mentions = re.findall(r'@(\w+)', text)
        for mention in mentions:
            if mention.lower() not in ['bot', 'channel', 'admin', 'all']:
                channels.append({'username': mention, 'source': 'text'})
        
        # Extract from URL buttons
        for btn in buttons:
            if btn['type'] == 'url':
                url = btn.get('url', '')
                match = re.search(r't\.me/(\w+)', url)
                if match:
                    channels.append({
                        'username': match.group(1),
                        'source': 'button',
                        'url': url,
                        'button_text': btn['text']
                    })
        
        return channels
    
    async def _join_channel(self, channel_info):
        """Join a Telegram channel"""
        try:
            username = channel_info.get('username', '')
            if not username.startswith('@'):
                username = '@' + username
            
            entity = await self.client.get_entity(username)
            await self.client(functions.channels.JoinChannelRequest(entity))
            logger.info(f"✅ Joined channel: {username}")
            await asyncio.sleep(random.uniform(3, 6))
            return True
        except Exception as e:
            logger.warning(f"⚠️ Could not join {channel_info.get('username', '')}: {e}")
            return False
    
    def _find_verification_button(self, buttons):
        """Find 'Joined', 'Done', '✅' buttons after joining channels"""
        for btn in buttons:
            text = btn['text'].lower()
            if any(word in text for word in ['joined', 'done', '✅', 'check', 'verify', 'complete']):
                return btn
        return None
    
    def _is_button_captcha(self, text, buttons):
        """Detect button-based captcha"""
        text_lower = text.lower()
        
        button_indicators = [
            'click', 'press', 'tap', 'select', 'choose', 'verify',
            'not a robot', 'i\'m human', 'captcha', 'confirm',
            'start', 'check', 'go to bot', 'open bot', 'human'
        ]
        
        if any(ind in text_lower for ind in button_indicators):
            return True
        
        # If there's only 1-2 callback buttons, likely a captcha
        callback_buttons = [b for b in buttons if b['type'] == 'callback']
        if len(callback_buttons) in [1, 2]:
            return True
        
        return False
    
    def _find_verify_button(self, buttons):
        """Find the 'Verify', 'I'm human', or primary action button"""
        priority_keywords = [
            'verify', 'i\'m human', 'not a robot', 'i am human',
            'start', 'go', 'check', 'confirm', 'human', 'robot',
            'tap here', 'click here', 'open', 'done'
        ]
        
        # First try priority keywords
        for btn in buttons:
            btn_lower = btn['text'].lower()
            for kw in priority_keywords:
                if kw in btn_lower:
                    return btn
        
        # Then try any callback button
        for btn in buttons:
            if btn['type'] == 'callback':
                return btn
        
        return None
    
    def _is_math_captcha(self, text):
        """Detect math captcha like '3 + 5 = ?'"""
        patterns = [
            r'\d+\s*\+\s*\d+', r'\d+\s*[-\u2212]\s*\d+',
            r'\d+\s*\*\s*\d+', r'\d+\s*x\s*\d+', r'\d+\s*/\s*\d+',
            r'solve', r'calculate', r'what is', r'how much is',
            r'answer.*\d+', r'\d+.*[+\-*/x].*\d+'
        ]
        text_lower = text.lower()
        return any(re.search(p, text_lower) for p in patterns)
    
    def _solve_math(self, text):
        """Solve math expressions like '3 + 5' or '10 - 4'"""
        patterns = [
            (r'(\d+)\s*\+\s*(\d+)', lambda a, b: int(a) + int(b)),
            (r'(\d+)\s*[-\u2212]\s*(\d+)', lambda a, b: int(a) - int(b)),
            (r'(\d+)\s*\*\s*(\d+)', lambda a, b: int(a) * int(b)),
            (r'(\d+)\s*x\s*(\d+)', lambda a, b: int(a) * int(b)),
            (r'(\d+)\s*/\s*(\d+)', lambda a, b: int(a) // int(b) if int(b) != 0 else None),
        ]
        
        for pattern, operation in patterns:
            match = re.search(pattern, text)
            if match:
                return operation(match.group(1), match.group(2))
        
        return None
    
    def _solve_text_captcha(self, text):
        """Extract text/code to type from captcha"""
        patterns = [
            r'type\s*:?\s*["\']([a-zA-Z0-9]+)["\']',
            r'enter\s*["\']([a-zA-Z0-9]+)["\']',
            r'code\s*:?\s*["\']?([A-Z0-9]{4,})["\']?',
            r'send\s*["\']?(\w+)["\']?',
            r'type\s+(\w+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    def _extract_number(self, text):
        """Extract a specific number the bot wants you to send"""
        patterns = [
            r'click\s*(?:the\s*)?number\s*["\']?(\d+)["\']?',
            r'press\s*["\']?(\d+)["\']?',
            r'send\s*["\']?(\d+)["\']?',
            r'type\s*["\']?(\d+)["\']?',
            r'enter\s*["\']?(\d+)["\']?',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    def _find_continue_button(self, buttons):
        """Find 'Continue
