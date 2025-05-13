import os
import uuid
import time
import random
import string
import logging
import urllib.parse

logger = logging.getLogger(__name__)

def generate_nonce(length=16):
    """Generate a random string of specified length"""
    letters = string.ascii_lowercase + string.digits
    return ''.join(random.choice(letters) for _ in range(length))

def generate_uuid():
    """Generate a random UUID"""
    return str(uuid.uuid4())

def current_timestamp():
    """Get current timestamp in milliseconds"""
    return int(time.time() * 1000)

def parse_websocket_url(url):
    """Parse components from a WebSocket URL"""
    parsed = urllib.parse.urlparse(url)
    path = parsed.path
    query = urllib.parse.parse_qs(parsed.query)
    
    # Extract parameters
    result = {
        'host': parsed.netloc,
        'path': path,
    }
    
    # Add query parameters
    for key, values in query.items():
        if values:
            result[key] = values[0]
    
    return result

def format_response_for_telegram(text):
    """Format text for Telegram, ensuring it's within limits"""
    if not text:
        return ""
    
    # Telegram has a 4096 character limit per message
    # We'll keep it to 4000 to be safe
    MAX_LENGTH = 4000
    
    if len(text) <= MAX_LENGTH:
        return text
    
    # If longer than the limit, truncate and add indicator
    return text[:MAX_LENGTH - 3] + "..."

def ensure_directory_exists(path):
    """Ensure that a directory exists, creating it if necessary"""
    if not os.path.exists(path):
        try:
            os.makedirs(path)
            return True
        except Exception as e:
            logger.error(f"Error creating directory {path}: {e}")
            return False
    return True