"""
Educative Course Downloader with Advanced Authentication Handling
Download entire Agentic System Design course as PDF with proper auth
"""

import os
from dotenv import load_dotenv
load_dotenv()

import sys
import json
import time
import logging
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime
import pickle
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Web scraping and automation
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# PDF handling
from PyPDF2 import PdfMerger
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Optional: webdriver manager for automatic ChromeDriver
try:
    from webdriver_manager.chrome import ChromeDriverManager
    WEBDRIVER_MANAGER_AVAILABLE = True
except ImportError:
    WEBDRIVER_MANAGER_AVAILABLE = False

# ==================== Configuration ====================

class Config:
    """Central configuration"""
    # Paths
    OUTPUT_DIR = Path("./educative_course")
    PDF_DIR = OUTPUT_DIR / "pdfs"
    COOKIES_FILE = OUTPUT_DIR / "session_cookies.pkl"
    LOG_FILE = OUTPUT_DIR / "download.log"
    
    # Educative
    BASE_URL = "https://www.educative.io"
    COURSE_URL = "https://www.educative.io/courses/agentic-ai-systems"
    LOGIN_URL = "https://www.educative.io/login"
    
    # Credentials (use environment variables for security)
    EMAIL = os.getenv("EDUCATIVE_EMAIL", "")
    PASSWORD = os.getenv("EDUCATIVE_PASSWORD", "")
    
    # Timeouts
    PAGE_LOAD_TIMEOUT = 15
    WAIT_TIMEOUT = 20
    REQUEST_TIMEOUT = 30
    
    # Delays (be respectful to servers)
    DELAY_BETWEEN_REQUESTS = 1
    DELAY_AFTER_LOGIN = 3
    
    # Parallel processing
    MAX_WORKERS = 3  # Number of parallel downloads
    
    # Chrome options
    HEADLESS = False  # Set to False to see browser for debugging
    WINDOW_SIZE = "1920x1080"
    USER_DATA_DIR = OUTPUT_DIR / "chrome_profile"  # Persist session between runs
    
    @classmethod
    def setup(cls):
        """Initialize directories"""
        cls.OUTPUT_DIR.mkdir(exist_ok=True)
        cls.PDF_DIR.mkdir(exist_ok=True)

# ==================== Logging Setup ====================

def setup_logger(name):
    """Configure logger with file and console output"""
    Config.setup()
    
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    # File handler
    fh = logging.FileHandler(Config.LOG_FILE)
    fh.setLevel(logging.DEBUG)
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger

logger = setup_logger(__name__)

# ==================== Authentication Handler ====================

