import os
import logging
import sys
from logging.handlers import RotatingFileHandler

def setup_logger():
    """Set up and configure the logger"""
    # Create logs directory if it doesn't exist
    log_directory = './logs'
    os.makedirs(log_directory, exist_ok=True)
    
    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Create a formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Configure console handler for terminal output
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Configure file handler for saving logs to a file
    log_file = os.path.join(log_directory, 'replit_agent_bot.log')
    file_handler = RotatingFileHandler(log_file, maxBytes=10485760, backupCount=5)  # 10 MB per file, 5 files max
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Set third-party logger levels to reduce noise
    logging.getLogger('websockets').setLevel(logging.WARNING)
    logging.getLogger('telegram').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('selenium').setLevel(logging.WARNING)
    
    # Return the configured logger
    return logger

# Create and configure the logger when this module is imported
logger = setup_logger()