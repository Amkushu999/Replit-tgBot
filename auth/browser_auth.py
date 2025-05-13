import os
import json
import time
import logging
import traceback
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger(__name__)

class BrowserAuthenticator:
    """Handles browser-based authentication and token extraction for Replit"""
    
    def __init__(self, cookie_file, headless=True):
        """Initialize the browser authenticator
        
        Args:
            cookie_file (str): Path to the cookie file
            headless (bool): Whether to run browser in headless mode
        """
        self.cookie_file = cookie_file
        self.headless = headless
        self.driver = None
        self.is_authenticated = False
        self.auth_data = {
            'cookies': {},
            'local_storage': {},
            'session_tokens': {},
            'websocket_params': {},
            'feature_flags': {},
            'timestamp': 0
        }
    
    def setup_browser(self):
        """Set up the browser instance"""
        logger.info("Setting up browser instance")
        chrome_options = Options()
        
        if self.headless:
            chrome_options.add_argument("--headless")
            
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        try:
            logger.info("Creating Chrome WebDriver")
            self.driver = webdriver.Chrome(options=chrome_options)
            logger.info("WebDriver created successfully")
            return True
        except Exception as e:
            logger.error(f"Error creating WebDriver: {str(e)}")
            return False
    
    def load_cookies(self):
        """Load cookies into the browser session"""
        logger.info(f"Loading cookies from {self.cookie_file}")
        
        # First, visit replit.com to be able to set cookies
        self.driver.get("https://replit.com")
        time.sleep(2)  # Wait for page to load
        
        # Load cookies from file
        with open(self.cookie_file, 'r') as f:
            cookies = json.load(f)
        
        # Store cookies in auth_data
        self.auth_data['cookies'] = {cookie.get('name'): cookie.get('value') 
                                     for cookie in cookies if 'name' in cookie and 'value' in cookie}
        
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
    
    def extract_local_storage(self):
        """Extract local storage data from the browser"""
        logger.info("Extracting local storage data")
        try:
            local_storage = self.driver.execute_script("""
                let items = {};
                for (let i = 0; i < localStorage.length; i++) {
                    const key = localStorage.key(i);
                    items[key] = localStorage.getItem(key);
                }
                return items;
            """)
            
            self.auth_data['local_storage'] = local_storage
            logger.info(f"Extracted {len(local_storage)} local storage items")
            return True
        except Exception as e:
            logger.error(f"Error extracting local storage: {str(e)}")
            return False
    
    def extract_websocket_params(self):
        """Extract WebSocket connection parameters"""
        logger.info("Extracting WebSocket parameters")
        try:
            # Execute JavaScript to extract WebSocket-related data
            websocket_params = self.driver.execute_script("""
                // Look for WebSocket connection info in various places
                try {
                    // Check for WebSocket URLs in network requests
                    const wsConnections = performance.getEntriesByType("resource")
                        .filter(r => r.name.includes('wss://') || r.name.includes('ws://'))
                        .map(r => r.name);
                    
                    // Look for connection parameters in localStorage or sessionStorage
                    const sessionId = localStorage.getItem('sessionId') || sessionStorage.getItem('sessionId');
                    const clientId = localStorage.getItem('clientId') || sessionStorage.getItem('clientId');
                    const anonymousId = localStorage.getItem('anonymousId') || sessionStorage.getItem('anonymousId');
                    
                    return {
                        wsUrls: wsConnections,
                        sessionId: sessionId,
                        clientId: clientId,
                        anonymousId: anonymousId,
                        // Add other parameters as they're identified
                    };
                } catch (e) {
                    return {error: e.toString()};
                }
            """)
            
            self.auth_data['websocket_params'] = websocket_params
            logger.info(f"Extracted WebSocket parameters")
            return True
        except Exception as e:
            logger.error(f"Error extracting WebSocket parameters: {str(e)}")
            return False
    
    def extract_feature_flags(self):
        """Extract feature flags from the page"""
        logger.info("Extracting feature flags")
        try:
            # Try to find feature flags in network requests or localStorage
            feature_flags = self.driver.execute_script("""
                // Look for feature flags in various sources
                try {
                    // Check localStorage for LaunchDarkly or feature flag data
                    const ldData = {};
                    for (let i = 0; i < localStorage.length; i++) {
                        const key = localStorage.key(i);
                        if (key.includes('LaunchDarkly') || key.includes('flag-') || key.includes('feature')) {
                            ldData[key] = localStorage.getItem(key);
                        }
                    }
                    
                    // Check for feature flags in the window object
                    const windowFlags = window.featureFlags || window.launchDarkly || {};
                    
                    return {
                        localStorage: ldData,
                        windowFlags: JSON.stringify(windowFlags)
                    };
                } catch (e) {
                    return {error: e.toString()};
                }
            """)
            
            self.auth_data['feature_flags'] = feature_flags
            logger.info(f"Extracted feature flags data")
            return True
        except Exception as e:
            logger.error(f"Error extracting feature flags: {str(e)}")
            return False
    
    def extract_session_tokens(self):
        """Extract session tokens and authentication data"""
        logger.info("Extracting session tokens")
        try:
            session_tokens = self.driver.execute_script("""
                // Look for session tokens in various places
                try {
                    // Check localStorage and sessionStorage for auth tokens
                    const authData = {};
                    
                    // Check localStorage
                    for (let i = 0; i < localStorage.length; i++) {
                        const key = localStorage.key(i);
                        if (key.includes('token') || key.includes('auth') || 
                            key.includes('session') || key.includes('user')) {
                            authData[`localStorage_${key}`] = localStorage.getItem(key);
                        }
                    }
                    
                    // Check sessionStorage
                    for (let i = 0; i < sessionStorage.length; i++) {
                        const key = sessionStorage.key(i);
                        if (key.includes('token') || key.includes('auth') || 
                            key.includes('session') || key.includes('user')) {
                            authData[`sessionStorage_${key}`] = sessionStorage.getItem(key);
                        }
                    }
                    
                    // Try to find user data
                    const userData = window.__INITIAL_DATA__ || window.__PRELOADED_STATE__ || {};
                    
                    return {
                        storage: authData,
                        userData: JSON.stringify(userData)
                    };
                } catch (e) {
                    return {error: e.toString()};
                }
            """)
            
            self.auth_data['session_tokens'] = session_tokens
            logger.info(f"Extracted session tokens data")
            return True
        except Exception as e:
            logger.error(f"Error extracting session tokens: {str(e)}")
            return False
    
    def monitor_network_requests(self):
        """Monitor network requests to capture WebSocket and API calls"""
        logger.info("Setting up network request monitoring")
        try:
            # Execute script to set up network monitoring
            self.driver.execute_script("""
                // This script sets up monitoring for network requests
                // It will store information about WebSocket connections and API calls
                
                window.__network_data = {
                    websocket_connections: [],
                    api_calls: []
                };
                
                // Monitor WebSocket connections
                const originalWebSocket = window.WebSocket;
                window.WebSocket = function(url, protocols) {
                    const ws = new originalWebSocket(url, protocols);
                    
                    window.__network_data.websocket_connections.push({
                        url: url,
                        protocols: protocols,
                        timestamp: new Date().toISOString()
                    });
                    
                    // Monitor WebSocket messages
                    const originalSend = ws.send;
                    ws.send = function(data) {
                        try {
                            window.__network_data.websocket_connections.push({
                                type: 'send',
                                data: data instanceof Blob ? 'Blob data' : data,
                                timestamp: new Date().toISOString()
                            });
                        } catch (e) {
                            console.error('Error capturing WebSocket send:', e);
                        }
                        return originalSend.apply(this, arguments);
                    };
                    
                    ws.addEventListener('message', function(event) {
                        try {
                            window.__network_data.websocket_connections.push({
                                type: 'receive',
                                data: event.data instanceof Blob ? 'Blob data' : event.data,
                                timestamp: new Date().toISOString()
                            });
                        } catch (e) {
                            console.error('Error capturing WebSocket message:', e);
                        }
                    });
                    
                    return ws;
                };
                
                // Monitor fetch API calls
                const originalFetch = window.fetch;
                window.fetch = function(url, options) {
                    try {
                        window.__network_data.api_calls.push({
                            url: url,
                            method: options ? options.method : 'GET',
                            headers: options ? JSON.stringify(options.headers) : '{}',
                            timestamp: new Date().toISOString()
                        });
                    } catch (e) {
                        console.error('Error capturing fetch:', e);
                    }
                    return originalFetch.apply(this, arguments);
                };
                
                // Monitor XHR requests
                const originalXHROpen = XMLHttpRequest.prototype.open;
                XMLHttpRequest.prototype.open = function(method, url) {
                    try {
                        this.__url = url;
                        this.__method = method;
                        window.__network_data.api_calls.push({
                            url: url,
                            method: method,
                            timestamp: new Date().toISOString()
                        });
                    } catch (e) {
                        console.error('Error capturing XHR:', e);
                    }
                    return originalXHROpen.apply(this, arguments);
                };
                
                console.log('Network monitoring set up successfully');
            """)
            
            logger.info("Network monitoring set up successfully")
            return True
        except Exception as e:
            logger.error(f"Error setting up network monitoring: {str(e)}")
            return False
    
    def collect_network_data(self):
        """Collect monitored network data"""
        logger.info("Collecting network monitoring data")
        try:
            network_data = self.driver.execute_script("return window.__network_data;")
            
            if network_data:
                self.auth_data['network_data'] = network_data
                logger.info(f"Collected network data: {len(network_data.get('websocket_connections', []))} WebSocket connections, {len(network_data.get('api_calls', []))} API calls")
                return True
            else:
                logger.warning("No network data collected")
                return False
        except Exception as e:
            logger.error(f"Error collecting network data: {str(e)}")
            return False
    
    def authenticate(self):
        """Perform the full authentication and token extraction process"""
        try:
            logger.info("Starting authentication process")
            
            if not self.setup_browser():
                raise Exception("Failed to set up browser")
            
            self.load_cookies()
            
            # Set up network monitoring before navigating to main page
            self.monitor_network_requests()
            
            # Navigate to Replit AI interface
            logger.info("Navigating to Replit AI page")
            self.driver.get("https://replit.com/ai")
            
            # Wait for page to load properly
            time.sleep(5)
            
            # Check if we're logged in
            page_source = self.driver.page_source.lower()
            if "log in" in page_source or "sign up" in page_source or "login" in page_source:
                logger.error("Not logged in - authentication failed")
                self.is_authenticated = False
                return False
            
            # Extract various authentication data
            self.extract_local_storage()
            self.extract_websocket_params()
            self.extract_feature_flags()
            self.extract_session_tokens()
            
            # Interact with the page to trigger WebSocket connections
            try:
                # Try to find and interact with the chat input
                input_selectors = [
                    "//textarea[contains(@placeholder, 'Ask')]",
                    "//textarea[contains(@placeholder, 'Message')]",
                    "//textarea[contains(@placeholder, 'Type')]",
                    "//div[contains(@contenteditable, 'true')]",
                    "//input[contains(@placeholder, 'Message')]"
                ]
                
                for selector in input_selectors:
                    try:
                        input_element = WebDriverWait(self.driver, 3).until(
                            EC.presence_of_element_located((By.XPATH, selector))
                        )
                        if input_element:
                            logger.info(f"Found input field with selector: {selector}")
                            # Just click on it to focus, don't send any message
                            input_element.click()
                            time.sleep(2)
                            break
                    except:
                        continue
            except Exception as e:
                logger.warning(f"Could not interact with chat input: {str(e)}")
            
            # Collect network data after page interaction
            time.sleep(3)  # Wait for WebSocket connections to establish
            self.collect_network_data()
            
            # Record authentication timestamp
            self.auth_data['timestamp'] = int(time.time())
            self.is_authenticated = True
            
            logger.info("Authentication and token extraction completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Authentication process failed: {str(e)}")
            logger.error(traceback.format_exc())
            self.is_authenticated = False
            return False
    
    def get_auth_data(self):
        """Get the extracted authentication data"""
        if not self.is_authenticated:
            logger.warning("Attempting to get auth data without successful authentication")
        
        return self.auth_data
    
    def close(self):
        """Close the browser session"""
        if self.driver:
            logger.info("Closing browser session")
            try:
                self.driver.quit()
                self.driver = None
            except Exception as e:
                logger.error(f"Error closing browser: {str(e)}")