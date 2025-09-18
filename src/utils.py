import os
from dotenv import load_dotenv

load_dotenv()

def env(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    """Get an env var with optional default and 'required' enforcement."""
    value = os.getenv(name, default)
    if required and (value is None or str(value).strip() == ""):
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

def env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean from env vars."""
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y"}


import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("policy-navigator") # A logger for debugging
