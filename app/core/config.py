from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    ENVIRONMENT: Literal["dev", "prod"] = Field(default="dev", description="Application environment")
    
    BASE_URL: str = Field(default="http://localhost:8000", description="Base URL for the API")
    FRONTEND_URL: str = Field(default="http://localhost:5173", description="Frontend URL for CORS")
    
    SECRET_KEY: str = Field(default="secret-key", description="Secret key for JWT signing")
    ALGORITHM: str = Field(default="HS256", description="JWT algorithm")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15, description="Access token expiration in minutes")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, description="Refresh token expiration in days")
    REFRESH_TOKEN_SECRET_KEY: str | None = Field(default=None, description="Optional separate secret key for refresh tokens")
    
    COOKIE_SECURE: bool = Field(default=True, description="Secure flag for cookies (HTTPS only)")
    COOKIE_SAME_SITE: Literal["lax", "strict", "none"] = Field(default="lax", description="SameSite policy for cookies")
    COOKIE_HTTP_ONLY: bool = Field(default=True, description="HttpOnly flag for cookies")
    
    DB_HOST: str = Field(default="localhost", description="Database host")
    DB_PORT: int = Field(default=5432, description="Database port")
    DB_NAME: str = Field(default="vecta_db", description="Database name")
    DB_USER: str = Field(default="postgres", description="Database user")
    DB_PASSWORD: str = Field(default="", description="Database password")
    
    # OpenAI Configuration
    OPENAI_API_KEY: str | None = Field(default=None, description="OpenAI API key for Agno agent")
    
    LOGIN_RATE_LIMIT_PER_MINUTE: int = Field(default=5, description="Maximum login attempts per minute per IP")
    REGISTER_RATE_LIMIT_PER_HOUR: int = Field(default=3, description="Maximum registration attempts per hour per IP")
    OTP_VERIFY_RATE_LIMIT_PER_MINUTE: int = Field(default=5, description="Maximum OTP verification attempts per minute per IP")
    MAX_FAILED_LOGIN_ATTEMPTS: int = Field(default=5, description="Maximum failed login attempts before account lockout")
    
    # OTP Configuration
    OTP_EXPIRY_MINUTES: int = Field(default=3, description="OTP expiration time in minutes")
    MAX_OTP_ATTEMPTS: int = Field(default=5, description="Maximum OTP verification attempts")
    FIXED_OTP: str | None = Field(default="", description="Fixed OTP for testing (leave empty for random OTP in production)")
    VERIFICATION_TOKEN_EXPIRY_MINUTES: int = Field(default=9, description="Verification token cookie expiration time in minutes")
    
    # Email Configuration (SMTP)
    SMTP_HOST: str = Field(default="smtp.gmail.com", description="SMTP server host")
    SMTP_PORT: int = Field(default=587, description="SMTP server port")
    SMTP_USERNAME: str = Field(default="", description="SMTP username/email")
    SMTP_PASSWORD: str = Field(default="", description="SMTP password/app password")
    SMTP_FROM_EMAIL: str = Field(default="", description="From email address")
    SMTP_FROM_NAME: str = Field(default="Vecta Finance", description="From name displayed in emails")
    
    @field_validator("ACCESS_TOKEN_EXPIRE_MINUTES", "REFRESH_TOKEN_EXPIRE_DAYS")
    @classmethod
    def validate_token_expiration(cls, v: int, info) -> int:
        if info.field_name == "ACCESS_TOKEN_EXPIRE_MINUTES" and v < 1:
            raise ValueError("Access token expiration must be at least 1 minute")
        if info.field_name == "REFRESH_TOKEN_EXPIRE_DAYS" and v < 1:
            raise ValueError("Refresh token expiration must be at least 1 day")
        return v
    
    @model_validator(mode="after")
    def set_environment_defaults(self):
        """Set environment-specific defaults and validations."""
        if self.ENVIRONMENT == "prod":
            if self.SECRET_KEY == "secret-key" or len(self.SECRET_KEY) < 32:
                raise ValueError(
                    "SECRET_KEY must be at least 32 characters long in production. "
                    "Set a strong secret key in your .env file."
                )
            if not self.BASE_URL.startswith("https://"):
                raise ValueError("BASE_URL must use HTTPS in production")
        
        # Dev environment overrides 
        if self.ENVIRONMENT == "dev":
            # Longer token expiration in dev for easier testing
            if self.ACCESS_TOKEN_EXPIRE_MINUTES == 15:
                self.ACCESS_TOKEN_EXPIRE_MINUTES = 60
            if self.REFRESH_TOKEN_EXPIRE_DAYS == 7:
                self.REFRESH_TOKEN_EXPIRE_DAYS = 30
            # Less strict cookie settings in dev for local development
            if self.COOKIE_SECURE is True:
                self.COOKIE_SECURE = False
            # Default to localhost if BASE_URL is production default
            if self.BASE_URL == "http://localhost:8000":
                pass  
        
        return self


settings = Settings()
