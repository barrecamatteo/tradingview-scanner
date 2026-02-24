"""
Extractor: Screenshot capture and OCR/AI Vision extraction of Cont. Rate values.
"""

import re
import os
import io
import base64
import logging
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageEnhance, ImageFilter

logger = logging.getLogger(__name__)

# Directory for debug screenshots
DEBUG_DIR = Path(__file__).parent.parent.parent / "data" / "screenshots"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)


class ContRateExtractor:
    """Extracts Continuation Rate values from TradingView chart screenshots."""

    def __init__(self, method: str = "ocr"):
        self.method = method
        self._ocr_reader = None
        self._init_ocr()

    def _init_ocr(self):
        """Initialize OCR engine."""
        if self.method == "ocr":
            try:
                import easyocr
                self._ocr_reader = easyocr.Reader(["en"], gpu=False)
                logger.info("EasyOCR initialized")
            except ImportError:
                logger.warning("EasyOCR not available, trying pytesseract")
                try:
                    import pytesseract
                    self._ocr_engine = "tesseract"
                    logger.info("Pytesseract initialized")
                except ImportError:
                    logger.error("No OCR engine available.")
                    raise

    def extract_cont_rate(
        self,
        screenshot_bytes: bytes,
        asset_name: str = "",
        timeframe: str = "",
        save_debug: bool = True,
    ) -> Tuple[Optional[float], float]:
        """
        Extract Continuation Rate from a screenshot.

        Returns:
            Tuple of (cont_rate_value, confidence_score)
            cont_rate_value is None if extraction failed
        """
        # Save debug screenshot
        if save_debug:
            debug_path = DEBUG_DIR / f"{asset_name}_{timeframe}.png"
            with open(debug_path, "wb") as f:
                f.write(screenshot_bytes)

        if self.method == "ai_vision":
            return self._extract_with_ai_vision(screenshot_bytes)
        else:
            return self._extract_with_ocr(screenshot_bytes)

    def _crop_right_portion(self, image_bytes: bytes) -> Image.Image:
        """
        Crop only the right ~35% of the screen where the Analysis panel lives.
        This reduces noise from the chart area and speeds up OCR.
        """
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size

        # The Analysis panel is in the top-right area
        crop_x = int(width * 0.62)
        crop_y = 0
        crop_right = width
        crop_bottom = int(height * 0.75)

        cropped = img.crop((crop_x, crop_y, crop_right, crop_bottom))
        return cropped

    def _preprocess_image(self, img: Image.Image) -> Image.Image:
        """
        Preprocess image for better OCR results.
        """
        # Scale up 2x for better OCR
        img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)

        # Increase contrast
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.8)

        # Sharpen
        img = img.filter(ImageFilter.SHARPEN)

        return img

    def _extract_with_ocr(self, screenshot_bytes: bytes) -> Tuple[Optional[float], float]:
        """Extract Cont. Rate using OCR (EasyOCR or Tesseract)."""
        try:
            # First try: crop right portion (where Analysis panel should be)
            cropped = self._crop_right_portion(screenshot_bytes)
            processed = self._preprocess_image(cropped)

            # Save the cropped debug image
            debug_cropped_path = DEBUG_DIR / "_last_cropped.png"
            processed.save(str(debug_cropped_path))

            if self._ocr_reader:
                # EasyOCR
                img_array = self._pil_to_numpy(processed)
                results = self._ocr_reader.readtext(img_array)

                all_text = " ".join([text for _, text, _ in results])
                logger.debug(f"OCR raw text (cropped): {all_text}")

                rate = self._parse_cont_rate(all_text, results)
                if rate[0] is not None:
                    return rate

                # Second try: full page scan
                logger.info("Cropped scan failed, trying full page...")
                full_img = Image.open(io.BytesIO(screenshot_bytes))
                full_processed = self._preprocess_image(full_img)
                full_array = self._pil_to_numpy(full_processed)
                full_results = self._ocr_reader.readtext(full_array)

                full_text = " ".join([text for _, text, _ in full_results])
                logger.debug(f"OCR raw text (full): {full_text}")

                return self._parse_cont_rate(full_text, full_results)
            else:
                # Tesseract fallback
                import pytesseract
                text = pytesseract.image_to_string(processed)
                logger.debug(f"Tesseract raw text: {text}")
                return self._parse_cont_rate(text)

        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            return None, 0.0

    def _extract_with_ai_vision(self, screenshot_bytes: bytes) -> Tuple[Optional[float], float]:
        """Extract Cont. Rate using Claude AI Vision API."""
        try:
            import anthropic

            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                logger.error("ANTHROPIC_API_KEY not set")
                return None, 0.0

            client = anthropic.Anthropic(api_key=api_key)

            b64_image = base64.b64encode(screenshot_bytes).decode("utf-8")

            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=256,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": b64_image,
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    "Look at this TradingView chart screenshot. "
                                    "Find the 'Analysis' panel (usually top-right area). "
                                    "Extract the 'Cont. Rate' value which shows as a percentage. "
                                    "Reply with ONLY the numeric value (e.g., '64.4'). "
                                    "If you cannot find it, reply with 'NOT_FOUND'."
                                ),
                            },
                        ],
                    }
                ],
            )

            response_text = message.content[0].text.strip()
            logger.debug(f"AI Vision response: {response_text}")

            if response_text == "NOT_FOUND":
                return None, 0.0

            try:
                value = float(response_text.replace("%", "").strip())
                if 0 <= value <= 100:
                    return value, 0.95
                else:
                    return None, 0.0
            except ValueError:
                match = re.search(r"(\d{1,3}\.?\d*)", response_text)
                if match:
                    value = float(match.group(1))
                    if 0 <= value <= 100:
                        return value, 0.85
                return None, 0.0

        except Exception as e:
            logger.error(f"AI Vision extraction failed: {e}")
            return None, 0.0

    def _parse_cont_rate(self, text: str, ocr_results=None) -> Tuple[Optional[float], float]:
        """
        Parse Continuation Rate from OCR text output.

        Looks for patterns like:
        - "Cont. Rate: 64.4%"
        - "Cont Rate 64.4"
        - "Cont_ Rate: 67.9%"
        - just "Rate:" near a percentage
        """
        # Clean up OCR artifacts
        text_clean = text.replace("|", "").replace("\\", "").replace("}", "")
        text_clean = text_clean.replace("_", ".").replace("{", "")

        # Pattern matching - from most specific to least
        patterns = [
            # Exact match with various OCR artifacts
            r"Cont\.?\s*\.?\s*Rate\s*:?\s*(\d{1,3}\.?\d*)\s*%?",
            r"Continuation\s*Rate\s*:?\s*(\d{1,3}\.?\d*)\s*%?",
            # OCR might read it with underscores or other artifacts
            r"Cont\s*[\._]?\s*Rate\s*[\.:;]?\s*(\d{1,3}[\.,]\d+)\s*%?",
            # Very loose - just "Rate" followed by a number (as last resort)
            r"(?:Cont|Rate)\s*[\.:;]?\s*(\d{2}\.\d)\s*%",
        ]

        for pattern in patterns:
            match = re.search(pattern, text_clean, re.IGNORECASE)
            if match:
                try:
                    value_str = match.group(1).replace(",", ".")
                    value = float(value_str)
                    if 0 <= value <= 100:
                        confidence = 0.9
                        logger.info(f"Extracted Cont. Rate: {value}% (confidence: {confidence})")
                        return value, confidence
                except ValueError:
                    continue

        # If we have EasyOCR results with positions, try spatial matching
        if ocr_results:
            spatial_result = self._spatial_extraction(ocr_results)
            if spatial_result[0] is not None:
                return spatial_result

        logger.warning(f"Could not extract Cont. Rate from text: {text[:300]}")
        return None, 0.0

    def _spatial_extraction(self, ocr_results) -> Tuple[Optional[float], float]:
        """
        Use spatial positioning of OCR results to find the Cont. Rate value.
        Look for "Cont" or "Rate" text, then find the nearest percentage value.
        """
        # Find the "Cont" or "Rate" label
        cont_box = None
        for bbox, text, conf in ocr_results:
            text_lower = text.lower().strip()
            if "cont" in text_lower and "rate" in text_lower:
                cont_box = bbox
                break
            elif "cont" in text_lower:
                cont_box = bbox
                # Don't break - keep looking for better match

        if cont_box is None:
            # Try finding just "Rate" as fallback
            for bbox, text, conf in ocr_results:
                if "rate" in text.lower().strip() and "extension" not in text.lower():
                    cont_box = bbox
                    break

        if cont_box is None:
            return None, 0.0

        # Find nearest numeric value to the right of the label
        cont_center_y = (cont_box[0][1] + cont_box[2][1]) / 2
        cont_right_x = max(p[0] for p in cont_box)

        best_match = None
        best_distance = float("inf")

        for bbox, text, conf in ocr_results:
            # Clean and try to parse as number
            clean = text.replace("%", "").replace(",", ".").strip()
            try:
                value = float(clean)
                if 0 < value <= 100:
                    text_left_x = min(p[0] for p in bbox)
                    text_center_y = (bbox[0][1] + bbox[2][1]) / 2

                    # Must be to the right or same line
                    y_distance = abs(text_center_y - cont_center_y)
                    x_distance = abs(text_left_x - cont_right_x)

                    distance = (x_distance ** 2 + y_distance ** 2) ** 0.5

                    if distance < best_distance and y_distance < 80:
                        best_distance = distance
                        best_match = (value, max(conf, 0.7))
            except ValueError:
                continue

        if best_match:
            logger.info(f"Spatial extraction found Cont. Rate: {best_match[0]}%")
            return best_match[0], best_match[1]

        return None, 0.0

    @staticmethod
    def _pil_to_numpy(img: Image.Image):
        """Convert PIL Image to numpy array."""
        import numpy as np
        return np.array(img)

    @staticmethod
    def validate_cont_rate(value: Optional[float]) -> bool:
        """Validate that a Cont. Rate value is within expected bounds."""
        if value is None:
            return False
        return 0.0 <= value <= 100.0
