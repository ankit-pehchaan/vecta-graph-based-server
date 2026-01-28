"""
Configuration management for the application.
"""

import os
from pathlib import Path


# Load .env file if it exists
try:
    from dotenv import load_dotenv
    
    # Load .env from project root
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
    else:
        # Try loading from current directory as fallback
        load_dotenv(override=True)
except ImportError:
    # python-dotenv not installed, skip loading .env
    pass


class Config:
    """Application configuration."""
    
    # Model configuration
    MODEL_ID: str = os.getenv("MODEL_ID", "gpt-4.1")
    
    # OpenAI API Key (required for agents)
    OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
    
    # PostgreSQL Database URL
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/vecta"
    )
    
    # API configuration
    CORS_ORIGINS: list[str] = os.getenv("CORS_ORIGINS", "https://vectatech.com.au,https://www.vectatech.com.au").split(",")
    
    @classmethod
    def validate(cls) -> None:
        """Validate required configuration."""
        if not cls.OPENAI_API_KEY:
            raise ValueError(
                "OPENAI_API_KEY not set. Please set it in .env file or environment variable.\n"
                "Create a .env file in the project root with: OPENAI_API_KEY=your_key_here"
            )

        # Warn about wildcard CORS with credentials (browsers reject this)
        if "*" in cls.CORS_ORIGINS:
            import warnings
            warnings.warn(
                "CORS_ORIGINS contains '*' which is incompatible with allow_credentials=True. "
                "Set explicit origins like 'https://yourdomain.com' for production.",
                UserWarning
            )

