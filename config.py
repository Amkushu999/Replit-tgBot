import os
import json
import logger

# Initialize logger
log = logger.setup_logger()

class Config:
    """Configuration manager for the application"""
    
    def __init__(self):
        """Initialize the config manager"""
        self.config_file = "config.json"
        self.config = self._load_config()
    
    def _load_config(self):
        """Load configuration from file or create default"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                log.info("Loaded configuration from file")
                return config
            else:
                # Create default configuration
                default_config = {
                    "features": {
                        "use_direct_api": True,
                        "browser_fallback": True,
                        "extract_tokens": True,
                        "streaming_responses": True
                    },
                    "timeouts": {
                        "api_connection": 30,
                        "api_response": 60,
                        "browser_startup": 60,
                        "browser_response": 120
                    },
                    "retry": {
                        "max_retries": 3,
                        "retry_delay": 2
                    }
                }
                
                # Save default configuration
                with open(self.config_file, 'w') as f:
                    json.dump(default_config, f, indent=2)
                
                log.info("Created default configuration file")
                return default_config
        except Exception as e:
            log.error(f"Error loading configuration: {e}")
            # Return a minimal default configuration
            return {
                "features": {
                    "use_direct_api": True,
                    "browser_fallback": True
                },
                "timeouts": {
                    "api_connection": 30,
                    "api_response": 60
                },
                "retry": {
                    "max_retries": 3
                }
            }
    
    def get(self, key, default=None):
        """Get a configuration value by key path"""
        try:
            # Split the key path
            parts = key.split('.')
            value = self.config
            
            # Navigate through the config dictionary
            for part in parts:
                value = value.get(part)
                if value is None:
                    return default
            
            return value
        except Exception:
            return default
    
    def set(self, key, value):
        """Set a configuration value by key path"""
        try:
            # Split the key path
            parts = key.split('.')
            
            # Navigate to the correct location
            config = self.config
            for i, part in enumerate(parts[:-1]):
                if part not in config:
                    config[part] = {}
                config = config[part]
            
            # Set the value
            config[parts[-1]] = value
            
            # Save the updated configuration
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            
            log.info(f"Updated configuration: {key} = {value}")
            return True
        except Exception as e:
            log.error(f"Error updating configuration: {e}")
            return False
    
    def is_feature_enabled(self, feature_name):
        """Check if a feature is enabled"""
        return self.get(f"features.{feature_name}", False)
