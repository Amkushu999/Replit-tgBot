import os
import json
import time
import asyncio
import logging
import traceback
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

class ReplitBrowserClient:
    """Client for interacting with Replit agent through browser automation using Playwright"""
    
    def __init__(self, cookies_file=None, headless=True):
        """Initialize the browser client
        
        Args:
            cookies_file (str, optional): Path to the cookies file
            headless (bool): Whether to run the browser in headless mode
        """
        self.cookies_file = cookies_file
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.initialized = False
        self.REPLIT_URL = "https://replit.com/ai"
        self.last_extraction_time = 0
        self.auth_data = None
    
    async def start(self):
        """Start the browser session"""
        if self.initialized:
            logger.info("Browser already initialized")
            return True
        
        logger.info("Initializing browser client with Playwright...")
        
        try:
            # Launch playwright
            self.playwright = await async_playwright().start()
            
            # Launch chromium browser
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ]
            )
            
            # Create a browser context
            self.context = await self.browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            
            # Create a new page
            self.page = await self.context.new_page()
            
            # Load cookies if available
            if self.cookies_file and os.path.exists(self.cookies_file):
                await self._load_cookies()
            
            # Navigate to Replit Agent
            logger.info(f"Navigating to {self.REPLIT_URL}...")
            await self.page.goto(self.REPLIT_URL, wait_until="networkidle")
            
            # Wait for the page to load
            try:
                # Check if we're logged in
                input_selector = "textarea, input[type='text']"
                await self.page.wait_for_selector(input_selector, timeout=20000)
            except Exception as e:
                # If we can't find the input, check if we need to log in
                page_content = await self.page.content()
                if "Log in" in page_content or "Sign in" in page_content:
                    logger.error("Authentication required - not logged in")
                    self.initialized = False
                    return False
            
            # Setup monitoring for network requests
            await self._setup_network_monitoring()
            
            logger.info("Browser client initialized successfully")
            self.initialized = True
            
            # Extract auth data after initialization
            await self.extract_auth_data()
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to initialize browser client: {e}")
            logger.error(traceback.format_exc())
            await self.close()
            self.initialized = False
            return False
    
    async def _load_cookies(self):
        """Load cookies from file into the browser session"""
        try:
            logger.info(f"Loading cookies from {self.cookies_file}")
            
            # First visit the domain to set cookies
            await self.page.goto("https://replit.com", wait_until="domcontentloaded")
            
            # Load cookies from file
            with open(self.cookies_file, 'r') as f:
                cookies = json.load(f)
            
            # Convert cookies to Playwright format
            playwright_cookies = []
            for cookie in cookies:
                if 'domain' in cookie and ('replit.com' in cookie['domain']):
                    playwright_cookie = {
                        'name': cookie.get('name'),
                        'value': cookie.get('value'),
                        'domain': cookie.get('domain'),
                        'path': cookie.get('path', '/'),
                        'secure': cookie.get('secure', False),
                        'httpOnly': cookie.get('httpOnly', False)
                    }
                    # Add expiry if present
                    if 'expiry' in cookie:
                        playwright_cookie['expires'] = cookie['expiry']
                    playwright_cookies.append(playwright_cookie)
            
            # Add cookies to context
            await self.context.add_cookies(playwright_cookies)
            
            # Verify cookies were set
            logger.info(f"Added {len(playwright_cookies)} cookies")
            
            return True
        except Exception as e:
            logger.error(f"Error loading cookies: {str(e)}")
            logger.error(traceback.format_exc())
            return False
    
    async def _setup_network_monitoring(self):
        """Set up monitoring of network requests in the browser"""
        try:
            # Add JavaScript to monitor WebSockets
            await self.page.evaluate("""() => {
                // Store WebSocket traffic information
                window.__ws_traffic = {
                    connections: [],
                    messages: []
                };
                
                // Override WebSocket to monitor traffic
                const originalWebSocket = window.WebSocket;
                window.WebSocket = function(url, protocols) {
                    console.log('WebSocket connection to:', url);
                    
                    // Create actual WebSocket
                    const ws = new originalWebSocket(url, protocols);
                    
                    // Log connection
                    window.__ws_traffic.connections.push({
                        url: url,
                        protocols: protocols,
                        time: new Date().toISOString()
                    });
                    
                    // Monitor send method
                    const originalSend = ws.send;
                    ws.send = function(data) {
                        try {
                            window.__ws_traffic.messages.push({
                                direction: 'outgoing',
                                data: typeof data === 'string' ? data : '[binary data]',
                                time: new Date().toISOString()
                            });
                            console.log('WS SEND:', typeof data === 'string' ? data : '[binary data]');
                        } catch (e) {
                            console.error('Error logging WebSocket send:', e);
                        }
                        
                        return originalSend.apply(this, arguments);
                    };
                    
                    // Monitor incoming messages
                    ws.addEventListener('message', function(event) {
                        try {
                            window.__ws_traffic.messages.push({
                                direction: 'incoming',
                                data: typeof event.data === 'string' ? event.data : '[binary data]',
                                time: new Date().toISOString()
                            });
                            console.log('WS RECEIVE:', typeof event.data === 'string' ? event.data : '[binary data]');
                        } catch (e) {
                            console.error('Error logging WebSocket message:', e);
                        }
                    });
                    
                    return ws;
                };
                
                console.log('WebSocket monitoring set up');
            }""")
            logger.info("Network monitoring set up successfully")
            return True
        except Exception as e:
            logger.error(f"Error setting up network monitoring: {str(e)}")
            logger.error(traceback.format_exc())
            return False
    
    async def extract_auth_data(self):
        """Extract authentication data from the browser session"""
        if not self.initialized or not self.page:
            logger.error("Browser not initialized")
            return None
        
        # Only extract once per 5 minutes to avoid excessive processing
        current_time = time.time()
        if self.auth_data and current_time - self.last_extraction_time < 300:
            logger.info("Using cached auth data (extracted less than 5 minutes ago)")
            return self.auth_data
        
        try:
            logger.info("Extracting authentication data from browser")
            
            auth_data = {
                'cookies': {},
                'local_storage': {},
                'websocket_data': {},
                'timestamp': int(time.time())
            }
            
            # Extract cookies
            cookies = await self.context.cookies()
            auth_data['cookies'] = {cookie['name']: cookie['value'] for cookie in cookies}
            
            # Extract localStorage data
            local_storage = await self.page.evaluate("""() => {
                let items = {};
                for (let i = 0; i < localStorage.length; i++) {
                    const key = localStorage.key(i);
                    items[key] = localStorage.getItem(key);
                }
                return items;
            }""")
            auth_data['local_storage'] = local_storage
            
            # Extract WebSocket traffic data
            ws_traffic = await self.page.evaluate("() => window.__ws_traffic")
            if ws_traffic:
                auth_data['websocket_data'] = ws_traffic
                
                # Extract WebSocket connection parameters
                for msg in ws_traffic.get('messages', []):
                    if msg.get('direction') == 'outgoing' and isinstance(msg.get('data'), str):
                        try:
                            data = json.loads(msg['data'])
                            if 'clientId' in data and 'sessionId' in data:
                                auth_data['connection_params'] = {
                                    'clientId': data['clientId'],
                                    'sessionId': data['sessionId'],
                                    'tokenCluster': data.get('tokenCluster', 'picard')
                                }
                                break
                        except:
                            pass
            
            self.auth_data = auth_data
            self.last_extraction_time = current_time
            logger.info(f"Extracted {len(auth_data['cookies'])} cookies and {len(auth_data['local_storage'])} localStorage items")
            
            return auth_data
        
        except Exception as e:
            logger.error(f"Error extracting auth data: {str(e)}")
            logger.error(traceback.format_exc())
            return None
    
    async def send_message(self, text):
        """Send a message to Replit Agent and get the response
        
        Args:
            text (str): Message to send to Replit Agent
            
        Returns:
            str: Response from Replit Agent
        """
        if not self.initialized:
            success = await self.start()
            if not success:
                raise Exception("Failed to initialize browser")
        
        try:
            # Find the input element (could be input or textarea)
            logger.info("Locating input element...")
            
            # Try various input selectors
            input_selectors = [
                "textarea", 
                "input[type='text']",
                "div[contenteditable='true']",
                "[placeholder*='Ask']",
                "[placeholder*='Message']",
                "[placeholder*='Type']"
            ]
            
            input_element = None
            for selector in input_selectors:
                try:
                    input_element = await self.page.query_selector(selector)
                    if input_element:
                        break
                except:
                    continue
            
            if not input_element:
                raise Exception("Could not find input element")
            
            # Clear any existing text and enter the new message
            await input_element.click()
            await input_element.fill("")
            await input_element.type(text)
            
            logger.info("Finding submit button...")
            # Find the submit button and click it
            
            # Try different selectors that might identify the submit button
            submit_selectors = [
                "button[type='submit']", 
                "button.send-button", 
                "button:has(svg)",  
                "div.input-area button",  
                "form button"  
            ]
            
            submit_button = None
            for selector in submit_selectors:
                try:
                    elements = await self.page.query_selector_all(selector)
                    for element in elements:
                        is_visible = await element.is_visible()
                        if is_visible:
                            submit_button = element
                            break
                    if submit_button:
                        break
                except:
                    continue
            
            if not submit_button:
                # As a fallback, try to press Enter key on the input field
                logger.info("Submit button not found, pressing Enter key...")
                await input_element.press("Enter")
            else:
                logger.info("Clicking submit button...")
                await submit_button.click()
            
            # Wait for the response to appear
            logger.info("Waiting for response...")
            
            # Wait for the response to load (this selector might need adjustment)
            response_selectors = [
                ".agent-response", 
                ".message.response", 
                ".message:not(.user-message)",
                ".response-container",
                "[data-testid='ai-response']"
            ]
            
            response_found = False
            for selector in response_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=60000)
                    response_found = True
                    break
                except:
                    continue
            
            if not response_found:
                logger.warning("Could not find response element using standard selectors")
            
            # Allow some time for the full response to be rendered
            await asyncio.sleep(2)
            
            # Extract the response text
            response_text = ""
            for selector in response_selectors:
                try:
                    elements = await self.page.query_selector_all(selector)
                    for element in elements:
                        text = await element.text_content()
                        if text and len(text.strip()) > 0:
                            response_text = text.strip()
                            break
                    if response_text:
                        break
                except:
                    continue
            
            if not response_text:
                # Fallback: get all visible text on the page after the user's message
                logger.warning("Standard response extraction failed, using fallback method")
                try:
                    # Get all text content
                    all_text = await self.page.evaluate("""() => {
                        // Return all visible text nodes in the document
                        const extractVisibleText = () => {
                            const walker = document.createTreeWalker(
                                document.body,
                                NodeFilter.SHOW_TEXT,
                                null,
                                false
                            );
                            
                            let text = [];
                            let node;
                            
                            while(node = walker.nextNode()) {
                                const element = node.parentElement;
                                
                                // Check if the element or any of its parents are hidden
                                let isVisible = true;
                                let parent = element;
                                
                                while(parent) {
                                    const style = window.getComputedStyle(parent);
                                    if(style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                                        isVisible = false;
                                        break;
                                    }
                                    parent = parent.parentElement;
                                }
                                
                                if(isVisible && node.textContent.trim()) {
                                    text.push(node.textContent.trim());
                                }
                            }
                            
                            return text.join(' ');
                        };
                        
                        return extractVisibleText();
                    }""")
                    
                    # Try to extract just the response part
                    if text and text.lower().find(text.lower()) >= 0:
                        response_text = all_text[all_text.lower().find(text.lower()) + len(text):].strip()
                except Exception as e:
                    logger.error(f"Error in fallback extraction: {e}")
            
            logger.info(f"Extracted response of length {len(response_text)}")
            return response_text
        
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            logger.error(traceback.format_exc())
            return f"Error: {str(e)}"
    
    def get_auth_data(self):
        """Get the cached authentication data"""
        return self.auth_data
    
    async def close(self):
        """Close the browser session"""
        logger.info("Closing browser client...")
        
        try:
            if self.browser:
                await self.browser.close()
                self.browser = None
                
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
                
            self.page = None
            self.context = None
            self.initialized = False
            logger.info("Browser client closed")
            return True
        except Exception as e:
            logger.error(f"Error closing browser: {str(e)}")
            return False