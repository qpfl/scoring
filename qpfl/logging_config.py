"""Centralized logging configuration for QPFL autoscorer."""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


def setup_logging(
    log_dir: Optional[Path] = None,
    level: int = logging.INFO,
    log_to_file: bool = True,
    log_to_console: bool = True,
) -> logging.Logger:
    """
    Configure logging for the application.

    Creates both file and console handlers with appropriate formatting.

    Args:
        log_dir: Directory for log files (default: ./logs)
        level: Logging level (default: INFO)
        log_to_file: Whether to log to file (default: True)
        log_to_console: Whether to log to console (default: True)

    Returns:
        Configured logger instance

    Example:
        from qpfl.logging_config import setup_logging
        logger = setup_logging()
        logger.info("Starting scoring process")
    """
    # Create logger
    logger = logging.getLogger('qpfl')
    logger.setLevel(level)

    # Clear any existing handlers
    logger.handlers = []

    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    simple_formatter = logging.Formatter('%(levelname)s: %(message)s')

    # File handler
    if log_to_file:
        if log_dir is None:
            log_dir = Path('logs')
        log_dir.mkdir(exist_ok=True)

        # Create log file with timestamp
        log_file = log_dir / f'qpfl_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(detailed_formatter)
        logger.addHandler(file_handler)

    # Console handler
    if log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(simple_formatter)
        logger.addHandler(console_handler)

    return logger


def get_logger(name: str = 'qpfl') -> logging.Logger:
    """
    Get a logger instance.

    If setup_logging() hasn't been called, returns a basic logger.

    Args:
        name: Logger name (default: 'qpfl')

    Returns:
        Logger instance
    """
    return logging.getLogger(name)