class AuthenticationHandler:
    """Manages authentication with Educative"""
    
    def __init__(self, driver: webdriver.Chrome):
        self.driver = driver
        self.wait = WebDriverWait(driver, Config.WAIT_TIMEOUT)
    
    def load_cookies(self) -> bool:
        """Load saved session cookies"""
        if not Config.COOKIES_FILE.exists():
            logger.info("No saved cookies found")
            return False
        
        try:
            logger.info("Loading saved session cookies...")
            self.driver.get(Config.BASE_URL)
            time.sleep(1)
            
            with open(Config.COOKIES_FILE, 'rb') as f:
                cookies = pickle.load(f)
            
            for cookie in cookies:
                try:
                    # Skip certain cookie attributes that might cause issues
                    if 'expiry' in cookie:
                        cookie['expiry'] = int(cookie['expiry'])
                    self.driver.add_cookie(cookie)
                except Exception as e:
                    logger.debug(f"Skipping cookie {cookie.get('name', 'unknown')}: {e}")
            
            logger.info("✓ Cookies loaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"✗ Failed to load cookies: {e}")
            return False
    
    def save_cookies(self):
        """Save session cookies for future use"""
        try:
            with open(Config.COOKIES_FILE, 'wb') as f:
                pickle.dump(self.driver.get_cookies(), f)
            logger.info(f"✓ Session cookies saved to {Config.COOKIES_FILE}")
        except Exception as e:
            logger.error(f"✗ Failed to save cookies: {e}")
    
    def is_authenticated(self) -> bool:
        """Check if user is authenticated by looking for logged_in cookie"""
        try:
            # Method 1: Check for logged_in cookie (most reliable)
            logger.info("Checking authentication via cookie...")
            is_logged_in = bool(self.driver.execute_script(
                '''return document.cookie.includes('logged_in')'''
            ))
            
            if is_logged_in:
                logger.info("✓ User is authenticated (cookie found)")
                return True
            
            # Method 2: Try navigating to course and checking
            logger.info("Cookie not found, checking course access...")
            self.driver.get(Config.COURSE_URL)
            time.sleep(2)
            
            # Check if we can see course content (not login page)
            try:
                # Check if we're on login page
                current_url = self.driver.current_url
                if "login" in current_url.lower():
                    logger.warning("⚠ Redirected to login page - not authenticated")
                    return False
                
                # Try to find course content
                self.wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "[class*='lesson'], [class*='content'], [class*='course']"))
                )
                logger.info("✓ User is authenticated (course content visible)")
                return True
            except:
                logger.warning("⚠ Could not verify authentication")
                return False
                
        except Exception as e:
            logger.error(f"✗ Authentication check failed: {e}")
            return False
    
    def login_with_google(self, email: str, password: str) -> bool:
        """Login using Google OAuth (Continue with Google)"""
        try:
            logger.info("Attempting login with Google...")
            
            # Navigate to login page
            self.driver.get(Config.LOGIN_URL)
            time.sleep(2)
            
            # Click "Continue with Google" button
            logger.info("Looking for 'Continue with Google' button...")
            google_button = self.wait.until(
                EC.element_to_be_clickable((
                    By.XPATH, 
                    "//button[contains(., 'Continue with Google')] | //a[contains(., 'Continue with Google')]"
                ))
            )
            google_button.click()
            time.sleep(2)
            
            # Switch to Google login window if needed
            if len(self.driver.window_handles) > 1:
                self.driver.switch_to.window(self.driver.window_handles[-1])
            
            # Enter Google email
            logger.info("Entering Google email...")
            email_field = self.wait.until(
                EC.presence_of_element_located((By.ID, "identifierId"))
            )
            email_field.clear()
            email_field.send_keys(email)
            
            # Click Next
            next_button = self.wait.until(
                EC.element_to_be_clickable((By.ID, "identifierNext"))
            )
            next_button.click()
            time.sleep(2)
            
            # Enter Google password
            logger.info("Entering Google password...")
            password_field = self.wait.until(
                EC.presence_of_element_located((By.NAME, "password"))
            )
            password_field.clear()
            password_field.send_keys(password)
            
            # Click Next
            password_next = self.wait.until(
                EC.element_to_be_clickable((By.ID, "passwordNext"))
            )
            password_next.click()
            
            # Wait for redirect back to Educative
            time.sleep(Config.DELAY_AFTER_LOGIN)
            
            # Switch back to main window if needed
            if len(self.driver.window_handles) > 1:
                self.driver.switch_to.window(self.driver.window_handles[0])
            
            # Check if login was successful
            if self.is_authenticated():
                logger.info("✓ Google login successful!")
                self.save_cookies()
                return True
            else:
                logger.error("✗ Google login failed - still not authenticated")
                return False
                
        except Exception as e:
            logger.error(f"✗ Google login error: {e}")
            return False
    
    def login_with_otp_support(self, email: str, password: str, otp_timeout: int = 120) -> bool:
        """Perform login with OTP/2FA support - fills email/password, waits for OTP"""
        try:
            logger.info("=" * 60)
            logger.info("Email/Password Login with OTP Support")
            logger.info("=" * 60)
            
            # Navigate to login page
            logger.info("Navigating to login page...")
            self.driver.get(Config.LOGIN_URL)
            time.sleep(3)
            
            # Take screenshot for debugging
            screenshot_path = Config.OUTPUT_DIR / "login_page.png"
            self.driver.save_screenshot(str(screenshot_path))
            logger.debug(f"Screenshot saved to {screenshot_path}")
            
            # Find and fill email field - try multiple selectors
            logger.info("Entering email...")
            email_field = None
            email_selectors = [
                (By.NAME, "email"),
                (By.ID, "email"),
                (By.CSS_SELECTOR, "input[type='email']"),
                (By.CSS_SELECTOR, "input[name='email']"),
                (By.XPATH, "//input[@type='email']"),
                (By.XPATH, "//input[@name='email']"),
                (By.XPATH, "//input[@placeholder='Email' or @placeholder='email']")
            ]
            
            for by, selector in email_selectors:
                try:
                    email_field = self.wait.until(
                        EC.element_to_be_clickable((by, selector))
                    )
                    logger.debug(f"Found email field using: {by}='{selector}'")
                    break
                except Exception as e:
                    logger.debug(f"Selector {by}='{selector}' failed: {e}")
                    continue
            
            if not email_field:
                raise Exception("Could not find email input field with any selector")
            
            # Scroll to element and click to focus
            self.driver.execute_script("arguments[0].scrollIntoView(true);", email_field)
            time.sleep(0.5)
            email_field.click()
            time.sleep(0.5)
            
            # Clear and enter email
            email_field.clear()
            time.sleep(0.3)
            email_field.send_keys(email)
            time.sleep(1)
            
            logger.info(f"✓ Email entered: {email}")
            
            # Find and fill password field - try multiple selectors
            logger.info("Entering password...")
            password_field = None
            password_selectors = [
                (By.NAME, "password"),
                (By.ID, "password"),
                (By.CSS_SELECTOR, "input[type='password']"),
                (By.CSS_SELECTOR, "input[name='password']"),
                (By.XPATH, "//input[@type='password']"),
                (By.XPATH, "//input[@name='password']"),
                (By.XPATH, "//input[@placeholder='Password' or @placeholder='password']")
            ]
            
            for by, selector in password_selectors:
                try:
                    password_field = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((by, selector))
                    )
                    logger.debug(f"Found password field using: {by}='{selector}'")
                    break
                except Exception as e:
                    logger.debug(f"Selector {by}='{selector}' failed: {e}")
                    continue
            
            if not password_field:
                raise Exception("Could not find password input field with any selector")
            
            # Scroll to element and click to focus
            self.driver.execute_script("arguments[0].scrollIntoView(true);", password_field)
            time.sleep(0.5)
            password_field.click()
            time.sleep(0.5)
            
            # Clear and enter password
            password_field.clear()
            time.sleep(0.3)
            password_field.send_keys(password)
            time.sleep(1)
            
            logger.info("✓ Password entered successfully")
            
            # Click login button - try multiple selectors
            logger.info("Clicking login button...")
            login_button = None
            login_selectors = [
                (By.XPATH, "//button[@type='submit']"),
                (By.XPATH, "//button[contains(text(), 'Log In') or contains(text(), 'Login')]"),
                (By.XPATH, "//button[contains(., 'Log In') or contains(., 'Login')]"),
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.XPATH, "//input[@type='submit']"),
                (By.XPATH, "//button[contains(@class, 'login')]"),
                (By.XPATH, "//button[contains(@class, 'submit')]")
            ]
            
            for by, selector in login_selectors:
                try:
                    login_button = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((by, selector))
                    )
                    logger.debug(f"Found login button using: {by}='{selector}'")
                    break
                except Exception as e:
                    logger.debug(f"Selector {by}='{selector}' failed: {e}")
                    continue
            
            if not login_button:
                raise Exception("Could not find login button with any selector")
            
            # Scroll to button and click
            self.driver.execute_script("arguments[0].scrollIntoView(true);", login_button)
            time.sleep(0.5)
            login_button.click()
            
            logger.info("✓ Login button clicked")
            logger.info("")
            logger.info("=" * 60)
            logger.info("📧 OTP/Verification Required")
            logger.info("=" * 60)
            logger.info(f"⏱️  You have {otp_timeout} seconds to:")
            logger.info("  1. Check your Gmail for the OTP code")
            logger.info("  2. Enter the OTP in the browser")
            logger.info("  3. Complete any other verification steps")
            logger.info("")
            logger.info("💡 The script will auto-detect when you're logged in")
            logger.info("=" * 60)
            
            # Wait for OTP completion and authentication
            start_time = time.time()
            check_interval = 3  # Check every 3 seconds
            
            while time.time() - start_time < otp_timeout:
                # Check if authenticated via cookie
                try:
                    is_logged_in = bool(self.driver.execute_script(
                        '''return document.cookie.includes('logged_in')'''
                    ))
                    
                    if is_logged_in:
                        logger.info("")
                        logger.info("=" * 60)
                        logger.info("✓ OTP verification successful! You're now logged in")
                        logger.info("=" * 60)
                        self.save_cookies()
                        time.sleep(1)
                        return True
                except Exception as e:
                    logger.debug(f"Cookie check error: {e}")
                
                # Show countdown
                time.sleep(check_interval)
                remaining = int(otp_timeout - (time.time() - start_time))
                if remaining % 15 == 0 and remaining > 0:  # Every 15 seconds
                    logger.info(f"⏱️  Waiting for OTP verification... {remaining}s remaining")
            
            logger.error("✗ OTP verification timeout")
            return False
                
        except Exception as e:
            logger.error(f"✗ Login error: {e}")
            # Save screenshot on error
            try:
                error_screenshot = Config.OUTPUT_DIR / "login_error.png"
                self.driver.save_screenshot(str(error_screenshot))
                logger.debug(f"Error screenshot saved to {error_screenshot}")
            except:
                pass
            return False
    
    def manual_login(self, timeout: int = 180) -> bool:
        """Allow user to manually login in the browser (RECOMMENDED METHOD)"""
        try:
            logger.info("=" * 60)
            logger.info("MANUAL LOGIN MODE (Recommended)")
            logger.info("=" * 60)
            logger.info(f"Opening Educative... You have {timeout} seconds to login")
            logger.info("")
            logger.info("📋 Instructions:")
            logger.info("  1. The browser will open to Educative.io")
            logger.info("  2. Login using ANY method you prefer:")
            logger.info("     - Click 'Continue with Google'")
            logger.info("     - Use email/password")
            logger.info("     - Complete 2FA/verification if needed")
            logger.info("  3. Wait until you see the Educative homepage")
            logger.info("  4. The script will auto-detect when you're logged in")
            logger.info("")
            logger.info("⏱️  Don't close the browser - it will continue automatically!")
            logger.info("=" * 60)
            
            # Navigate to Educative explore page
            self.driver.get("https://www.educative.io/explore")
            time.sleep(3)
            
            # Wait for user to complete login
            start_time = time.time()
            check_interval = 3  # Check every 3 seconds
            
            while time.time() - start_time < timeout:
                # Check if authenticated via cookie
                try:
                    is_logged_in = bool(self.driver.execute_script(
                        '''return document.cookie.includes('logged_in')'''
                    ))
                    
                    if is_logged_in:
                        logger.info("")
                        logger.info("=" * 60)
                        logger.info("✓ Login detected! You're now authenticated")
                        logger.info("=" * 60)
                        self.save_cookies()
                        time.sleep(1)
                        return True
                except Exception as e:
                    logger.debug(f"Cookie check error: {e}")
                
                # Show countdown
                time.sleep(check_interval)
                remaining = int(timeout - (time.time() - start_time))
                if remaining % 15 == 0 and remaining > 0:  # Every 15 seconds
                    logger.info(f"⏱️  Waiting for login... {remaining}s remaining")
            
            logger.error("✗ Login timeout - please try again")
            return False
            
        except Exception as e:
            logger.error(f"✗ Manual login error: {e}")
            return False
    
    def authenticate(self, email: Optional[str] = None, password: Optional[str] = None, use_google: bool = False, manual: bool = False) -> bool:
        """Main authentication flow - Auto-fills credentials from .env, waits for OTP"""
        logger.info("=" * 60)
        logger.info("Starting Authentication")
        logger.info("=" * 60)
        
        # Try loading saved cookies first (from previous session)
        if self.load_cookies():
            self.driver.get("https://www.educative.io/explore")
            time.sleep(2)
            if self.is_authenticated():
                logger.info("✓ Using saved session - already authenticated!")
                return True
            logger.info("Saved cookies expired, need to re-authenticate")
        
        # Manual login mode - completely manual
        if manual:
            return self.manual_login()
        
        # Use provided credentials or from environment (.env file)
        email = email or Config.EMAIL
        password = password or Config.PASSWORD
        
        # If credentials provided, use automatic login with OTP support
        if email and password:
            logger.info("📧 Using credentials from .env file")
            logger.info("Will auto-fill email/password and wait for OTP...")
            logger.info("")
            
            # Use login with OTP support (fills form, waits for OTP)
            if self.login_with_otp_support(email, password):
                return True
            
            # If OTP login fails, fall back to manual
            logger.warning("✗ Automatic login with OTP failed")
            logger.info("💡 Switching to fully manual login mode...")
            logger.info("")
            return self.manual_login()
        
        # If no credentials provided, use manual login
        logger.info("⚠ No credentials found in .env file")
        logger.info("💡 Tip: Manual login works with Google OAuth, 2FA, and any login method!")
        logger.info("")
        return self.manual_login()

