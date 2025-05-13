import os
import json
import asyncio
import websockets
import logging
import uuid
import time
from utils import generate_nonce
import logger

# Initialize logger
log = logger.setup_logger()

class ReplitAgentAPI:
    """A class for interacting with the Replit Agent API directly via WebSockets"""
    
    def __init__(self, token):
        """Initialize the ReplitAgentAPI with the provided token"""
        self.token = token
        self.ws = None
        self.connected = False
        self.conversation_id = None
        self.message_queue = {}  # Store message IDs and responses
        self.BASE_WS_URL = "wss://replit.com/api/v1/agent/ws"
        
    async def connect(self):
        """Establish a WebSocket connection to the Replit Agent API"""
        try:
            # Generate conversation ID if not already set
            if not self.conversation_id:
                self.conversation_id = str(uuid.uuid4())
                log.info(f"Generated new conversation ID: {self.conversation_id}")
            
            # Generate URL with token and conversation ID
            url = f"{self.BASE_WS_URL}?token={self.token}&conversationId={self.conversation_id}"
            
            # Connect to the WebSocket
            log.info("Connecting to Replit Agent WebSocket API...")
            self.ws = await websockets.connect(url)
            self.connected = True
            log.info("Successfully connected to Replit Agent WebSocket API")
            
            # Start listening for messages in the background
            asyncio.create_task(self._listen_for_messages())
            
            return True
        except Exception as e:
            log.error(f"Failed to connect to Replit Agent WebSocket API: {e}")
            self.connected = False
            return False
    
    async def _listen_for_messages(self):
        """Listen for incoming messages from the WebSocket connection"""
        if not self.ws:
            log.error("Cannot listen for messages: WebSocket connection not established")
            return
        
        try:
            while True:
                message = await self.ws.recv()
                await self._process_message(message)
        except websockets.exceptions.ConnectionClosed:
            log.warning("WebSocket connection closed")
            self.connected = False
        except Exception as e:
            log.error(f"Error listening for messages: {e}")
            self.connected = False
    
    async def _process_message(self, message):
        """Process incoming WebSocket messages"""
        try:
            data = json.loads(message)
            message_id = data.get("id")
            
            if message_id and message_id in self.message_queue:
                # Update the response for this message ID
                if "content" in data:
                    self.message_queue[message_id]["response"] += data["content"]
                
                # Check if this is the final message
                if data.get("done", False):
                    self.message_queue[message_id]["complete"] = True
                    log.info(f"Received complete response for message ID: {message_id}")
            
            # Log other messages for debugging
            else:
                log.debug(f"Received message without known ID: {message[:100]}...")
                
        except json.JSONDecodeError:
            log.error(f"Received invalid JSON: {message[:100]}...")
        except Exception as e:
            log.error(f"Error processing message: {e}")
    
    async def send_message(self, text):
        """Send a message to the Replit Agent and wait for the response"""
        if not self.connected:
            await self.connect()
            if not self.connected:
                raise Exception("Failed to connect to Replit Agent API")
        
        try:
            # Generate unique message ID
            message_id = generate_nonce()
            
            # Initialize entry in message queue
            self.message_queue[message_id] = {
                "response": "",
                "complete": False,
                "timestamp": time.time()
            }
            
            # Prepare message payload
            payload = {
                "id": message_id,
                "content": text,
                "action": "prompt"
            }
            
            # Send the message
            await self.ws.send(json.dumps(payload))
            log.info(f"Sent message with ID: {message_id}")
            
            # Wait for the response with timeout
            timeout = 60  # 60 seconds timeout
            start_time = time.time()
            
            while not self.message_queue[message_id]["complete"]:
                if time.time() - start_time > timeout:
                    raise TimeoutError("Timed out waiting for response from Replit Agent")
                await asyncio.sleep(0.1)
            
            # Return the complete response
            return self.message_queue[message_id]["response"]
            
        except Exception as e:
            log.error(f"Error sending message: {e}")
            raise
    
    def is_connected(self):
        """Check if the WebSocket connection is still active"""
        return self.connected
    
    async def close(self):
        """Close the WebSocket connection"""
        if self.ws:
            await self.ws.close()
            self.connected = False
            log.info("Closed WebSocket connection to Replit Agent API")
