import os
import json
import time
import base64
import logging
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

class TokenManager:
    """Securely manages authentication tokens and credentials"""
    
    def __init__(self, storage_dir="./storage", encryption_key=None):
        """Initialize the token manager
        
        Args:
            storage_dir (str): Directory to store token data
            encryption_key (str): Key for encrypting token data. If None, generates one.
        """
        self.storage_dir = storage_dir
        self.tokens_file = os.path.join(storage_dir, "tokens.enc")
        
        # Ensure storage directory exists
        os.makedirs(storage_dir, exist_ok=True)
        
        # Setup encryption
        if encryption_key is None:
            # Generate a key from environment or create a new one
            encryption_key = os.getenv("ENCRYPTION_KEY", "")
            if not encryption_key:
                encryption_key = base64.urlsafe_b64encode(os.urandom(32)).decode()
                logger.warning(f"Generated new encryption key. Please store this securely: {encryption_key}")
        
        self.setup_encryption(encryption_key)
        
        # Initialize tokens storage
        self.tokens = {}
        self.load_tokens()
    
    def setup_encryption(self, key):
        """Set up encryption with the provided key"""
        try:
            # Convert string key to bytes if needed
            if isinstance(key, str):
                # If key is a password rather than a Fernet key, derive a key
                if not key.endswith('='):  # Heuristic to detect if it's not a base64 key
                    password = key.encode()
                    salt = b'replit_agent_bot_salt'  # Not ideal, but ok for this use case
                    kdf = PBKDF2HMAC(
                        algorithm=hashes.SHA256(),
                        length=32,
                        salt=salt,
                        iterations=100000,
                    )
                    key = base64.urlsafe_b64encode(kdf.derive(password))
                else:
                    key = key.encode()
            
            self.cipher = Fernet(key)
            logger.info("Encryption setup successful")
        except Exception as e:
            logger.error(f"Failed to setup encryption: {str(e)}")
            raise
    
    def load_tokens(self):
        """Load tokens from storage file"""
        if not os.path.exists(self.tokens_file):
            logger.info(f"No tokens file found at {self.tokens_file}")
            return
        
        try:
            with open(self.tokens_file, 'rb') as f:
                encrypted_data = f.read()
            
            decrypted_data = self.cipher.decrypt(encrypted_data)
            self.tokens = json.loads(decrypted_data.decode())
            logger.info(f"Loaded tokens for {len(self.tokens)} users")
        except Exception as e:
            logger.error(f"Failed to load tokens: {str(e)}")
            self.tokens = {}
    
    def save_tokens(self):
        """Save tokens to storage file"""
        try:
            json_data = json.dumps(self.tokens)
            encrypted_data = self.cipher.encrypt(json_data.encode())
            
            with open(self.tokens_file, 'wb') as f:
                f.write(encrypted_data)
            
            logger.info(f"Saved tokens for {len(self.tokens)} users")
            return True
        except Exception as e:
            logger.error(f"Failed to save tokens: {str(e)}")
            return False
    
    def store_user_tokens(self, user_id, auth_data):
        """Store tokens for a specific user
        
        Args:
            user_id (str): Telegram user ID
            auth_data (dict): Authentication data to store
        """
        try:
            # Store with timestamp
            self.tokens[user_id] = {
                'data': auth_data,
                'stored_at': int(time.time())
            }
            return self.save_tokens()
        except Exception as e:
            logger.error(f"Failed to store tokens for user {user_id}: {str(e)}")
            return False
    
    def get_user_tokens(self, user_id):
        """Get tokens for a specific user
        
        Args:
            user_id (str): Telegram user ID
            
        Returns:
            dict: Authentication data or None if not found
        """
        user_data = self.tokens.get(user_id)
        if not user_data:
            logger.warning(f"No tokens found for user {user_id}")
            return None
        
        return user_data.get('data')
    
    def is_token_valid(self, user_id, max_age=43200):  # Default: 12 hours
        """Check if user tokens are still valid
        
        Args:
            user_id (str): Telegram user ID
            max_age (int): Maximum age in seconds for tokens to be considered valid
            
        Returns:
            bool: True if tokens exist and are valid, False otherwise
        """
        user_data = self.tokens.get(user_id)
        if not user_data:
            return False
        
        stored_at = user_data.get('stored_at', 0)
        current_time = int(time.time())
        
        return (current_time - stored_at) < max_age
    
    def delete_user_tokens(self, user_id):
        """Delete tokens for a specific user
        
        Args:
            user_id (str): Telegram user ID
            
        Returns:
            bool: True if deleted, False otherwise
        """
        if user_id in self.tokens:
            del self.tokens[user_id]
            return self.save_tokens()
        
        return False