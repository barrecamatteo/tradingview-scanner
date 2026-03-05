"""
Browser automation: Selenium setup and TradingView authentication.
"""

import os
import json
import time
import logging
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)

COOKIES_PATH = Path(__file__).parent.parent.parent / "data" / "tv_cookies.json"


class TradingViewBrowser:
    """Manages Selenium browser instance with TradingView authentication."""

    def __init__(self, headless: bool = True, download_dir: str = None):
        self.headless = headless
        self.driver = None
        self._download_dir = download_dir
        self._setup_driver()

    def _setup_driver(self):
        """Initialize Chrome WebDriver with optimized settings."""
        options = Options()

        if self.headless:
            options.add_argument("--headless=new")

        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-popup-blocking")

        # Prevent detection
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # Set download directory for CSV extraction
        if self._download_dir:
            os.makedirs(self._download_dir, exist_ok=True)
            prefs = {
                "download.default_directory": self._download_dir,
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "safebrowsing.enabled": True,
            }
            options.add_experimental_option("prefs", prefs)
            logger.info(f"Chrome download directory set to: {self._download_dir}")

        # Persistent user data dir to maintain sessions
        user_data_dir = Path(__file__).parent.parent.parent / "data" / "chrome_profile"
        user_data_dir.mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={user_data_dir}")

        try:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
        except Exception:
            # Fallback: try system chromedriver
            self.driver = webdriver.Chrome(options=options)

        self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
        )

        # Enable file downloads in headless mode
        if self._download_dir:
            abs_download_dir = os.path.abspath(self._download_dir)
            os.makedirs(abs_download_dir, exist_ok=True)

            # Try multiple CDP commands for different Chrome versions
            try:
                self.driver.execute_cdp_cmd(
                    "Browser.setDownloadBehavior",
                    {"behavior": "allow", "downloadPath": abs_download_dir, "eventsEnabled": True},
                )
                logger.info(f"Download enabled (Browser.setDownloadBehavior): {abs_download_dir}")
            except Exception:
                try:
                    self.driver.execute_cdp_cmd(
                        "Page.setDownloadBehavior",
                        {"behavior": "allow", "downloadPath": abs_download_dir},
                    )
                    logger.info(f"Download enabled (Page.setDownloadBehavior): {abs_download_dir}")
                except Exception as e:
                    logger.warning(f"Could not set download behavior: {e}")

            self._abs_download_dir = abs_download_dir

        self.driver.set_page_load_timeout(90)
        logger.info("Chrome WebDriver initialized")

    def login(self, username: str = None, password: str = None) -> bool:
        """
        Login to TradingView.
        Always restores cookies first (most reliable for GitHub Actions),
        then verifies on a chart page.
        """
        username = username or os.getenv("TV_USERNAME")
        password = password or os.getenv("TV_PASSWORD")

        # Always try cookie restoration first (don't trust cached profile)
        if self._restore_cookies():
            # Verify by loading a chart page (not just homepage)
            if self._verify_chart_access():
                logger.info("Logged in via restored cookies")
                return True
            else:
                logger.warning("Cookies restored but chart access failed")

        # Check if maybe already logged in via profile
        if self._verify_chart_access():
            logger.info("Already logged in via persistent session")
            return True

        # Credential-based login
        if not username or not password:
            logger.error("No credentials provided and no active session")
            return False

        return self._login_with_credentials(username, password)

    def _verify_chart_access(self) -> bool:
        """Verify login by loading a chart page and checking for Premium features."""
        try:
            self.driver.get("https://www.tradingview.com/chart/")
            time.sleep(5)

            page_source = self.driver.page_source.lower()

            # Check for unauthenticated / Basic plan indicators
            if "can't open this chart layout" in page_source:
                logger.info("Chart access denied - not logged in")
                return False
            if "upgrade your plan" in page_source:
                logger.info("Chart shows upgrade prompt - session may be Basic")
                return False

            # Check for chart canvas (indicates chart loaded successfully)
            try:
                self.driver.find_element(By.CSS_SELECTOR, "canvas")
                logger.info("Chart loaded successfully - session valid")
                return True
            except NoSuchElementException:
                pass

            # Fallback: check for user menu
            try:
                self.driver.find_element(
                    By.CSS_SELECTOR, "[data-name='header-user-menu-button']"
                )
                return True
            except NoSuchElementException:
                pass

            return False
        except Exception as e:
            logger.warning(f"Error verifying chart access: {e}")
            return False

    def _login_with_credentials(self, username: str, password: str) -> bool:
        """Perform credential-based login to TradingView."""
        try:
            logger.info("Attempting credential-based login...")
            self.driver.get("https://www.tradingview.com/#signin")
            time.sleep(3)

            # Click "Email" sign-in option
            wait = WebDriverWait(self.driver, 10)

            # Look for email sign-in button
            email_buttons = self.driver.find_elements(
                By.XPATH,
                "//*[contains(text(), 'Email') or contains(text(), 'email')]"
            )
            for btn in email_buttons:
                try:
                    btn.click()
                    time.sleep(1)
                    break
                except Exception:
                    continue

            # Enter username
            username_field = wait.until(
                EC.presence_of_element_located((By.NAME, "id_username"))
            )
            username_field.clear()
            username_field.send_keys(username)

            # Enter password
            password_field = self.driver.find_element(By.NAME, "id_password")
            password_field.clear()
            password_field.send_keys(password)

            # Click sign in
            sign_in_btn = self.driver.find_element(
                By.CSS_SELECTOR, "button[type='submit']"
            )
            sign_in_btn.click()

            time.sleep(5)

            # Check for 2FA prompt
            if self._handle_2fa():
                logger.info("2FA handled")

            # Verify login
            if self._is_logged_in():
                self._save_cookies()
                logger.info("Login successful")
                return True
            else:
                logger.error("Login failed - could not verify session")
                return False

        except TimeoutException:
            logger.error("Login timed out")
            return False
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False

    def _handle_2fa(self) -> bool:
        """
        Handle 2FA if prompted.
        Returns True if 2FA was detected (user must handle manually in non-headless mode).
        """
        try:
            # Check if 2FA input is present
            tfa_input = self.driver.find_elements(
                By.CSS_SELECTOR, "input[name='code'], input[placeholder*='code']"
            )
            if tfa_input:
                logger.warning(
                    "2FA detected! If running headless, you'll need to handle this manually. "
                    "Consider running with headless=False for first login."
                )
                # In non-headless mode, wait for user to enter code
                if not self.headless:
                    input("Press Enter after completing 2FA in the browser...")
                    return True
                return False
            return False
        except Exception:
            return False

    def _save_cookies(self):
        """Save browser cookies for session persistence."""
        try:
            COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
            cookies = self.driver.get_cookies()
            with open(COOKIES_PATH, "w") as f:
                json.dump(cookies, f)
            logger.info(f"Cookies saved to {COOKIES_PATH}")
        except Exception as e:
            logger.warning(f"Failed to save cookies: {e}")

    def _restore_cookies(self) -> bool:
        """Restore cookies from file with detailed logging."""
        try:
            if not COOKIES_PATH.exists():
                logger.info(f"No cookies file at {COOKIES_PATH}")
                return False

            logger.info(f"Loading cookies from {COOKIES_PATH}")

            self.driver.get("https://www.tradingview.com/")
            time.sleep(2)

            with open(COOKIES_PATH, "r") as f:
                cookies = json.load(f)

            logger.info(f"Found {len(cookies)} cookies to restore")

            restored = 0
            for cookie in cookies:
                try:
                    # Remove problematic fields
                    cookie.pop("sameSite", None)
                    cookie.pop("expiry", None)
                    self.driver.add_cookie(cookie)
                    restored += 1
                except Exception:
                    continue

            logger.info(f"Restored {restored}/{len(cookies)} cookies")

            # Refresh to apply cookies
            logger.info("Cookies restored - checking session...")
            self.driver.refresh()
            time.sleep(5)
            return True
        except Exception as e:
            logger.warning(f"Failed to restore cookies: {e}")
            return False

    def get_driver(self):
        """Return the Selenium WebDriver instance."""
        return self.driver

    def close(self):
        """Close the browser."""
        if self.driver:
            try:
                self._save_cookies()
            except Exception:
                pass
            self.driver.quit()
            logger.info("Browser closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
