"""OAuth authentication schemas."""
from pydantic import BaseModel, ConfigDict


class GoogleAuthUrlResponse(BaseModel):
    """Response schema for Google OAuth URL generation."""
    model_config = ConfigDict(extra='ignore')
    
    auth_url: str
    state: str  # CSRF protection token


class GoogleUserInfo(BaseModel):
    """Google user information from OAuth."""
    model_config = ConfigDict(extra='ignore')
    
    email: str
    name: str
    given_name: str | None = None
    family_name: str | None = None
    picture: str | None = None
    email_verified: bool = True


class OAuthCallbackResponse(BaseModel):
    """Response schema for OAuth callback (same as TokenResponse)."""
    model_config = ConfigDict(extra='ignore')
    
    email: str
    name: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    is_new_user: bool = False  # True if user was just created
