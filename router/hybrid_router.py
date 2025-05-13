import os
import time
import asyncio
import logging
import traceback
import json
from enum import Enum, auto

from api.websocket_client import ReplitWebSocketClient
from api.direct_api_client import ReplitDirectAPIClient
from browser.browser_client import ReplitBrowserClient
try:
    from browser.browser_client_playwright import ReplitBrowserClient as PlaywrightBrowserClient
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
from auth.token_manager import TokenManager

logger = logging.getLogger(__name__)

class RouterMethod(Enum):
    """Methods that the router can use"""
    DIRECT_API = auto()
    WEBSOCKET_API = auto()
    BROWSER_AUTOMATION = auto()
    AUTO = auto()  # Automatically select the best method

class HybridRouter:
    """Router that decides between direct API, WebSocket API and browser automation"""
    
    def __init__(self, user_id, token_manager, cookies_file=None, method=RouterMethod.AUTO):
        """Initialize the hybrid router
        
        Args:
            user_id (str): User ID for this router instance
            token_manager (TokenManager): Token manager for storing and retrieving authentication data
            cookies_file (str, optional): Path to the cookies file
            method (RouterMethod): Which method to use
        """
        self.user_id = user_id
        self.token_manager = token_manager
        self.cookies_file = cookies_file or os.environ.get('COOKIES_FILE', './storage/cookies.json')
        self.method = method
        self.ws_client = None
        self.direct_client = None
        self.browser_client = None
        self.last_method_used = None
        self.use_playwright = os.environ.get('USE_PLAYWRIGHT', 'false').lower() == 'true' and HAS_PLAYWRIGHT
        
        # Failure counts and thresholds
        self.direct_api_failures = 0
        self.max_direct_api_failures = 3
        self.websocket_failures = 0
        self.max_websocket_failures = 3
        self.browser_failures = 0
        self.max_browser_failures = 3
        
        # Statistics
        self.successful_api_calls = 0
        self.total_api_calls = 0
        
        # Load any existing authentication data
        self.auth_data = self.token_manager.get_user_tokens(user_id)
    
    async def _init_direct_api(self):
        """Initialize the direct API client"""
        try:
            if self.direct_client:
                # The client is already initialized
                return True
            
            logger.info(f"Initializing direct API client for user {self.user_id}")
            self.direct_client = ReplitDirectAPIClient(self.auth_data)
            connected = await self.direct_client.connect()
            
            if connected:
                logger.info("Direct API client initialized successfully")
                return True
            else:
                logger.warning("Failed to initialize direct API client")
                self.direct_api_failures += 1
                self.direct_client = None
                return False
                
        except Exception as e:
            logger.error(f"Error initializing direct API client: {e}")
            logger.error(traceback.format_exc())
            self.direct_api_failures += 1
            self.direct_client = None
            return False
            
    async def _init_websocket_api(self):
        """Initialize the WebSocket API client"""
        try:
            if self.ws_client:
                if self.ws_client.is_connected():
                    return True
                else:
                    await self.ws_client.close()  # Close existing connection if it's not connected
            
            logger.info(f"Initializing WebSocket API client for user {self.user_id}")
            self.ws_client = ReplitWebSocketClient(self.auth_data)
            connected = await self.ws_client.connect()
            
            if connected:
                logger.info("WebSocket API client initialized successfully")
                return True
            else:
                logger.warning("Failed to initialize WebSocket API client")
                self.websocket_failures += 1
                self.ws_client = None
                return False
                
        except Exception as e:
            logger.error(f"Error initializing WebSocket API client: {e}")
            logger.error(traceback.format_exc())
            self.websocket_failures += 1
            self.ws_client = None
            return False
    
    async def _init_browser(self):
        """Initialize the browser client"""
        try:
            if self.browser_client and hasattr(self.browser_client, 'initialized') and self.browser_client.initialized:
                return True
            
            logger.info(f"Initializing browser client for user {self.user_id}")
            
            # Use Playwright if available and configured
            if self.use_playwright and HAS_PLAYWRIGHT:
                logger.info("Using Playwright browser client")
                self.browser_client = PlaywrightBrowserClient(cookies_file=self.cookies_file)
            else:
                logger.info("Using Selenium browser client")
                self.browser_client = ReplitBrowserClient(cookies_file=self.cookies_file)
                
            initialized = await self.browser_client.start()
            
            if initialized:
                logger.info("Browser client initialized successfully")
                
                # Extract auth data from the browser and store it
                auth_data = await self.browser_client.extract_auth_data()
                if auth_data:
                    self.auth_data = auth_data
                    self.token_manager.store_user_tokens(self.user_id, auth_data)
                    logger.info(f"Stored authentication data for user {self.user_id}")
                
                return True
            else:
                logger.warning("Failed to initialize browser client")
                self.browser_failures += 1
                return False
                
        except Exception as e:
            logger.error(f"Error initializing browser client: {e}")
            logger.error(traceback.format_exc())
            self.browser_failures += 1
            return False
    
    def _determine_method(self):
        """Determine which method to use based on current state"""
        if self.method != RouterMethod.AUTO:
            return self.method
            
        # If we have recent successful direct API calls, prefer that
        if self.direct_client and self.successful_api_calls > 0 and self.direct_api_failures < self.max_direct_api_failures:
            logger.info("Using direct API client due to recent success")
            return RouterMethod.DIRECT_API
            
        # If we have recent successful WebSocket API calls, prefer that
        if self.ws_client and self.successful_api_calls > 0 and self.websocket_failures < self.max_websocket_failures:
            logger.info("Using WebSocket API client due to recent success")
            return RouterMethod.WEBSOCKET_API
        
        # Try methods in order of preference with failure checks
        
        # If direct API hasn't failed too much, try it first
        if self.direct_api_failures < self.max_direct_api_failures:
            logger.info("Trying direct API client")
            return RouterMethod.DIRECT_API
            
        # If WebSocket API hasn't failed too much, try it next
        if self.websocket_failures < self.max_websocket_failures:
            logger.info("Trying WebSocket API client")
            return RouterMethod.WEBSOCKET_API
            
        # If browser automation hasn't failed too much, use that
        if self.browser_failures < self.max_browser_failures:
            logger.info("Using browser automation as fallback")
            return RouterMethod.BROWSER_AUTOMATION
            
        # If all are failing, reset failure counts and try direct API again
        logger.info("All methods have exceeded failure thresholds. Resetting counters.")
        self.direct_api_failures = 0
        self.websocket_failures = 0
        self.browser_failures = 0
        return RouterMethod.DIRECT_API
    
    async def send_message(self, text, on_update=None):
        """Send a message using the appropriate method
        
        Args:
            text (str): Message to send
            on_update (callable, optional): Callback for streaming updates
            
        Returns:
            str: Response from Replit Agent
        """
        method = self._determine_method()
        self.last_method_used = method
        self.total_api_calls += 1
        
        try:
            # Define a standard update callback
            async def update_callback(content):
                if on_update:
                    await on_update(content)
            
            # Method 1: Try Direct API
            if method == RouterMethod.DIRECT_API:
                logger.info(f"Using direct API to send message for user {self.user_id}")
                initialized = await self._init_direct_api()
                
                if initialized:
                    try:
                        message_id = await self.direct_client.send_message(
                            text, 
                            on_update=update_callback if on_update else None,
                            on_complete=None
                        )
                        
                        if message_id:
                            response = await self.direct_client.wait_for_response(message_id)
                            if response:
                                self.direct_api_failures = 0  # Reset failures counter
                                self.successful_api_calls += 1
                                return response
                    except Exception as e:
                        logger.warning(f"Direct API client failed: {e}")
                        self.direct_api_failures += 1
                
                # If we get here, something went wrong with the Direct API
                logger.warning("Direct API failed to get response, trying WebSocket API")
                method = RouterMethod.WEBSOCKET_API
                self.last_method_used = method
            
            # Method 2: Try WebSocket API
            if method == RouterMethod.WEBSOCKET_API:
                logger.info(f"Using WebSocket API to send message for user {self.user_id}")
                initialized = await self._init_websocket_api()
                
                if initialized:
                    try:
                        message_id = await self.ws_client.send_message(
                            text, 
                            on_update=update_callback if on_update else None
                        )
                        
                        if message_id:
                            response = await self.ws_client.wait_for_response(message_id)
                            if response:
                                self.websocket_failures = 0  # Reset failures counter
                                self.successful_api_calls += 1
                                return response
                    except Exception as e:
                        logger.warning(f"WebSocket API client failed: {e}")
                        self.websocket_failures += 1
                
                # If we get here, something went wrong with the WebSocket API
                logger.warning("WebSocket API failed to get response, falling back to browser")
                method = RouterMethod.BROWSER_AUTOMATION
                self.last_method_used = method
            
            # Method 3: Try Browser Automation (last resort)
            if method == RouterMethod.BROWSER_AUTOMATION:
                logger.info(f"Using browser automation to send message for user {self.user_id}")
                initialized = await self._init_browser()
                
                if not initialized:
                    raise Exception("Failed to initialize browser client")
                
                # Use the browser client
                response = await self.browser_client.send_message(text)
                
                if response and "Error:" not in response:
                    self.browser_failures = 0  # Reset failures counter
                    
                    # Try to extract auth data for future API use
                    auth_data = await self.browser_client.extract_auth_data()
                    if auth_data:
                        self.auth_data = auth_data
                        self.token_manager.store_user_tokens(self.user_id, auth_data)
                        logger.info(f"Updated authentication data for user {self.user_id}")
                    
                    return response
                else:
                    self.browser_failures += 1
                    raise Exception(f"Browser automation failed: {response}")
            
            # If we got here, all methods failed
            return "Failed to get a response from Replit Agent through any method."
            
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            logger.error(traceback.format_exc())
            return f"Error: {str(e)}"
    
    def get_stats(self):
        """Get statistics about the router usage
        
        Returns:
            dict: Statistics about the router usage
        """
        success_rate = 0
        if self.total_api_calls > 0:
            success_rate = (self.successful_api_calls / self.total_api_calls) * 100
        
        return {
            "total_calls": self.total_api_calls,
            "successful_calls": self.successful_api_calls,
            "success_rate": int(success_rate),
            "direct_api_failures": self.direct_api_failures,
            "websocket_failures": self.websocket_failures,
            "browser_failures": self.browser_failures,
            "last_method": str(self.last_method_used).split('.')[-1] if self.last_method_used else None,
            "has_auth_data": bool(self.auth_data),
            "direct_client_active": bool(self.direct_client),
            "websocket_client_active": bool(self.ws_client),
            "browser_client_active": bool(self.browser_client)
        }
    
    async def close(self):
        """Close all clients"""
        tasks = []
        
        # Close Direct API client
        if self.direct_client:
            try:
                tasks.append(self.direct_client.close())
            except Exception as e:
                logger.error(f"Error closing direct API client: {e}")
        
        # Close WebSocket client
        if self.ws_client:
            try:
                tasks.append(self.ws_client.close())
            except Exception as e:
                logger.error(f"Error closing WebSocket client: {e}")
        
        # Close Browser client (may be sync or async depending on implementation)
        if self.browser_client:
            try:
                if hasattr(self.browser_client, 'close') and callable(self.browser_client.close):
                    close_method = self.browser_client.close()
                    if asyncio.iscoroutine(close_method):
                        tasks.append(close_method)
            except Exception as e:
                logger.error(f"Error closing browser client: {e}")
        
        # Wait for all async close tasks to complete
        if tasks:
            try:
                await asyncio.gather(*tasks)
                logger.info("All clients closed successfully")
            except Exception as e:
                logger.error(f"Error during client shutdown: {e}")
        
        # Reset client references
        self.direct_client = None
        self.ws_client = None
        self.browser_client = None