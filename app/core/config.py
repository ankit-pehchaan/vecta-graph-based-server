from pydantic import Field, field_validator, model_validator, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal, Optional
import os
import logging

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # AWS Secrets Manager Configuration
    USE_AWS_SECRETS: bool = Field(default=False, description="Enable AWS Secrets Manager integration")
    AWS_SECRET_NAME: Optional[str] = Field(default=None, description="AWS Secrets Manager secret name")
    AWS_REGION: str = Field(default="us-east-1", description="AWS region for Secrets Manager")

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

    # Database Configuration
    DB_HOST: str = Field(default="localhost", description="Database host")
    DB_PORT: int = Field(default=5432, description="Database port")
    DB_NAME: str = Field(default="vecta_db", description="Database name")
    DB_USER: str = Field(default="postgres", description="Database user")
    DB_PASSWORD: str = Field(default="", description="Database password")
    DATABASE_URL: Optional[str] = Field(default=None, description="Full database URL (overrides individual DB_* settings)")
    DB_POOL_SIZE: int = Field(default=5, description="Database connection pool size")
    DB_ECHO: bool = Field(default=False, description="Enable SQL query logging")

    # OpenAI Configuration
    OPENAI_API_KEY: str | None = Field(default=None, description="OpenAI API key for Agno agent")

    LOGIN_RATE_LIMIT_PER_MINUTE: int = Field(default=5, description="Maximum login attempts per minute per IP")
    REGISTER_RATE_LIMIT_PER_HOUR: int = Field(default=3, description="Maximum registration attempts per hour per IP")
    OTP_VERIFY_RATE_LIMIT_PER_MINUTE: int = Field(default=5, description="Maximum OTP verification attempts per minute per IP")
    MAX_FAILED_LOGIN_ATTEMPTS: int = Field(default=5, description="Maximum failed login attempts before account lockout")

    @computed_field
    @property
    def database_url_computed(self) -> str:
        """
        Compute the database URL from individual settings or use DATABASE_URL if provided.

        Returns:
            str: PostgreSQL connection URL for asyncpg
        """
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            # Ensure asyncpg driver is used
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            elif not url.startswith("postgresql+asyncpg://"):
                url = f"postgresql+asyncpg://{url}"
            return url

        # Build URL from individual settings
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    # OTP Configuration
    OTP_EXPIRY_MINUTES: int = Field(default=3, description="OTP expiration time in minutes")
    MAX_OTP_ATTEMPTS: int = Field(default=5, description="Maximum OTP verification attempts")
    FIXED_OTP: str | None = Field(default="", description="Fixed OTP for testing (leave empty for random OTP in production)")
    VERIFICATION_TOKEN_EXPIRY_MINUTES: int = Field(default=9, description="Verification token cookie expiration time in minutes")
    
    # Email Configuration
    EMAIL_PROVIDER: Literal["ses", "resend"] = Field(default="ses", description="Email provider: 'ses' or 'resend'")
    EMAIL_FROM_ADDRESS: str = Field(default="", description="Sender email address")
    EMAIL_FROM_NAME: str = Field(default="Vecta AI", description="From name displayed in emails")

    # AWS SES Configuration (used when EMAIL_PROVIDER=ses)
    AWS_SES_REGION: str = Field(default="ap-southeast-2", description="AWS SES region")
    SES_CONFIGURATION_SET: str | None = Field(default=None, description="Optional SES configuration set name")

    # Resend Configuration (used when EMAIL_PROVIDER=resend)
    RESEND_API_KEY: str | None = Field(default=None, description="Resend API key")

    # Google OAuth Configuration
    GOOGLE_CLIENT_ID: str | None = Field(default=None, description="Google OAuth Client ID")
    GOOGLE_CLIENT_SECRET: str | None = Field(default=None, description="Google OAuth Client Secret")
    GOOGLE_REDIRECT_URI: str | None = Field(default=None, description="Google OAuth Redirect URI")

    # Document Processing Configuration
    DOC_UPLOAD_LAMBDA_URL: str = Field(
        default="https://your-api-id.execute-api.ap-southeast-2.amazonaws.com/Prod/upload/",
        description="API Gateway URL for document redaction Lambda"
    )

    # Document Processing Configuration
    DOC_UPLOAD_LAMBDA_URL: str = Field(
        default="https://your-api-id.execute-api.ap-southeast-2.amazonaws.com/Prod/upload/",
        description="API Gateway URL for document redaction Lambda"
    )

    # Backwards compatibility aliases
    @property
    def SES_FROM_EMAIL(self) -> str:
        return self.EMAIL_FROM_ADDRESS

    @property
    def SES_FROM_NAME(self) -> str:
        return self.EMAIL_FROM_NAME
    
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
            if self.BASE_URL == "http://localhost:80":
                pass  
        
        return self


def _load_settings_with_aws_fallback() -> Settings:
    """
    Load settings with AWS Secrets Manager integration and local .env fallback.

    Priority order:
    1. AWS Secrets Manager (if USE_AWS_SECRETS=true and AWS_SECRET_NAME is set)
    2. Local .env file
    3. Default values from Settings class

    Returns:
        Settings instance with loaded configuration
    """
    # First load basic config from .env to check if AWS should be used
    basic_settings = Settings()

    if not basic_settings.USE_AWS_SECRETS:
        logger.info("AWS Secrets Manager disabled, using local .env configuration")
        return basic_settings

    if not basic_settings.AWS_SECRET_NAME:
        logger.warning("USE_AWS_SECRETS=true but AWS_SECRET_NAME not set, using local .env configuration")
        return basic_settings

    # Try to load from AWS Secrets Manager
    try:
        from app.core.aws_secrets import load_secrets_from_aws

        logger.info(f"Attempting to load secrets from AWS Secrets Manager: {basic_settings.AWS_SECRET_NAME}")
        aws_secrets = load_secrets_from_aws(
            secret_name=basic_settings.AWS_SECRET_NAME,
            region_name=basic_settings.AWS_REGION
        )

        if aws_secrets:
            logger.info(f"Successfully loaded {len(aws_secrets)} secrets from AWS Secrets Manager")

            # Merge AWS secrets with environment variables
            # AWS secrets take precedence over .env file but not over actual environment variables
            merged_env = {}

            # Start with AWS secrets
            for key, value in aws_secrets.items():
                env_key = key.upper()
                merged_env[env_key] = value

            # Override with actual environment variables (highest priority)
            for key in os.environ:
                merged_env[key] = os.environ[key]

            # Create settings with merged configuration
            # Temporarily set environment variables for pydantic to pick up
            original_env = {}
            for key, value in merged_env.items():
                if key not in os.environ:
                    original_env[key] = os.environ.get(key)
                    os.environ[key] = str(value)

            try:
                settings_with_aws = Settings()
                logger.info("Configuration loaded successfully with AWS Secrets Manager")
                return settings_with_aws
            finally:
                # Clean up temporary environment variables
                for key in original_env:
                    if original_env[key] is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = original_env[key]
        else:
            logger.info("AWS Secrets Manager returned no secrets, falling back to local .env configuration")
            return basic_settings

    except ImportError as e:
        logger.error(f"Failed to import AWS secrets module: {e}")
        logger.info("Falling back to local .env configuration")
        return basic_settings
    except Exception as e:
        logger.error(f"Unexpected error loading AWS secrets: {e}")
        logger.info("Falling back to local .env configuration")
        return basic_settings


settings = _load_settings_with_aws_fallback()
