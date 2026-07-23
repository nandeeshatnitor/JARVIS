"""
Centralized logging configuration for JARVIS .
All logs go to logs/jarvis.log with rotation, and critical logs also print to console.
Terminal stdout/stderr are also captured to logs/terminal.log
"""

import logging
import logging.handlers
import sys
import io
from core.llm_client import get_base_dir

BASE_DIR = get_base_dir()
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "jarvis.log"
TERMINAL_LOG_FILE = LOG_DIR / "logs.log"


# Custom formatter with timestamp, level, module, and message
class JarvisFormatter(logging.Formatter):
    """Formatter that adds module name and keeps output clean."""

    def format(self, record):
        # Add module name if not present
        if not hasattr(record, 'module_name'):
            record.module_name = record.name.split('.')[-1] if record.name else 'JARVIS'
        return super().format(record)


# Stream redirector to capture stdout/stderr to logger
class StreamToLogger(io.TextIOBase):
    """Redirects stdout/stderr to a logger."""

    def __init__(self, logger: logging.Logger, level: int):
        self.logger = logger
        self.level = level
        self.buffer = ""

    def write(self, s: str) -> int:
        if not s:
            return 0
        self.buffer += s
        # Flush on newlines
        if '\n' in self.buffer:
            lines = self.buffer.split('\n')
            for line in lines[:-1]:
                if line:
                    self.logger.log(self.level, line)
            self.buffer = lines[-1]
        return len(s)

    def flush(self):
        if self.buffer:
            self.logger.log(self.level, self.buffer)
            self.buffer = ""


def setup_logging(level: int = logging.INFO, console: bool = True) -> logging.Logger:
    """
    Configure root logger with file handler (rotating) and optional console handler.
    Also redirects stdout/stderr to terminal.log file.

    Args:
        level: Logging level (default: INFO)
        console: Whether to also log to console (default: True)

    Returns:
        Configured root logger
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Clear existing handlers to avoid duplicates on reconfig
    root.handlers.clear()

    # File handler with rotation (10 MB per file, keep 5 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(level)
    file_fmt = JarvisFormatter(
        fmt='%(asctime)s | %(levelname)-8s | %(module_name)-15s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_fmt)
    root.addHandler(file_handler)

    # Terminal output logger (captures stdout/stderr)
    terminal_handler = logging.handlers.RotatingFileHandler(
        TERMINAL_LOG_FILE,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    terminal_fmt = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    terminal_handler.setFormatter(terminal_fmt)

    terminal_logger = logging.getLogger('jarvis.terminal')
    terminal_logger.setLevel(logging.DEBUG)
    terminal_logger.addHandler(terminal_handler)
    terminal_logger.propagate = False

    # Redirect stdout and stderr to terminal logger
    sys.stdout = StreamToLogger(terminal_logger, logging.INFO)
    sys.stderr = StreamToLogger(terminal_logger, logging.ERROR)

    # Console handler (optional, for critical errors and above)
    if console:
        # Use the REAL stdout for console output (not our redirected one)
        console_handler = logging.StreamHandler(sys.__stdout__)
        console_handler.setLevel(logging.WARNING)  # Only WARNING+ to console
        console_fmt = JarvisFormatter(
            fmt='%(asctime)s | %(levelname)-8s | %(module_name)-15s | %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(console_fmt)
        root.addHandler(console_handler)

    # Prevent propagation to avoid duplicate logs
    root.propagate = False

    return root


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a specific module.

    Args:
        name: Module name (usually __name__)

    Returns:
        Logger instance
    """
    logger = logging.getLogger(name)
    # Add a filter to inject module_name into log records
    if not any(isinstance(f, _ModuleNameFilter) for f in logger.filters):
        logger.addFilter(_ModuleNameFilter(name))
    return logger


class _ModuleNameFilter(logging.Filter):
    """Filter to add module_name to log records."""
    def __init__(self, name: str):
        super().__init__()
        self.module_name = name.split('.')[-1] if name else 'JARVIS'

    def filter(self, record: logging.LogRecord) -> bool:
        record.module_name = self.module_name
        return True


# Convenience functions for common log levels
def log_debug(logger: logging.Logger, msg: str, *args, **kwargs):
    logger.debug(msg, *args, **kwargs)


def log_info(logger: logging.Logger, msg: str, *args, **kwargs):
    logger.info(msg, *args, **kwargs)


def log_warning(logger: logging.Logger, msg: str, *args, **kwargs):
    logger.warning(msg, *args, **kwargs)


def log_error(logger: logging.Logger, msg: str, *args, **kwargs):
    logger.error(msg, *args, **kwargs)


def log_critical(logger: logging.Logger, msg: str, *args, **kwargs):
    logger.critical(msg, *args, **kwargs)


def log_exception(logger: logging.Logger, msg: str, *args, **kwargs):
    """Log exception with full traceback."""
    logger.exception(msg, *args, **kwargs)


# Initialize on import
setup_logging()