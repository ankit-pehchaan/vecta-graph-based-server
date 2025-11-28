import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Settings:
    # API Configuration
    BASE_URL: str = os.getenv("BASE_URL", "http://localhost:8000")
    
    # JWT Configuration
    SECRET_KEY: str = os.getenv("SECRET_KEY", "secret-key")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))


settings = Settings()
