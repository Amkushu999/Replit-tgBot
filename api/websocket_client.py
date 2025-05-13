import json
import time
import asyncio
import logging
import websockets
import traceback
from datetime import datetime
from enum import Enum, auto

logger = logging.getLogger(__name__)

class ConnectionState(Enum):
    """States for the WebSocket connection state machine"""
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    HANDSHAKING = auto()
    NO_CONNECTION = auto()
    BACKING_OFF = auto()
    ERROR = auto()
    CLOSED = auto()

class ReplitWebSocketClient:
    """Client for direct communication with Replit agent via WebSocket"""
    
    def __init__(self, auth_data=None):
        """Initialize WebSocket client
        
        Args:
            auth_data (dict): Authentication data including tokens and connection parameters
        """
        self.auth_data = auth_data or {}
        self.ws = None
        self.state = ConnectionState.DISCONNECTED
        self.ws_url = "wss://replit.com/river/wsv2"
        self.responses = {}
        self.handlers = {}
        self.message_queue = asyncio.Queue()
        self.client_id = self.auth_data.get('client_id', '')
        self.session_id = self.auth_data.get('session_id', '')
        self.token_cluster = "picard"  # Default value from captured traffic
        self.task = None
        self.backoff_time = 1  # Initial backoff time in seconds
        self.max_backoff_time = 30  # Maximum backoff time in seconds
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5

    def _extract_connection_params(self):
        """Extract WebSocket connection parameters from auth data"""
        # Extract client ID
        if 'websocket_params' in self.auth_data and 'clientId' in self.auth_data['websocket_params']:
            self.client_id = self.auth_data['websocket_params']['clientId']
        
        # Extract session ID
        if 'websocket_params' in self.auth_data and 'sessionId' in self.auth_data['websocket_params']:
            self.session_id = self.auth_data['websocket_params']['sessionId']
        
        # Extract token cluster
        if 'websocket_params' in self.auth_data and 'tokenCluster' in self.auth_data['websocket_params']:
            self.token_cluster = self.auth_data['websocket_params']['tokenCluster']
        
        # Look in network data
        if 'network_data' in self.auth_data and 'websocket_connections' in self.auth_data['network_data']:
            for conn in self.auth_data['network_data']['websocket_connections']:
                if 'data' in conn and isinstance(conn['data'], str) and conn['data'].startswith('{'):
                    try:
                        data = json.loads(conn['data'])
                        if 'clientId' in data:
                            self.client_id = data['clientId']
                        if 'sessionId' in data:
                            self.session_id = data['sessionId']
                        if 'tokenCluster' in data:
                            self.token_cluster = data['tokenCluster']
                    except:
                        pass
        
        logger.info(f"Extracted connection params: clientId={self.client_id}, sessionId={self.session_id}, tokenCluster={self.token_cluster}")
        return bool(self.client_id and self.session_id)

    def _get_headers(self):
        """Construct headers for the WebSocket connection"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-A035F Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.7103.60 Mobile Safari/537.36",
            "Origin": "https://replit.com",
            "Referer": "https://replit.com/"
        }
        
        # Add cookies as headers if available
        if 'cookies' in self.auth_data:
            cookie_strings = []
            for name, value in self.auth_data['cookies'].items():
                cookie_strings.append(f"{name}={value}")
            
            if cookie_strings:
                headers["Cookie"] = "; ".join(cookie_strings)
        
        return headers

    async def connect(self):
        """Establish WebSocket connection to Replit agent"""
        if self.state == ConnectionState.CONNECTING or self.state == ConnectionState.CONNECTED:
            logger.info("Connection already in progress or established")
            return True
        
        self.state = ConnectionState.CONNECTING
        logger.info("Connecting to Replit WebSocket...")
        
        # Extract connection parameters if needed
        if not self.client_id or not self.session_id:
            if not self._extract_connection_params():
                logger.error("Failed to extract connection parameters from auth data")
                self.state = ConnectionState.ERROR
                return False
        
        try:
            # Connect to WebSocket
            headers = self._get_headers()
            self.ws = await websockets.connect(self.ws_url, extra_headers=headers)
            
            # Send handshake message
            self.state = ConnectionState.HANDSHAKING
            logger.info("Sending handshake message...")
            
            handshake_message = {
                "clientId": self.client_id,
                "sessionId": self.session_id,
                "tokenCluster": self.token_cluster
            }
            
            await self.ws.send(json.dumps(handshake_message))
            
            # Start listening for messages
            self.state = ConnectionState.CONNECTED
            self.reconnect_attempts = 0
            logger.info("WebSocket connection established successfully")
            
            # Start message processing task
            if self.task is None or self.task.done():
                self.task = asyncio.create_task(self._process_messages())
            
            return True
        
        except Exception as e:
            self.state = ConnectionState.NO_CONNECTION
            logger.error(f"Failed to connect to WebSocket: {str(e)}")
            traceback.print_exc()
            return False

    async def reconnect(self):
        """Attempt to reconnect with exponential backoff"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(f"Max reconnection attempts ({self.max_reconnect_attempts}) reached")
            self.state = ConnectionState.ERROR
            return False
        
        self.reconnect_attempts += 1
        self.state = ConnectionState.BACKING_OFF
        
        # Calculate backoff time with exponential increase
        backoff = min(self.backoff_time * (2 ** (self.reconnect_attempts - 1)), self.max_backoff_time)
        logger.info(f"Backing off for {backoff}s before reconnection attempt {self.reconnect_attempts}")
        
        await asyncio.sleep(backoff)
        return await self.connect()

    async def _process_messages(self):
        """Process incoming WebSocket messages"""
        try:
            async for message in self.ws:
                try:
                    # Parse the message
                    data = json.loads(message)
                    message_type = data.get('type', '')
                    
                    # Process based on message type
                    if message_type == 'agentResponse':
                        # Content from agent
                        content = data.get('content', '')
                        message_id = data.get('id', '')
                        
                        if message_id in self.responses:
                            self.responses[message_id]['content'] += content
                            self.responses[message_id]['updated_at'] = time.time()
                            
                            # Call appropriate handler if registered
                            if message_id in self.handlers and 'on_update' in self.handlers[message_id]:
                                await self.handlers[message_id]['on_update'](content)
                    
                    elif message_type == 'agentResponseComplete':
                        # Agent response is complete
                        message_id = data.get('id', '')
                        
                        if message_id in self.responses:
                            self.responses[message_id]['complete'] = True
                            
                            # Call appropriate handler if registered
                            if message_id in self.handlers and 'on_complete' in self.handlers[message_id]:
                                await self.handlers[message_id]['on_complete'](self.responses[message_id]['content'])
                    
                    elif message_type == 'state':
                        # Log state transitions
                        connection_id = data.get('connId', '')
                        state = data.get('state', '')
                        prev_state = data.get('prev', '')
                        logger.info(f"Connection {connection_id} transition: {prev_state} -> {state}")
                    
                    else:
                        # Log other message types
                        logger.debug(f"Received message of type {message_type}: {message[:100]}...")
                
                except json.JSONDecodeError:
                    logger.warning(f"Received non-JSON message: {message[:100]}...")
                except Exception as e:
                    logger.error(f"Error processing message: {str(e)}")
                    traceback.print_exc()
        
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"WebSocket connection closed: {e}")
            self.state = ConnectionState.NO_CONNECTION
            
            # Attempt to reconnect
            await self.reconnect()
        
        except Exception as e:
            logger.error(f"Error in message processing: {str(e)}")
            self.state = ConnectionState.ERROR
            traceback.print_exc()

    async def send_message(self, text, message_id=None, on_update=None, on_complete=None):
        """Send a message to the Replit agent
        
        Args:
            text (str): Message text to send
            message_id (str, optional): Unique ID for this message. Generated if None.
            on_update (callable, optional): Callback for content updates
            on_complete (callable, optional): Callback when response is complete
            
        Returns:
            str: Message ID for tracking the response
        """
        # Generate message ID if not provided
        if message_id is None:
            message_id = f"msg_{int(time.time() * 1000)}_{hash(text) % 10000}"
        
        # Register response tracking
        self.responses[message_id] = {
            'content': '',
            'complete': False,
            'created_at': time.time(),
            'updated_at': time.time()
        }
        
        # Register handlers if provided
        if on_update or on_complete:
            self.handlers[message_id] = {}
            if on_update:
                self.handlers[message_id]['on_update'] = on_update
            if on_complete:
                self.handlers[message_id]['on_complete'] = on_complete
        
        # Ensure connection is established
        if self.state != ConnectionState.CONNECTED:
            successful = await self.connect()
            if not successful:
                logger.error("Failed to establish WebSocket connection")
                return None
        
        try:
            # Prepare the message
            message = {
                "type": "prompt",
                "prompt": text,
                "id": message_id,
                "clientId": self.client_id,
                "sessionId": self.session_id
            }
            
            # Send the message
            await self.ws.send(json.dumps(message))
            logger.info(f"Sent message with ID {message_id}")
            
            return message_id
        
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            return None

    async def wait_for_response(self, message_id, timeout=60):
        """Wait for a complete response to a message
        
        Args:
            message_id (str): ID of the message to wait for
            timeout (int): Maximum time to wait in seconds
            
        Returns:
            str: Complete response or None if timed out or error
        """
        if message_id not in self.responses:
            logger.error(f"No response tracking for message ID {message_id}")
            return None
        
        start_time = time.time()
        while not self.responses[message_id]['complete']:
            if time.time() - start_time > timeout:
                logger.warning(f"Timeout waiting for response to message {message_id}")
                return None
            
            # Break if connection is lost
            if self.state == ConnectionState.ERROR or self.state == ConnectionState.CLOSED:
                logger.error(f"Connection error while waiting for response to {message_id}")
                return None
            
            await asyncio.sleep(0.1)
        
        return self.responses[message_id]['content']

    async def close(self):
        """Close the WebSocket connection"""
        if self.ws is not None:
            logger.info("Closing WebSocket connection")
            try:
                await self.ws.close()
                self.state = ConnectionState.CLOSED
                
                # Cancel the message processing task
                if self.task is not None and not self.task.done():
                    self.task.cancel()
                    try:
                        await self.task
                    except asyncio.CancelledError:
                        pass
                
                logger.info("WebSocket connection closed")
            except Exception as e:
                logger.error(f"Error closing WebSocket connection: {str(e)}")

    def is_connected(self):
        """Check if the WebSocket is connected
        
        Returns:
            bool: True if connected, False otherwise
        """
        return self.state == ConnectionState.CONNECTED