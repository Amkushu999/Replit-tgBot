import os
import json
import time
import asyncio
import logging
import traceback
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException

logger = logging.getLogger(__name__)

class ReplitBrowserClient:
    """Client for interacting with Replit agent through browser automation"""
    
    def __init__(self, cookies_file=None, headless=True):
        """Initialize the browser client
        
        Args:
            cookies_file (str, optional): Path to the cookies file
            headless (bool): Whether to run the browser in headless mode
        """
        self.cookies_file = cookies_file
        self.headless = headless
        self.driver = None
        self.initialized = False
        self.REPLIT_URL = "https://replit.com/ai"
        self.last_extraction_time = 0
        self.auth_data = None
    
    async def start(self):
        """Start the browser session"""
        if self.initialized:
            logger.info("Browser already initialized")
            return True
        
        logger.info("Initializing browser client...")
        
        # Configure Chrome options for headless operation
        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        try:
            # Initialize the Chrome driver
            self.driver = webdriver.Chrome(options=chrome_options)
            
            # Load cookies if available
            if self.cookies_file and os.path.exists(self.cookies_file):
                await self._load_cookies()
            
            # Navigate to Replit Agent
            logger.info(f"Navigating to {self.REPLIT_URL}...")
            self.driver.get(self.REPLIT_URL)
            
            # Wait for the page to load
            try:
                WebDriverWait(self.driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text'], textarea"))
                )
            except TimeoutException:
                # If we can't find the input, check if we need to log in
                if "Log in" in self.driver.page_source or "Sign in" in self.driver.page_source:
                    logger.error("Authentication required - not logged in")
                    self.initialized = False
                    return False
            
            # Setup monitoring for network requests
            self._setup_network_monitoring()
            
            logger.info("Browser client initialized successfully")
            self.initialized = True
            
            # Extract auth data after initialization
            await self.extract_auth_data()
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to initialize browser client: {e}")
            logger.error(traceback.format_exc())
            if self.driver:
                self.driver.quit()
                self.driver = None
            self.initialized = False
            return False
    
    async def _load_cookies(self):
        """Load cookies from file into the browser session"""
        if not self.driver:
            logger.error("Browser not initialized")
            return False
        
        try:
            logger.info(f"Loading cookies from {self.cookies_file}")
            
            # First visit the domain to set cookies
            self.driver.get("https://replit.com")
            time.sleep(2)  # Wait for page to load
            
            # Load cookies from file
            with open(self.cookies_file, 'r') as f:
                cookies = json.load(f)
            
            # Add cookies to browser
            for cookie in cookies:
                # Skip cookies that might cause issues
                if 'expiry' in cookie:
                    del cookie['expiry']
                
                try:
                    if 'domain' in cookie and ('replit.com' in cookie['domain']):
                        # Modify cookie domain if needed
                        if cookie['domain'].startswith('.'):
                            cookie['domain'] = cookie['domain'][1:]
                        self.driver.add_cookie(cookie)
                except Exception as e:
                    logger.warning(f"Error adding cookie {cookie.get('name')}: {str(e)}")
            
            logger.info("Cookies loaded successfully")
            return True
        except Exception as e:
            logger.error(f"Error loading cookies: {str(e)}")
            return False
    
    def _setup_network_monitoring(self):
        """Set up monitoring of network requests in the browser"""
        if not self.driver:
            return
        
        try:
            self.driver.execute_script("""
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
            """)
            logger.info("Network monitoring set up successfully")
        except Exception as e:
            logger.error(f"Error setting up network monitoring: {str(e)}")
    
    async def extract_auth_data(self):
        """Extract authentication data from the browser session"""
        if not self.initialized or not self.driver:
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
                'network_traffic': {},
                'timestamp': int(time.time())
            }
            
            # Extract cookies
            cookies = self.driver.get_cookies()
            auth_data['cookies'] = {cookie['name']: cookie['value'] for cookie in cookies}
            
            # Extract localStorage data
            local_storage = self.driver.execute_script("""
                let items = {};
                for (let i = 0; i < localStorage.length; i++) {
                    const key = localStorage.key(i);
                    items[key] = localStorage.getItem(key);
                }
                return items;
            """)
            auth_data['local_storage'] = local_storage
            
            # Extract WebSocket traffic data
            ws_traffic = self.driver.execute_script("return window.__ws_traffic;")
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
            input_element = None
            
            try:
                input_element = self.driver.find_element(By.CSS_SELECTOR, "textarea")
            except NoSuchElementException:
                try:
                    input_element = self.driver.find_element(By.CSS_SELECTOR, "input[type='text']")
                except NoSuchElementException:
                    # Try XPath selectors if CSS selectors fail
                    input_selectors = [
                        "//textarea[contains(@placeholder, 'Ask')]",
                        "//textarea[contains(@placeholder, 'Message')]",
                        "//textarea[contains(@placeholder, 'Type')]",
                        "//div[contains(@contenteditable, 'true')]",
                        "//input[contains(@placeholder, 'Message')]"
                    ]
                    
                    for selector in input_selectors:
                        try:
                            input_element = self.driver.find_element(By.XPATH, selector)
                            if input_element:
                                break
                        except:
                            continue
            
            if not input_element:
                raise Exception("Could not find input element")
            
            # Clear any existing text and enter the new message
            input_element.clear()
            input_element.send_keys(text)
            
            logger.info("Finding submit button...")
            # Find the submit button and click it
            submit_button = None
            
            # Try different selectors that might identify the submit button
            selectors = [
                "button[type='submit']", 
                "button.send-button", 
                "button:has(svg)",  # Button with an SVG icon
                "div.input-area button",  # Button in an input area
                "form button"  # Button within a form
            ]
            
            for selector in selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for element in elements:
                        if element.is_displayed() and element.is_enabled():
                            submit_button = element
                            break
                    if submit_button:
                        break
                except:
                    continue
            
            if not submit_button:
                # As a fallback, try to press Enter key on the input field
                logger.info("Submit button not found, pressing Enter key...")
                input_element.send_keys(Keys.RETURN)
            else:
                logger.info("Clicking submit button...")
                submit_button.click()
            
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
                    WebDriverWait(self.driver, 60).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
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
                    response_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if response_elements:
                        # Get the latest response (should be the last element)
                        latest_response = response_elements[-1]
                        response_text = latest_response.text
                        if response_text:
                            break
                except:
                    continue
            
            if response_text:
                logger.info(f"Extracted response: {response_text[:100]}...")
                
                # Try to extract updated auth data in the background
                asyncio.create_task(self.extract_auth_data())
                
                return response_text
            else:
                return "No response received from Replit Agent."
            
        except TimeoutException:
            logger.error("Timeout waiting for response from Replit Agent")
            return "Timeout waiting for response from Replit Agent."
        except Exception as e:
            logger.error(f"Error sending message via browser automation: {e}")
            logger.error(traceback.format_exc())
            return f"Error: {str(e)}"
    
    def get_auth_data(self):
        """Get the cached authentication data"""
        return self.auth_data
    
    def close(self):
        """Close the browser session"""
        if self.driver:
            logger.info("Closing browser session")
            try:
                self.driver.quit()
            except Exception as e:
                logger.error(f"Error closing browser session: {e}")
            finally:
                self.driver = None
                self.initialized = False