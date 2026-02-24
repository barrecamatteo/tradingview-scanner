#!/usr/bin/env python3
"""
CLI runner for TradingView Continuation Rate Scanner.
Used by GitHub Actions or cron jobs.
"""

import os
import sys
import logging
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.scanner import TradingViewScanner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    extraction_method = os.getenv("EXTRACTION_METHOD", "ocr")

    logger.info("=" * 60)
    logger.info("TradingView Continuation Rate Scanner")
    logger.info(f"Extraction method: {extraction_method}")
    logger.info("=" * 60)

    scanner = TradingViewScanner(
        headless=True,
        extraction_method=extraction_method,
        use_database=True,
    )

    def progress(current, total, message):
        logger.info(f"[{current}/{total}] {message}")

    scanner.set_progress_callback(progress)

    try:
        results = scanner.run_full_scan()

        # Summary
        success = sum(1 for r in results if r.status == "success" and r.cont_rate is not None)
        failed = len(results) - success

        logger.info("=" * 60)
        logger.info(f"SCAN COMPLETE: {success} successful, {failed} failed")
        logger.info("=" * 60)

        # Print pivot table
        pivot = scanner.get_results_as_pivot()
        logger.info(f"{'Asset':<12} {'Category':<22} {'4H':>8} {'1H':>8} {'15min':>8} {'Avg':>8}")
        logger.info("-" * 70)
        for row in pivot:
            logger.info(
                f"{row['asset']:<12} {row['category']:<22} "
                f"{row.get('4H', '—'):>7}% {row.get('1H', '—'):>7}% "
                f"{row.get('15min', '—'):>7}% {row.get('avg', '—'):>7}%"
            )

        if failed > 0:
            sys.exit(1)  # Signal partial failure to CI

    except Exception as e:
        logger.exception(f"Scan failed: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
