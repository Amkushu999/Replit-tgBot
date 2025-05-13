import os
import json
import asyncio
import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import logger

# Initialize logger
log = logger.setup_logger()

class ReplitBrowserAutomation:
    """A class to interact with Replit Agent through browser automation"""
    
    def __init__(self):
        """Initialize the browser automation instance"""
        self.driver = None
        self.initialized = False
        self.REPLIT_URL = "https://replit.com/agent"
    
    async def start(self):
        """Start the browser automation by launching Chrome in headless mode"""
        if self.initialized:
            return True
        
        log.info("Initializing browser automation...")
        
        # Configure Chrome options for headless operation
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        
        try:
            # Initialize the Chrome driver
            self.driver = webdriver.Chrome(options=chrome_options)
            
            # Navigate to Replit Agent
            log.info(f"Navigating to {self.REPLIT_URL}...")
            self.driver.get(self.REPLIT_URL)
            
            # Wait for the page to load
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text'], textarea"))
            )
            
            log.info("Browser automation initialized successfully")
            self.initialized = True
            
            # Try to extract token after initialization
            await self.extract_token()
            
            return True
        
        except Exception as e:
            log.error(f"Failed to initialize browser automation: {e}")
            if self.driver:
                self.driver.quit()
                self.driver = None
            self.initialized = False
            return False
    
    async def send_message(self, text):
        """Send a message to Replit Agent through the browser interface"""
        if not self.initialized:
            success = await self.start()
            if not success:
                raise Exception("Failed to initialize browser automation")
        
        try:
            # Find the input element (could be input or textarea)
            log.info("Locating input element...")
            input_element = None
            
            try:
                input_element = self.driver.find_element(By.CSS_SELECTOR, "textarea")
            except NoSuchElementException:
                try:
                    input_element = self.driver.find_element(By.CSS_SELECTOR, "input[type='text']")
                except NoSuchElementException:
                    raise Exception("Could not find input element")
            
            # Clear any existing text and enter the new message
            input_element.clear()
            input_element.send_keys(text)
            
            log.info("Finding submit button...")
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
                log.info("Submit button not found, pressing Enter key...")
                input_element.send_keys("\n")
            else:
                log.info("Clicking submit button...")
                submit_button.click()
            
            # Wait for the response to appear
            log.info("Waiting for response...")
            
            # Wait for the response to load (this selector might need adjustment)
            WebDriverWait(self.driver, 60).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".agent-response, .message.response, .message:not(.user-message)"))
            )
            
            # Allow some time for the full response to be rendered
            await asyncio.sleep(2)
            
            # Extract the response text
            response_elements = self.driver.find_elements(By.CSS_SELECTOR, ".agent-response, .message.response, .message:not(.user-message)")
            
            # Get the latest response (should be the last element)
            if response_elements:
                latest_response = response_elements[-1]
                response_text = latest_response.text
                log.info(f"Extracted response: {response_text[:100]}...")
                return response_text
            else:
                return "No response received from Replit Agent."
            
        except TimeoutException:
            log.error("Timeout waiting for response from Replit Agent")
            return "Timeout waiting for response from Replit Agent."
        except Exception as e:
            log.error(f"Error sending message via browser automation: {e}")
            return f"Error: {str(e)}"
    
    async def extract_token(self):
        """Extract authentication token from the browser session"""
        if not self.initialized or not self.driver:
            return None
        
        try:
            log.info("Attempting to extract authentication token...")
            
            # Execute JavaScript to extract token from localStorage or cookies
            script = """
            // Try to get token from localStorage
            let token = localStorage.getItem('agent-token') || localStorage.getItem('token');
            
            // If not found, try to get from cookies
            if (!token) {
                const cookies = document.cookie.split(';');
                for (let cookie of cookies) {
                    const [name, value] = cookie.trim().split('=');
                    if (name === 'agent-token' || name === 'token') {
                        token = value;
                        break;
                    }
                }
            }
            
            // If still not found, try to get from network requests
            if (!token) {
                // This approach is speculative and may not work in all browsers
                if (window.performance && window.performance.getEntries) {
                    const entries = window.performance.getEntries();
                    for (let entry of entries) {
                        if (entry.name && entry.name.includes('/api/')) {
                            console.log(entry);
                        }
                    }
                }
            }
            
            return token;
            """
            
            token = self.driver.execute_script(script)
            
            if token:
                log.info("Successfully extracted authentication token")
                return token
            else:
                log.warning("Could not extract authentication token")
                return None
            
        except Exception as e:
            log.error(f"Error extracting token: {e}")
            return None
    
    def close(self):
        """Close the browser session"""
        if self.driver:
            try:
                self.driver.quit()
                log.info("Browser session closed")
            except Exception as e:
                log.error(f"Error closing browser session: {e}")
            finally:
                self.driver = None
                self.initialized = False
