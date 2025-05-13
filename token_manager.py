import os
import json
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import logger

# Initialize logger
log = logger.setup_logger()

class TokenManager:
    """A class to securely store and retrieve authentication tokens"""
    
    def __init__(self):
        """Initialize the token manager"""
        self.token_file = "tokens.enc"
        self.key = self._get_encryption_key()
        self.cipher = Fernet(self.key)
    
    def _get_encryption_key(self):
        """Get or generate the encryption key"""
        try:
            # Get key from environment variable or generate a new one
            key_env = os.environ.get("ENCRYPTION_KEY")
            
            if key_env:
                # Use the key from environment variable
                if len(base64.urlsafe_b64decode(key_env)) != 32:
                    # If the key is not the right size, derive a key from it
                    salt = b'replit_agent_bot'  # Static salt
                    kdf = PBKDF2HMAC(
                        algorithm=hashes.SHA256(),
                        length=32,
                        salt=salt,
                        iterations=100000,
                    )
                    key = base64.urlsafe_b64encode(kdf.derive(key_env.encode()))
                    return key
                return key_env.encode()
            else:
                # Generate a new key
                key = Fernet.generate_key()
                log.warning("ENCRYPTION_KEY not set in environment. Generated a new key.")
                log.warning("Note: Tokens will be lost if the application restarts without this key.")
                return key
        except Exception as e:
            log.error(f"Error getting encryption key: {e}")
            # Fallback to a derived key
            return base64.urlsafe_b64encode(
                PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=b'replit_agent_bot_fallback',
                    iterations=100000,
                ).derive(b'fallback_encryption_key')
            )
    
    def save_token(self, token):
        """Save a token to the encrypted file"""
        try:
            # Load existing tokens
            tokens = self.load_tokens()
            
            # Add or update the token
            tokens["api_token"] = token
            
            # Encrypt and save
            encrypted_data = self.cipher.encrypt(json.dumps(tokens).encode())
            
            with open(self.token_file, 'wb') as f:
                f.write(encrypted_data)
            
            log.info("Token saved successfully")
            return True
        except Exception as e:
            log.error(f"Error saving token: {e}")
            return False
    
    def load_tokens(self):
        """Load tokens from the encrypted file"""
        try:
            if not os.path.exists(self.token_file):
                return {}
            
            with open(self.token_file, 'rb') as f:
                encrypted_data = f.read()
            
            decrypted_data = self.cipher.decrypt(encrypted_data)
            tokens = json.loads(decrypted_data.decode())
            
            return tokens
        except Exception as e:
            log.error(f"Error loading tokens: {e}")
            return {}
    
    def get_token(self):
        """Get the saved API token"""
        tokens = self.load_tokens()
        return tokens.get("api_token")
    
    def delete_token(self):
        """Delete the saved token"""
        try:
            if os.path.exists(self.token_file):
                os.remove(self.token_file)
                log.info("Token file deleted")
            return True
        except Exception as e:
            log.error(f"Error deleting token: {e}")
            return False
