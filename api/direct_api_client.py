import os
import json
import time
import asyncio
import logging
import traceback
import websockets
import uuid
import requests
from urllib.parse import urlparse
import utils

logger = logging.getLogger(__name__)

class ReplitDirectAPIClient:
    """Client for directly communicating with Replit Agent API via WebSockets"""
    
    def __init__(self, auth_data=None):
        """Initialize the direct API client
        
        Args:
            auth_data (dict, optional): Authentication data including tokens
        """
        self.auth_data = auth_data
        self.ws = None
        self.url = None
        self.headers = {}
        self.initialized = False
        self.message_callbacks = {}
        self.connection_established = asyncio.Event()
        self.cookies_file = os.environ.get('COOKIES_FILE', './storage/cookies.json')
        
    async def _load_auth_from_cookies_file(self):
        """Load authentication data from cookies file"""
        try:
            if not os.path.exists(self.cookies_file):
                logger.warning(f"Cookies file not found: {self.cookies_file}")
                return False
                
            with open(self.cookies_file, 'r') as f:
                cookies = json.load(f)
                
            # Extract required cookies
            auth_data = {
                'cookies': {},
                'timestamp': int(time.time())
            }
            
            for cookie in cookies:
                if cookie.get('domain', '').endswith('.replit.com') or cookie.get('domain') == 'replit.com':
                    name = cookie.get('name')
                    value = cookie.get('value')
                    if name and value:
                        auth_data['cookies'][name] = value
            
            # Extract important cookies
            important_cookies = ['connect.sid', 'ajs_user_id', '__stripe_mid', 'amplitude_id_']
            found_important = [cookie for cookie in important_cookies if cookie in auth_data['cookies']]
            
            if found_important:
                logger.info(f"Found {len(found_important)}/{len(important_cookies)} important cookies")
                self.auth_data = auth_data
                return True
            else:
                logger.warning("No important cookies found in the cookies file")
                return False
                
        except Exception as e:
            logger.error(f"Error loading auth from cookies file: {str(e)}")
            logger.error(traceback.format_exc())
            return False
            
    def _prepare_headers(self):
        """Prepare headers for WebSocket connection"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Origin': 'https://replit.com',
            'Pragma': 'no-cache',
            'Cache-Control': 'no-cache',
        }
        
        # Add cookie header if we have cookies
        if self.auth_data and 'cookies' in self.auth_data:
            cookie_str = "; ".join([f"{name}={value}" for name, value in self.auth_data['cookies'].items()])
            headers['Cookie'] = cookie_str
            
        self.headers = headers
        return headers
        
    def _generate_parameters(self):
        """Generate WebSocket connection parameters"""
        params = {
            'user_agent': 'replit',
            'client_id': f"lakojic990-L{uuid.uuid4().hex[:8]}",
            'session_id': f"session-{uuid.uuid4().hex[:12]}",
            'token_cluster': 'picard',
            'timestamp': int(time.time()),
        }
        return params
    
    async def connect(self):
        """Connect to the Replit Agent WebSocket API"""
        if not self.auth_data:
            logger.info("No auth data provided, attempting to load from cookies file")
            auth_loaded = await self._load_auth_from_cookies_file()
            if not auth_loaded:
                raise Exception("Failed to load authentication data")
        
        # Prepare connection
        headers = self._prepare_headers()
        params = self._generate_parameters()
        
        # Store parameters for future use
        self.params = params
        
        # Construct WebSocket URL
        self.url = f"wss://replit.com/river/wsv2?"
        self.url += f"user_agent={params['user_agent']}"
        self.url += f"&client_id={params['client_id']}"
        self.url += f"&session_id={params['session_id']}"
        self.url += f"&token_cluster={params['token_cluster']}"
        self.url += f"&timestamp={params['timestamp']}"
        
        logger.info(f"Connecting to WebSocket at {self.url}")
        
        try:
            # Connect to WebSocket
            self.ws = await websockets.connect(
                self.url,
                extra_headers=headers,
                max_size=None,
                ping_interval=30,
                ping_timeout=10,
                close_timeout=10
            )
            
            # Start message processing task
            self.message_task = asyncio.create_task(self._process_messages())
            
            # Wait for the connection to be fully established
            try:
                await asyncio.wait_for(self.connection_established.wait(), timeout=15)
                logger.info("Connection established successfully")
                self.initialized = True
                return True
            except asyncio.TimeoutError:
                logger.error("Timed out waiting for connection to be established")
                await self.close()
                return False
                
        except Exception as e:
            logger.error(f"Error connecting to WebSocket: {str(e)}")
            logger.error(traceback.format_exc())
            await self.close()
            return False
    
    async def _process_messages(self):
        """Process incoming WebSocket messages"""
        if not self.ws:
            logger.error("WebSocket not connected")
            return
            
        try:
            async for message in self.ws:
                try:
                    # Parse the message
                    data = json.loads(message)
                    
                    # Log the message
                    logger.debug(f"Received WebSocket message: {message[:100]}...")
                    
                    # Check message type
                    if 'type' in data:
                        # Handle connection established
                        if data['type'] == 'connection:established':
                            logger.info("WebSocket connection established")
                            self.connection_established.set()
                        
                        # Handle agent messages
                        elif data['type'] == 'agent:response' or data['type'] == 'agent:stream':
                            message_id = data.get('messageId')
                            if message_id and message_id in self.message_callbacks:
                                callbacks = self.message_callbacks[message_id]
                                
                                # Check if it's a streaming update or final response
                                if data['type'] == 'agent:stream' and callbacks.get('on_update'):
                                    await callbacks['on_update'](data.get('content', ''))
                                    
                                elif data['type'] == 'agent:response' and callbacks.get('on_complete'):
                                    await callbacks['on_complete'](data.get('content', ''))
                                    # Remove the callback after completion
                                    del self.message_callbacks[message_id]
                    
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON in WebSocket message: {message[:100]}...")
                except Exception as e:
                    logger.error(f"Error processing WebSocket message: {str(e)}")
                    logger.error(traceback.format_exc())
        
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
        except Exception as e:
            logger.error(f"Error in message processing: {str(e)}")
            logger.error(traceback.format_exc())
        finally:
            self.initialized = False
            self.connection_established.clear()
    
    async def send_message(self, text, on_update=None, on_complete=None):
        """Send a message to Replit Agent
        
        Args:
            text (str): Message to send
            on_update (callable, optional): Callback for content updates
            on_complete (callable, optional): Callback when response is complete
            
        Returns:
            str: Message ID for tracking the response
        """
        if not self.initialized or not self.ws:
            connected = await self.connect()
            if not connected:
                raise Exception("Failed to connect to WebSocket")
        
        # Generate a unique message ID
        message_id = utils.generate_uuid()
        
        # Create message payload
        payload = {
            "type": "agent:query",
            "messageId": message_id,
            "query": text,
            "clientId": self.params['client_id'],
            "sessionId": self.params['session_id'],
            "tokenCluster": self.params['token_cluster']
        }
        
        # Store callbacks for this message
        self.message_callbacks[message_id] = {
            'on_update': on_update,
            'on_complete': on_complete,
            'timestamp': time.time()
        }
        
        # Send the message
        try:
            logger.info(f"Sending message: {text[:50]}...")
            await self.ws.send(json.dumps(payload))
            return message_id
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            if message_id in self.message_callbacks:
                del self.message_callbacks[message_id]
            raise
    
    async def wait_for_response(self, message_id, timeout=60):
        """Wait for a complete response to a message
        
        Args:
            message_id (str): ID of the message to wait for
            timeout (int): Maximum time to wait in seconds
            
        Returns:
            str: Complete response or None if timed out
        """
        if message_id not in self.message_callbacks:
            logger.error(f"No callbacks found for message ID: {message_id}")
            return None
            
        # Create a future to wait for the response
        response_future = asyncio.Future()
        
        # Update the callbacks to set the future result
        original_callback = self.message_callbacks[message_id].get('on_complete')
        
        async def on_complete_wrapper(content):
            if original_callback:
                await original_callback(content)
            response_future.set_result(content)
            
        self.message_callbacks[message_id]['on_complete'] = on_complete_wrapper
        
        try:
            # Wait for the response with timeout
            return await asyncio.wait_for(response_future, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"Timed out waiting for response to message ID: {message_id}")
            return None
        finally:
            # Clean up
            if message_id in self.message_callbacks:
                del self.message_callbacks[message_id]
    
    async def close(self):
        """Close the WebSocket connection"""
        logger.info("Closing WebSocket connection")
        
        # Cancel the message processing task
        if hasattr(self, 'message_task') and self.message_task:
            self.message_task.cancel()
            try:
                await self.message_task
            except asyncio.CancelledError:
                pass
            
        # Close the WebSocket connection
        if self.ws:
            try:
                await self.ws.close()
            except:
                pass
            self.ws = None
            
        self.initialized = False
        self.connection_established.clear()
        logger.info("WebSocket connection closed")