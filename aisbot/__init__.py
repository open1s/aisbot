"""
aisbot - A lightweight AI agent framework
"""

import os

__version__ = "0.1.0"
__logo__ = "🐈"

# Configure loguru with AISBOT_LOG environment variable
if os.getenv("AISBOT_LOG"):
    from loguru import logger
    import sys

    log_level = os.getenv("AISBOT_LOG", "INFO").upper()
    logger.remove()
    logger.add(sys.stderr, level=log_level)