# ==================== Chrome Driver Setup ====================

class ChromeDriverSetup:
    """Handles Chrome WebDriver configuration"""
    
    @staticmethod
    def get_driver() -> webdriver.Chrome:
        """Create and configure Chrome WebDriver with optimized settings for speed"""
        logger.info("Initializing Chrome WebDriver...")
        
        chrome_options = Options()
        
        if Config.HEADLESS:
            chrome_options.add_argument('--headless=new')
            logger.info("Running in headless mode")
        
        # Essential Chrome arguments
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument(f'--window-size={Config.WINDOW_SIZE}')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        
        # Performance optimizations for faster page loads
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--disable-plugins')
        chrome_options.add_argument('--disable-images')  # Don't load images (faster, but loses images in PDF)
        chrome_options.add_argument('--blink-settings=imagesEnabled=true')  # Re-enable for PDF quality
        chrome_options.add_argument('--disk-cache-size=0')  # Disable disk cache
        chrome_options.add_argument('--aggressive-cache-discard')
        
        # User data directory for session persistence (KEY FEATURE!)
        user_data_dir = str(Config.USER_DATA_DIR.absolute())
        Config.USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        chrome_options.add_argument(f'--user-data-dir={user_data_dir}')
        logger.info(f"Using profile directory: {user_data_dir}")
        
        # User agent to avoid detection
        chrome_options.add_argument(
            'user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )
        
        # Disable notifications and other annoyances
        chrome_options.add_argument('--disable-notifications')
        chrome_options.add_argument('--disable-popup-blocking')
        chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Preferences for faster loads
        prefs = {
            'profile.managed_default_content_settings.images': 1,  # Allow images
            'profile.default_content_setting_values.notifications': 2,  # Block notifications
            'profile.managed_default_content_settings.stylesheets': 1,  # Allow CSS
            'profile.managed_default_content_settings.javascript': 1,  # Allow JS
        }
        chrome_options.add_experimental_option('prefs', prefs)
        
        # Get ChromeDriver
        if WEBDRIVER_MANAGER_AVAILABLE:
            logger.info("Using webdriver-manager for ChromeDriver")
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
        else:
            logger.info("Using system ChromeDriver")
            driver = webdriver.Chrome(options=chrome_options)
        
        # Reduced page load timeout for faster failures
        driver.set_page_load_timeout(15)  # Reduced from 30s to 15s
        
        # Enable CDP commands for PDF generation
        driver.command_executor._commands["send_command"] = ("POST", '/session/$sessionId/chromium/send_command')
        
        logger.info("✓ Chrome WebDriver initialized with optimized settings")

        
        return driver

# ==================== Lesson Downloader ====================

class LessonDownloader:
    """Downloads individual lessons as PDFs"""
    
    def __init__(self, driver, course_url: str = None):
        """
        Initialize downloader
        Args:
            driver: Selenium WebDriver instance
            course_url: Main course URL (e.g., https://www.educative.io/courses/agentic-ai-systems)
        """
        self.driver = driver
        self.wait = WebDriverWait(driver, Config.WAIT_TIMEOUT)
        self.course_url = course_url
        self.lesson_urls = []
    
    def extract_lesson_urls_from_course(self) -> List[str]:
        """
        Dynamically extract all lesson URLs from the course table of contents
        Returns list of lesson URLs
        """
        if not self.course_url:
            logger.error("No course URL provided")
            return []
        
        try:
            logger.info(f"Extracting lesson URLs from: {self.course_url}")
            self.driver.get(self.course_url)
            
            # Wait for page to load
            time.sleep(2)
            
            # Try multiple selectors for lesson links
            lesson_links = []
            
            # Method 1: Look for links in table of contents / sidebar
            selectors_to_try = [
                "a[href*='/courses/'][href*='/']",  # Course lesson links
                ".toc a[href*='/courses/']",  # Table of contents links
                "[class*='lesson'] a[href*='/courses/']",  # Lesson container links
                "[class*='curriculum'] a[href*='/courses/']",  # Curriculum links
                "nav a[href*='/courses/']",  # Navigation links
            ]
            
            for selector in selectors_to_try:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        logger.info(f"Found {len(elements)} links using selector: {selector}")
                        for elem in elements:
                            href = elem.get_attribute('href')
                            if href and '/courses/' in href and href not in lesson_links:
                                # Filter out non-lesson links (home, profile, etc.)
                                if not any(x in href for x in ['/profile', '/login', '/signup', '#']):
                                    lesson_links.append(href)
                        if lesson_links:
                            break
                except Exception as e:
                    logger.debug(f"Selector {selector} failed: {e}")
                    continue
            
            # Remove duplicates while preserving order
            seen = set()
            unique_lessons = []
            for url in lesson_links:
                if url not in seen:
                    seen.add(url)
                    unique_lessons.append(url)
            
            # Filter to only include lesson pages (not main course page)
            course_base = self.course_url.rstrip('/')
            filtered_lessons = [
                url for url in unique_lessons 
                if url.startswith(course_base) and url != course_base and url != course_base + '/'
            ]
            
            logger.info(f"✓ Extracted {len(filtered_lessons)} lesson URLs")
            self.lesson_urls = filtered_lessons
            return filtered_lessons
            
        except Exception as e:
            logger.error(f"Failed to extract lesson URLs: {e}")
            return []
    
    def extract_lesson_content(self, url: str) -> Optional[str]:
        """Extract text content from a lesson page"""
        try:
            logger.info(f"Loading lesson: {url}")
            self.driver.get(url)
            time.sleep(3)
            
            # Wait for page to load - try multiple selectors
            content = None
            content_selectors = [
                (By.CLASS_NAME, "lesson-content"),
                (By.CSS_SELECTOR, "[class*='lesson']"),
                (By.CSS_SELECTOR, "[class*='content']"),
                (By.CSS_SELECTOR, "article"),
                (By.CSS_SELECTOR, "main"),
                (By.TAG_NAME, "body"),
            ]
            
            for by, selector in content_selectors:
                try:
                    content = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((by, selector))
                    )
                    logger.debug(f"Found content using: {by}='{selector}'")
                    break
                except Exception as e:
                    logger.debug(f"Selector {by}='{selector}' failed: {e}")
                    continue
            
            if not content:
                logger.warning(f"Could not find content container, using full page")
                content = self.driver.find_element(By.TAG_NAME, "body")
            
            # Extract title - try multiple methods
            title = None
            try:
                title = self.driver.find_element(By.TAG_NAME, "h1").text
            except:
                pass
            
            if not title or len(title.strip()) == 0:
                try:
                    title = self.driver.find_element(By.CSS_SELECTOR, "[class*='title']").text
                except:
                    pass
            
            if not title or len(title.strip()) == 0:
                title = url.split("/")[-1].replace("-", " ").title()
            
            # Extract all text content
            text_content = content.text
            
            if not text_content or len(text_content.strip()) < 50:
                logger.warning(f"Content seems empty, trying alternative extraction")
                # Try getting all paragraphs
                paragraphs = self.driver.find_elements(By.TAG_NAME, "p")
                text_content = "\n\n".join([p.text for p in paragraphs if p.text.strip()])
            
            logger.info(f"✓ Extracted content from: {title} ({len(text_content)} chars)")
            return f"\n{'='*80}\n{title}\n{'='*80}\n\n{text_content}\n\n"
            
        except Exception as e:
            logger.error(f"✗ Failed to extract content from {url}: {e}")
            # Try to save a screenshot for debugging
            try:
                screenshot_path = Config.OUTPUT_DIR / f"error_lesson_{url.split('/')[-1]}.png"
                self.driver.save_screenshot(str(screenshot_path))
                logger.debug(f"Error screenshot saved to {screenshot_path}")
            except:
                pass
            return None
    
    def download_lesson_as_pdf(self, url: str, lesson_number: int) -> Optional[Path]:
        """Download a single lesson as PDF using optimized Chrome print"""
        try:
            logger.info(f"[{lesson_number}] Downloading: {url}")
            
            # Navigate to page
            self.driver.get(url)
            
            # Optimized wait: use explicit wait for content, not fixed sleep
            try:
                # Wait for any content container to be present (max 10s)
                WebDriverWait(self.driver, 10).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
                # Small additional wait for dynamic content (reduced from 1.5s to 0.5s)
                time.sleep(0.5)
            except:
                logger.warning(f"[{lesson_number}] Timeout waiting for page, continuing anyway")
            
            # Get lesson title for filename
            title = None
            try:
                title = self.driver.find_element(By.TAG_NAME, "h1").text
            except:
                pass
            
            if title:
                # Sanitize filename
                filename = f"lesson_{lesson_number:02d}_{title[:50]}.pdf"
                filename = "".join(c for c in filename if c.isalnum() or c in (' ', '_', '-')).rstrip()
                filename = filename.replace(" ", "_") + ".pdf"
            else:
                filename = f"lesson_{lesson_number:02d}.pdf"
            
            filepath = Config.PDF_DIR / filename
            
            # Optimized PDF settings for faster generation and better quality
            print_options = {
                'paperWidth': 8.5,  # Letter width in inches
                'paperHeight': 11,  # Letter height in inches
                'printBackground': True,  # Include backgrounds and colors
                'marginTop': 0.4,
                'marginBottom': 0.4,
                'marginLeft': 0.4,
                'marginRight': 0.4,
                'scale': 0.95,  # Slightly smaller to fit more content
                'preferCSSPageSize': False,
                'displayHeaderFooter': False,  # Faster without headers/footers
            }
            
            # Generate PDF using Chrome DevTools Protocol
            result = self.driver.execute_cdp_cmd('Page.printToPDF', print_options)
            
            # Decode and save
            import base64
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(result['data']))
            
            logger.info(f"✓ [{lesson_number}] Saved: {filename}")
            return filepath
            
        except Exception as e:
            logger.error(f"✗ [{lesson_number}] Failed: {e}")
            return None
    
    def download_all_lessons_text_parallel(self) -> Optional[Path]:
        """Download all lessons using single browser with coordinated parallel extraction"""
        logger.info("=" * 60)
        logger.info(f"Starting Fast Sequential Download (single browser)")
        logger.info("=" * 60)
        logger.info("💡 Using same browser, navigating quickly between lessons")
        
        # Get lesson URLs
        if not self.lesson_urls:
            logger.error("No lesson URLs available. Call extract_lesson_urls_from_course() first.")
            return None
        
        all_content = []
        all_content.append(f"COURSE CONTENT\n")
        all_content.append(f"Downloaded: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        all_content.append(f"{'='*80}\n\n")
        
        # Download lessons sequentially (but faster with reduced delays)
        for i, url in enumerate(self.lesson_urls, 1):
            content = self.extract_lesson_content(url)
            if content:
                all_content.append(content)
            
            # Shorter delay since we're using same authenticated browser
            time.sleep(0.1)  # Reduced from 0.3s
            
            if i % 5 == 0 or i == len(self.lesson_urls):
                logger.info(f"Progress: {i}/{len(self.lesson_urls)} lessons downloaded")
        
        # Save to file
        output_file = Config.OUTPUT_DIR / f"course_content_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.writelines(all_content)
        
        logger.info(f"✓ Course content saved to: {output_file}")
        return output_file
    
    def download_all_lessons_text(self) -> Optional[Path]:
        """Download all lessons as a single text file (sequential)"""
        logger.info("=" * 60)
        logger.info("Starting Text Download (Sequential)")
        logger.info("=" * 60)
        
        # Get lesson URLs
        if not self.lesson_urls:
            logger.error("No lesson URLs available. Call extract_lesson_urls_from_course() first.")
            return None
        
        all_content = []
        all_content.append(f"COURSE CONTENT\n")
        all_content.append(f"Downloaded: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        all_content.append(f"{'='*80}\n\n")
        
        for i, url in enumerate(self.lesson_urls, 1):
            content = self.extract_lesson_content(url)
            if content:
                all_content.append(content)
            time.sleep(0.1)  # Reduced delay
            
            if i % 5 == 0 or i == len(self.lesson_urls):
                logger.info(f"Progress: {i}/{len(self.lesson_urls)} lessons downloaded")
        
        # Save to file
        output_file = Config.OUTPUT_DIR / f"course_content_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.writelines(all_content)
        
        logger.info(f"✓ Course content saved to: {output_file}")
        return output_file
    
    def download_all_lessons_pdf(self) -> List[Path]:
        """Download all lessons as individual PDFs - optimized for speed"""
        logger.info("=" * 60)
        logger.info("Starting Optimized PDF Download")
        logger.info("=" * 60)
        
        # Get lesson URLs
        if not self.lesson_urls:
            logger.error("No lesson URLs available. Call extract_lesson_urls_from_course() first.")
            return []
        
        pdf_files = []
        total = len(self.lesson_urls)
        
        logger.info(f"Downloading {total} lessons...")
        
        for i, url in enumerate(self.lesson_urls, 1):
            pdf_path = self.download_lesson_as_pdf(url, i)
            if pdf_path:
                pdf_files.append(pdf_path)
            
            # Minimal delay - no need to wait, browser handles rate limiting
            # Only add tiny delay to avoid overwhelming the server
            if i < total:  # Don't wait after last lesson
                time.sleep(0.1)  # Reduced from 0.3s to 0.1s
            
            # Progress indicator
            if i % 5 == 0 or i == total:
                logger.info(f"Progress: {i}/{total} lessons ({(i/total)*100:.1f}%)")
        
        logger.info(f"✓ Successfully downloaded {len(pdf_files)}/{total} PDFs")
        return pdf_files
    
    def merge_pdfs(self, pdf_files: List[Path]) -> Optional[Path]:
        """Merge all PDFs into a single file"""
        if not pdf_files:
            logger.warning("No PDFs to merge")
            return None
        
        try:
            logger.info(f"Merging {len(pdf_files)} PDFs...")
            
            merger = PdfMerger()
            
            for pdf_file in sorted(pdf_files):
                merger.append(str(pdf_file))
            
            output_file = Config.OUTPUT_DIR / f"course_complete_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            merger.write(str(output_file))
            merger.close()
            
            logger.info(f"✓ Merged PDF saved to: {output_file}")
            return output_file
            
        except Exception as e:
            logger.error(f"✗ Failed to merge PDFs: {e}")
            return None

# ==================== Main Application ====================

class EducativeCourseDownloader:
    """Main application orchestrator"""
    
    def __init__(self, course_url: str = None):
        """
        Initialize downloader
        Args:
            course_url: URL of the course (e.g., https://www.educative.io/courses/agentic-ai-systems)
        """
        self.driver = None
        self.auth_handler = None
        self.downloader = None
        self.course_url = course_url
    
    def setup(self):
        """Initialize components"""
        logger.info("=" * 60)
        logger.info("Educative Course Downloader")
        logger.info("=" * 60)
        
        if self.course_url:
            logger.info(f"Course URL: {self.course_url}")
        
        Config.setup()
        
        # Setup Chrome driver
        self.driver = ChromeDriverSetup.get_driver()
        
        # Setup handlers
        self.auth_handler = AuthenticationHandler(self.driver)
        self.downloader = LessonDownloader(self.driver, self.course_url)
    
    def cleanup(self):
        """Cleanup resources"""
        if self.driver:
            logger.info("Closing browser...")
            self.driver.quit()
    
    def run(self, download_format: str = "text", use_google_login: bool = True, manual_login: bool = False, parallel: bool = True):
        """Main execution flow"""
        try:
            self.setup()
            
            # Authenticate
            if not self.auth_handler.authenticate(use_google=use_google_login, manual=manual_login):
                logger.error("Authentication failed. Exiting.")
                return False
            
            # Extract lesson URLs from course page
            if self.course_url:
                logger.info("Extracting lesson URLs from course page...")
                lessons = self.downloader.extract_lesson_urls_from_course()
                if not lessons:
                    logger.error("Failed to extract lesson URLs. Check course URL.")
                    return False
                logger.info(f"Found {len(lessons)} lessons to download")
            else:
                logger.error("No course URL provided!")
                return False
            
            # Download content
            if download_format == "text":
                if parallel:
                    self.downloader.download_all_lessons_text_parallel()
                else:
                    self.downloader.download_all_lessons_text()
            elif download_format == "pdf":
                pdf_files = self.downloader.download_all_lessons_pdf()
                self.downloader.merge_pdfs(pdf_files)
            elif download_format == "both":
                if parallel:
                    self.downloader.download_all_lessons_text_parallel()
                else:
                    self.downloader.download_all_lessons_text()
                pdf_files = self.downloader.download_all_lessons_pdf()
                self.downloader.merge_pdfs(pdf_files)
            else:
                logger.error(f"Unknown format: {download_format}")
                return False
            
            logger.info("=" * 60)
            logger.info("✓ Download Complete!")
            logger.info("=" * 60)
            return True
            
        except KeyboardInterrupt:
            logger.warning("\n⚠ Download interrupted by user")
            return False
        except Exception as e:
            logger.error(f"✗ Unexpected error: {e}", exc_info=True)
            return False
        finally:
            self.cleanup()

# ==================== CLI Entry Point ====================

def main():
    """Command-line interface"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Download Educative courses with authentication'
    )
    parser.add_argument(
        '--format',
        choices=['text', 'pdf', 'both'],
        default='text',
        help='Download format (default: text)'
    )
    parser.add_argument(
        '--email',
        help='Educative/Google account email'
    )
    parser.add_argument(
        '--password',
        help='Account password'
    )
    parser.add_argument(
        '--no-google',
        action='store_true',
        help='Skip Google login, use direct Educative login'
    )
    parser.add_argument(
        '--manual',
        action='store_true',
        help='Manual login mode - login yourself in the browser'
    )
    parser.add_argument(
        '--headless',
        action='store_true',
        help='Run browser in headless mode'
    )
    parser.add_argument(
        '--no-parallel',
        action='store_true',
        help='Disable parallel downloads (use sequential)'
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=3,
        help='Number of parallel workers (default: 3)'
    )
    
    args = parser.parse_args()
    
    # Update config with CLI arguments
    if args.email:
        Config.EMAIL = args.email
    if args.password:
        Config.PASSWORD = args.password
    if args.headless:
        Config.HEADLESS = True
    if args.workers:
        Config.MAX_WORKERS = args.workers
    
    # Manual mode cannot be headless
    if args.manual and args.headless:
        logger.warning("Manual mode requires visible browser, disabling headless")
        Config.HEADLESS = False
    
    # Run downloader
    downloader = EducativeCourseDownloader()
    success = downloader.run(
        download_format=args.format,
        use_google_login=not args.no_google,
        manual_login=args.manual,
        parallel=not args.no_parallel
    )
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
