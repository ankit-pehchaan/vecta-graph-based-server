"""OAuth authentication service for Google OAuth 2.0."""
import secrets
from typing import Optional
from authlib.integrations.httpx_client import AsyncOAuth2Client
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.handler import AppException
from app.core.security import create_access_token, create_refresh_token
from app.repositories.user_repository import UserRepository
from app.schemas.oauth import GoogleUserInfo
from app.services.kms_service import KmsService


class OAuthService:
    """Service for handling Google OAuth authentication."""

    # Google OAuth 2.0 endpoints
    GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
    GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

    # OAuth scopes we need
    SCOPES = [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    ]

    def __init__(self, user_repository: UserRepository, session: Optional[AsyncSession] = None):
        """
        Initialize OAuth service.

        Args:
            user_repository: User repository for database operations
            session: Database session for KMS key creation
        """
        self.user_repository = user_repository
        self.session = session
        self._kms_service: Optional[KmsService] = None

    def _get_kms_service(self) -> Optional[KmsService]:
        """Get KMS service if session is available."""
        if self.session and not self._kms_service:
            self._kms_service = KmsService(session=self.session)
        return self._kms_service

    def _validate_config(self) -> None:
        """
        Validate that Google OAuth is properly configured.

        Raises:
            AppException: If configuration is missing or invalid
        """
        if not settings.GOOGLE_CLIENT_ID:
            raise AppException(
                message="Google OAuth is not configured. Missing GOOGLE_CLIENT_ID.",
                status_code=500,
            )
        if not settings.GOOGLE_CLIENT_SECRET:
            raise AppException(
                message="Google OAuth is not configured. Missing GOOGLE_CLIENT_SECRET.",
                status_code=500,
            )
        if not settings.GOOGLE_REDIRECT_URI:
            raise AppException(
                message="Google OAuth is not configured. Missing GOOGLE_REDIRECT_URI.",
                status_code=500,
            )

    def generate_auth_url(self) -> dict[str, str]:
        """
        Generate Google OAuth authorization URL.

        Returns:
            Dictionary with auth_url and state (CSRF token)

        Raises:
            AppException: If OAuth is not configured
        """
        self._validate_config()

        # Generate random state for CSRF protection
        state = secrets.token_urlsafe(32)

        # Create OAuth client
        client = AsyncOAuth2Client(
            client_id=settings.GOOGLE_CLIENT_ID,
            redirect_uri=settings.GOOGLE_REDIRECT_URI,
            scope=" ".join(self.SCOPES),
        )

        auth_url, _ = client.create_authorization_url(
            self.GOOGLE_AUTH_URL, 
            state=state,
            prompt="select_account"
        )

        return {"auth_url": auth_url, "state": state}

    async def verify_google_token(
        self, code: str, state: Optional[str] = None
    ) -> GoogleUserInfo:
        """
        Exchange authorization code for user information.

        Args:
            code: Authorization code from Google callback
            state: CSRF token for validation (optional but recommended)

        Returns:
            GoogleUserInfo with user data from Google

        Raises:
            AppException: If token exchange fails or user info cannot be retrieved
        """
        self._validate_config()

        try:
            # Exchange code for access token
            async with httpx.AsyncClient() as client:
                token_response = await client.post(
                    self.GOOGLE_TOKEN_URL,
                    data={
                        "code": code,
                        "client_id": settings.GOOGLE_CLIENT_ID,
                        "client_secret": settings.GOOGLE_CLIENT_SECRET,
                        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                        "grant_type": "authorization_code",
                    },
                )

                if token_response.status_code != 200:
                    raise AppException(
                        message="Failed to exchange authorization code with Google.",
                        status_code=400,
                        data={"error": token_response.text},
                    )

                token_data = token_response.json()
                access_token = token_data.get("access_token")

                if not access_token:
                    raise AppException(
                        message="No access token received from Google.",
                        status_code=400,
                    )

                # Get user info from Google
                userinfo_response = await client.get(
                    self.GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                )

                if userinfo_response.status_code != 200:
                    raise AppException(
                        message="Failed to retrieve user information from Google.",
                        status_code=400,
                        data={"error": userinfo_response.text},
                    )

                user_data = userinfo_response.json()

                # Validate required fields
                if not user_data.get("email"):
                    raise AppException(
                        message="Email not provided by Google.",
                        status_code=400,
                    )

                # Create GoogleUserInfo object
                return GoogleUserInfo(
                    email=user_data["email"],
                    name=user_data.get("name", user_data["email"]),
                    given_name=user_data.get("given_name"),
                    family_name=user_data.get("family_name"),
                    picture=user_data.get("picture"),
                    email_verified=user_data.get("verified_email", True),
                )

        except httpx.HTTPError as e:
            raise AppException(
                message="Network error while communicating with Google.",
                status_code=500,
                data={"error": str(e)},
            )
        except Exception as e:
            if isinstance(e, AppException):
                raise
            raise AppException(
                message="Unexpected error during Google authentication.",
                status_code=500,
                data={"error": str(e)},
            )

    async def handle_google_login(
        self, code: str, state: Optional[str] = None
    ) -> dict[str, str | bool]:
        """
        Handle Google OAuth callback - unified login/register flow.

        This method automatically:
        - Registers new users
        - Logs in existing users
        - Links Google to existing email/password accounts

        Args:
            code: Authorization code from Google
            state: CSRF token for validation

        Returns:
            Dictionary with:
                - email: User's email
                - name: User's name
                - access_token: JWT access token
                - refresh_token: JWT refresh token
                - is_new_user: True if user was just created

        Raises:
            AppException: If authentication fails
        """
        # 1. Get user info from Google
        google_user = await self.verify_google_token(code, state)

        # 2. Check if user exists
        existing_user = await self.user_repository.get_by_email(google_user.email)

        is_new_user = False

        if existing_user:
            # User exists - LOGIN flow
            oauth_provider = existing_user.get("oauth_provider")

            if oauth_provider == "local" or oauth_provider is None:
                # User registered with email/password
                # Link Google account for convenience
                await self.user_repository.link_oauth_provider(
                    google_user.email, "google"
                )

            # If oauth_provider is already "google", no action needed
            # User is logging in with their existing Google account

        else:
            # User doesn't exist - REGISTER flow
            new_user = await self.user_repository.create_oauth_user(
                email=google_user.email,
                name=google_user.name,
                oauth_provider="google",
            )
            is_new_user = True

            # Create KMS key for the new user (non-blocking on failure)
            kms_service = self._get_kms_service()
            if kms_service and new_user.get('id'):
                try:
                    await kms_service.create_and_save_user_key(
                        user_id=new_user['id'],
                        user_email=google_user.email
                    )
                    print(f"[OAuth] Created KMS key for user {new_user['id']}")
                except Exception as e:
                    # Log error but don't block signup - KMS key can be created later
                    print(f"[OAuth] Warning: Failed to create KMS key for user {new_user['id']}: {e}")

        # 3. Generate JWT tokens (same for both login and register)
        # Get user_id from existing_user or new_user
        user_id = None
        if is_new_user:
            user_id = new_user.get('id')
        else:
            user_id = existing_user.get('id')

        token_data = {"sub": google_user.email}
        if user_id is not None:
            token_data["user_id"] = user_id

        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)

        return {
            "email": google_user.email,
            "name": google_user.name,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "is_new_user": is_new_user,
        }
