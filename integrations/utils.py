#!/usr/bin/env python3
"""Shared utilities for Iris integrations.

Provides common functionality used across multiple integrations:
- run_claude: Execute prompts via Claude CLI
- make_logger: Create consistent file+stdout loggers
"""

import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from config import WORKSPACE, STATE_DIR


def run_claude(prompt: str, timeout: int = 120, cwd: Path = None) -> str:
    """Run a prompt through Claude CLI.

    Args:
        prompt: The prompt to send to Claude
        timeout: Timeout in seconds (default 120)
        cwd: Working directory (defaults to WORKSPACE)

    Returns:
        Claude's response text, or "Error: <message>" on failure
    """
    if cwd is None:
        cwd = WORKSPACE

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd),
            env={**os.environ, "PATH": "/home/iris/.local/node_modules/.bin:" + os.environ.get("PATH", "")}
        )
        return result.stdout.strip() if result.returncode == 0 else f"Error: {result.stderr}"
    except subprocess.TimeoutExpired:
        return "Error: Timeout"
    except Exception as e:
        return f"Error: {e}"


def make_logger(name: str, log_file: Path = None) -> logging.Logger:
    """Create a logger that writes to both file and stdout.

    Args:
        name: Logger name (usually script name without .py)
        log_file: Path for log file. If None, uses STATE_DIR/<name>.log

    Returns:
        Configured logger instance
    """
    if log_file is None:
        log_file = STATE_DIR / f"{name}.log"

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Avoid adding duplicate handlers
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "[%(asctime)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Stdout handler
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    return logger


def log_to_file(log_file: Path, message: str):
    """Simple file+stdout logging without logging module.

    For scripts that want the old-style log() function behavior.

    Args:
        log_file: Path to log file
        message: Message to log
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    with open(log_file, "a") as f:
        f.write(line + "\n")
