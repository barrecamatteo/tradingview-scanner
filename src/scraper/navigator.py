"""
Chart navigation and DOM-based data extraction from TradingView.
"""

import logging
import time
from typing import Optional, Tuple

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
)

from ..config.assets import TV_CHART_URL, SCRAPER_CONFIG

logger = logging.getLogger(__name__)


class ChartNavigator:
    """Navigates TradingView charts and extracts data from Data Window DOM."""

    def __init__(self, driver):
        self.driver = driver
        self._data_window_open = False
        self._current_symbol = None
        self._current_interval = None

    def navigate_to_chart(self, symbol: str, interval: str) -> bool:
        """Navigate to a specific symbol/timeframe chart.

        Returns True if navigation was successful.
        """
        try:
            url = TV_CHART_URL.format(symbol=symbol, interval=interval)

            # If already on the same symbol, just change timeframe
            if self._current_symbol == symbol and self._current_interval != interval:
                # Use TradingView's timeframe selector instead of full page reload
                if self._change_timeframe(interval):
                    self._current_interval = interval
                    time.sleep(2)  # Wait for chart to update
                    return True

            self.driver.get(url)
            self._current_symbol = symbol
            self._current_interval = interval
            self._data_window_open = False  # Reset after navigation

            # Wait for chart to load
            timeout = SCRAPER_CONFIG["page_load_timeout"]
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[class*='chart-container']")
                )
            )

            # Wait for indicators to load
            time.sleep(SCRAPER_CONFIG["indicator_wait_timeout"])
            return True

        except TimeoutException:
            logger.error(f"Timeout loading chart for {symbol}@{interval}")
            return False
        except Exception as e:
            logger.error(f"Navigation error for {symbol}@{interval}: {e}")
            return False

    def _change_timeframe(self, interval: str) -> bool:
        """Change timeframe using URL parameter update."""
        try:
            current_url = self.driver.current_url
            # Replace interval parameter in URL
            import re
            new_url = re.sub(r'interval=\d+', f'interval={interval}', current_url)
            if new_url == current_url:
                new_url = current_url + f"&interval={interval}"
            self.driver.get(new_url)
            time.sleep(3)
            return True
        except Exception as e:
            logger.warning(f"Timeframe change failed: {e}")
            return False

    def dismiss_popups(self):
        """Dismiss any TradingView popups or dialogs."""
        popup_selectors = [
            "[data-role='toast-container'] button",
            "[class*='close']",
            "[class*='dialog'] button[class*='close']",
            "[data-name='go-to-date-dialog'] button[class*='close']",
        ]
        for selector in popup_selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    try:
                        el.click()
                        time.sleep(0.3)
                    except Exception:
                        pass
            except Exception:
                pass

    def open_data_window(self) -> bool:
        """Open the Data Window panel in TradingView.

        The Data Window shows indicator values as DOM elements, making
        extraction fast and 100% accurate (no OCR needed).

        Returns True if Data Window was opened successfully.
        """
        if self._data_window_open:
            return True

        try:
            # Method 1: Click "Data Window" tab if visible
            try:
                data_window_tab = self.driver.find_element(
                    By.XPATH, "//button[contains(text(), 'Data Window')]"
                )
                data_window_tab.click()
                time.sleep(1)
                self._data_window_open = True
                logger.info("Data Window opened via tab click")
                return True
            except NoSuchElementException:
                pass

            # Method 2: Use keyboard shortcut (Alt+D or via right panel)
            try:
                # Look for the right panel toggle buttons
                # The Data Window icon is typically in the right toolbar
                right_panel_buttons = self.driver.find_elements(
                    By.CSS_SELECTOR, "[data-name='right-toolbar'] button"
                )
                for btn in right_panel_buttons:
                    try:
                        title = btn.get_attribute("title") or ""
                        aria = btn.get_attribute("aria-label") or ""
                        data_tooltip = btn.get_attribute("data-tooltip") or ""
                        if any("data window" in t.lower() for t in [title, aria, data_tooltip]):
                            btn.click()
                            time.sleep(1)
                            self._data_window_open = True
                            logger.info("Data Window opened via toolbar button")
                            return True
                    except Exception:
                        continue
            except Exception:
                pass

            # Method 3: Try clicking Object Tree/Data Window area
            try:
                tabs = self.driver.find_elements(
                    By.CSS_SELECTOR, "[class*='tab']"
                )
                for tab in tabs:
                    try:
                        if "data window" in tab.text.lower():
                            tab.click()
                            time.sleep(1)
                            self._data_window_open = True
                            logger.info("Data Window opened via generic tab")
                            return True
                    except Exception:
                        continue
            except Exception:
                pass

            logger.warning("Could not open Data Window automatically")
            return False

        except Exception as e:
            logger.error(f"Error opening Data Window: {e}")
            return False

    def get_cont_rate_from_dom(
        self, max_wait: int = 20, poll_interval: float = 2.0,
        asset_name: str = "", timeframe: str = ""
    ) -> Tuple[Optional[float], float]:
        """Extract Continuation Rate value directly from Data Window DOM.

        Polls the DOM repeatedly until the value appears or timeout is reached.
        TradingView indicators can take 5-15 seconds to populate after chart load.

        Args:
            max_wait: Maximum seconds to wait for the value to appear.
            poll_interval: Seconds between each poll attempt.
            asset_name: For debug screenshot naming.
            timeframe: For debug screenshot naming.

        Returns:
            Tuple of (cont_rate, confidence).
            cont_rate is None if extraction fails.
            confidence is 1.0 for DOM extraction (always accurate).
        """
        import math
        import os
        attempts = math.ceil(max_wait / poll_interval)

        for attempt in range(attempts):
            value_text = self._find_cont_rate_in_dom()

            if value_text:
                cont_rate = self._parse_cont_rate(value_text)
                if cont_rate is not None:
                    logger.info(
                        f"DOM extraction: Continuation Rate = {cont_rate} "
                        f"(found after {attempt * poll_interval:.0f}s)"
                    )
                    return cont_rate, 1.0
                else:
                    logger.warning(
                        f"Found text '{value_text}' but could not parse as number"
                    )
                    return None, 0.0

            if attempt < attempts - 1:
                logger.debug(
                    f"Continuation Rate not in DOM yet, "
                    f"retry {attempt + 1}/{attempts}..."
                )
                time.sleep(poll_interval)

        # Debug: save screenshot and DOM dump on failure
        try:
            debug_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)
                ))),
                "data", "screenshots"
            )
            os.makedirs(debug_dir, exist_ok=True)

            # Save screenshot
            debug_name = f"debug_{asset_name}_{timeframe}".replace(" ", "_")
            screenshot_path = os.path.join(debug_dir, f"{debug_name}.png")
            self.driver.save_screenshot(screenshot_path)
            logger.info(f"Debug screenshot saved: {screenshot_path}")

            # Log current URL
            logger.warning(f"Current URL: {self.driver.current_url}")

            # Log what's visible in Data Window area
            try:
                # Find all data-test-id="value-title" elements
                titles = self.driver.find_elements(
                    By.CSS_SELECTOR, "[data-test-id*='value-title']"
                )
                if titles:
                    logger.info(
                        f"Data Window titles found: "
                        f"{[t.text for t in titles[:10]]}"
                    )
                else:
                    logger.warning("No data-test-id='value-title' elements found")

                # Also check for any itemTitle elements
                item_titles = self.driver.find_elements(
                    By.CSS_SELECTOR, "[class*='itemTitle']"
                )
                if item_titles:
                    logger.info(
                        f"itemTitle elements: "
                        f"{[t.text for t in item_titles[:10]]}"
                    )
                else:
                    logger.warning("No itemTitle elements found")

            except Exception as debug_err:
                logger.warning(f"Debug DOM inspection failed: {debug_err}")

        except Exception as debug_err:
            logger.warning(f"Could not save debug info: {debug_err}")

        logger.warning(
            f"Could not find Continuation Rate in Data Window DOM "
            f"after {max_wait}s"
        )
        return None, 0.0

    def _find_cont_rate_in_dom(self) -> Optional[str]:
        """Search for Continuation Rate value text in the Data Window DOM.

        Returns the raw text value if found, None otherwise.
        """
        try:
            # Strategy 1: XPath - find label then get sibling value
            # <div class="itemTitle-_gbYDtbd">Continuation Rate</div>
            # <div><span>64.674</span></div>
            try:
                value_span = self.driver.find_element(
                    By.XPATH,
                    "//div[contains(text(), 'Continuation Rate')]"
                    "/following-sibling::div/span"
                )
                text = value_span.text.strip()
                if text:
                    return text
            except NoSuchElementException:
                pass

            # Strategy 2: Try with partial class name match
            try:
                value_span = self.driver.find_element(
                    By.XPATH,
                    "//div[contains(@class, 'itemTitle') and "
                    "contains(text(), 'Continuation Rate')]"
                    "/following-sibling::div/span"
                )
                text = value_span.text.strip()
                if text:
                    return text
            except NoSuchElementException:
                pass

            # Strategy 3: Find via data-test-id attribute
            try:
                titles = self.driver.find_elements(
                    By.CSS_SELECTOR, "[data-test-id*='value-title']"
                )
                for title in titles:
                    if "Continuation Rate" in title.text:
                        parent = title.find_element(By.XPATH, "..")
                        span = parent.find_element(
                            By.CSS_SELECTOR, "div > span"
                        )
                        text = span.text.strip()
                        if text:
                            return text
            except (NoSuchElementException, StaleElementReferenceException):
                pass

            # Strategy 4: Search all item containers
            try:
                items = self.driver.find_elements(
                    By.CSS_SELECTOR, "[class*='item-']"
                )
                for item in items:
                    try:
                        title_div = item.find_element(
                            By.CSS_SELECTOR, "[class*='itemTitle']"
                        )
                        if "Continuation Rate" in title_div.text:
                            span = item.find_element(By.CSS_SELECTOR, "span")
                            text = span.text.strip()
                            if text:
                                return text
                    except NoSuchElementException:
                        continue
            except Exception:
                pass

            return None

        except Exception as e:
            logger.error(f"DOM search error: {e}")
            return None

    def _parse_cont_rate(self, text: str) -> Optional[float]:
        """Parse continuation rate from text string.

        Handles formats like: "64.674", "64.7", "n/a", "∅", etc.
        """
        if not text:
            return None

        # Clean the text
        text = text.strip().replace("%", "").replace(",", ".")

        # Check for non-numeric values
        if text.lower() in ("n/a", "na", "nan", "∅", "—", "-", ""):
            return None

        try:
            value = float(text)
            # Sanity check: Continuation Rate should be 0-100
            if 0 <= value <= 100:
                return round(value, 1)
            else:
                logger.warning(f"Continuation Rate {value} outside 0-100 range")
                return None
        except ValueError:
            logger.warning(f"Cannot parse '{text}' as float")
            return None

    def get_analysis_panel_screenshot(self) -> bytes:
        """Take screenshot of the analysis panel (fallback for OCR).

        Returns PNG bytes of the screenshot.
        """
        try:
            # Hide drawings/overlays for cleaner screenshot
            self._hide_drawings()
            time.sleep(0.5)

            # Try to find the analysis panel element
            panel_selectors = [
                "[class*='analysis']",
                "[class*='rightPanel']",
                "[data-name='legend']",
            ]

            for selector in panel_selectors:
                try:
                    panel = self.driver.find_element(By.CSS_SELECTOR, selector)
                    return panel.screenshot_as_png
                except NoSuchElementException:
                    continue

            # Fallback: full page screenshot
            logger.warning("Could not find analysis panel, taking full screenshot")
            return self.driver.get_screenshot_as_png()

        except Exception as e:
            logger.error(f"Screenshot error: {e}")
            return self.driver.get_screenshot_as_png()
        finally:
            self._show_drawings()

    def _hide_drawings(self):
        """Hide chart drawings for cleaner screenshot."""
        try:
            self.driver.execute_script("""
                document.querySelectorAll('[class*="drawing"]').forEach(el => {
                    el.style.visibility = 'hidden';
                });
            """)
        except Exception:
            pass

    def _show_drawings(self):
        """Restore chart drawings after screenshot."""
        try:
            self.driver.execute_script("""
                document.querySelectorAll('[class*="drawing"]').forEach(el => {
                    el.style.visibility = 'visible';
                });
            """)
        except Exception:
            pass
