"""
Structured logging configuration
"""
import logging
import logging.handlers
import sys
from pathlib import Path
from datetime import datetime

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    """Get configured logger with both file and console handlers"""
    logger = logging.getLogger(name)
    
    if logger.handlers:  # Already configured
        return logger
    
    logger.setLevel(logging.DEBUG)
    
    # Format: timestamp | level | module | message
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler (INFO and above)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler (DEBUG and above)
    log_file = LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10_000_000,  # 10 MB
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger


# Module loggers
logger_auth = get_logger("auth")
logger_admin = get_logger("admin")
logger_project = get_logger("project")
logger_blog = get_logger("blog")
logger_upload = get_logger("upload")
logger_db = get_logger("database")
logger_contact = get_logger("contact")
logger_lead = get_logger("lead")
logger_requirement = get_logger("requirement")
logger_quotation = get_logger("quotation")
logger_timeline = get_logger("timeline")
logger_discussion = get_logger("discussion")
logger_deliverables = get_logger("deliverables")
logger_activity = get_logger("activity")
logger_notification = get_logger("notification")
logger_portfolio = get_logger("portfolio")
logger_website = get_logger("website")
logger_invoice = get_logger("invoice")
