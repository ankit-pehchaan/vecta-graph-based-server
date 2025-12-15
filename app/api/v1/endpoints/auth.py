from datetime import timedelta
from fastapi import APIRouter, Response, status, Depends, Cookie
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.user import (
    UserLoginRequest,
    TokenResponse,
    RegistrationInitiateRequest,
    RegistrationInitiateResponse,
    OTPVerifyRequest,
    ResendOTPResponse,
    UserData
)
from app.schemas.response import ApiResponse
from app.services.auth import AuthService
from app.repositories.user_repository import UserRepository
from app.repositories.verification_repository import VerificationRepository
from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import (
    check_login_rate_limit,
    check_register_rate_limit,
    check_otp_verify_rate_limit,
    get_current_user
)
from app.core.handler import AppException
from app.core.constants import AuthErrorDetails, GeneralErrorDetails
from app.core.security import decode_token
from jose import JWTError

router = APIRouter()


async def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    """Dependency injection for AuthService with database repositories."""
    user_repository = UserRepository(db)
    verification_repository = VerificationRepository(db)
    return AuthService(
        user_repository=user_repository,
        verification_repository=verification_repository
    )


@router.post("/register/initiate", response_model=ApiResponse, status_code=status.HTTP_200_OK)
async def register_initiate(
    user: RegistrationInitiateRequest,
    response: Response,
    _: None = Depends(check_register_rate_limit),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Initiate registration by sending OTP to email."""
    result = await auth_service.initiate_registration(
        name=user.name,
        email=user.email,
        password=user.password
    )

    response.set_cookie(
        key="verification_token",
        value=result["verification_token"],
        httponly=settings.COOKIE_HTTP_ONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAME_SITE,
        max_age=settings.VERIFICATION_TOKEN_EXPIRY_MINUTES * 60
    )

    return ApiResponse(
        success=True,
        message="OTP sent to your email",
        data=RegistrationInitiateResponse(
            verification_token=result["verification_token"]
        )
    )


@router.post("/register/verify", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def register_verify(
    request: OTPVerifyRequest,
    response: Response,
    verification_token: str = Cookie(...),
    _: None = Depends(check_otp_verify_rate_limit),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Verify OTP and complete registration. Token is read from cookie."""
    result = await auth_service.verify_otp(
        verification_token=verification_token,
        otp=request.otp
    )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh_token_expires = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    response.set_cookie(
        key="access_token",
        value=result["access_token"],
        httponly=settings.COOKIE_HTTP_ONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAME_SITE,
        max_age=int(access_token_expires.total_seconds())
    )
    response.set_cookie(
        key="refresh_token",
        value=result["refresh_token"],
        httponly=settings.COOKIE_HTTP_ONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAME_SITE,
        max_age=int(refresh_token_expires.total_seconds())
    )

    response.delete_cookie(
        key="verification_token",
        httponly=settings.COOKIE_HTTP_ONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAME_SITE
    )

    return ApiResponse(
        success=True,
        message="Registration successful",
        data=TokenResponse(
            email=result["email"],
            name=result["name"],
            access_token=result["access_token"],
            refresh_token=result["refresh_token"]
        )
    )


@router.post("/register/resend-otp", response_model=ApiResponse, status_code=status.HTTP_200_OK)
async def resend_otp(
    response: Response,
    verification_token: str = Cookie(...),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Resend OTP for pending verification. Token is read from cookie."""
    result = await auth_service.resend_otp(verification_token=verification_token)

    # Refresh the cookie expiry time (reset to 9 minutes)
    response.set_cookie(
        key="verification_token",
        value=verification_token,
        httponly=settings.COOKIE_HTTP_ONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAME_SITE,
        max_age=settings.VERIFICATION_TOKEN_EXPIRY_MINUTES * 60
    )

    return ApiResponse(
        success=True,
        message=result["message"],
        data=ResendOTPResponse(message=result["message"])
    )


@router.post("/login", response_model=ApiResponse, status_code=status.HTTP_200_OK)
async def login(
    user: UserLoginRequest,
    response: Response,
    _: None = Depends(check_login_rate_limit),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Login user and return JWT tokens."""
    result = await auth_service.login_user(user.email, user.password)

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh_token_expires = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    response.set_cookie(
        key="access_token",
        value=result["access_token"],
        httponly=settings.COOKIE_HTTP_ONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAME_SITE,
        max_age=int(access_token_expires.total_seconds())
    )
    response.set_cookie(
        key="refresh_token",
        value=result["refresh_token"],
        httponly=settings.COOKIE_HTTP_ONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAME_SITE,
        max_age=int(refresh_token_expires.total_seconds())
    )

    user_data = result.get("user", {})
    user_name = user_data.get("name") if isinstance(user_data, dict) else None

    return ApiResponse(
        success=True,
        message="Login successful",
        data=TokenResponse(
            email=user.email,
            name=user_name,
            access_token=result["access_token"],
            refresh_token=result["refresh_token"]
        )
    )


@router.post("/logout", response_model=ApiResponse, status_code=status.HTTP_200_OK)
async def logout(response: Response):
    """Logout user by clearing tokens."""
    response.delete_cookie(
        key="access_token",
        httponly=settings.COOKIE_HTTP_ONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAME_SITE
    )
    response.delete_cookie(
        key="refresh_token",
        httponly=settings.COOKIE_HTTP_ONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAME_SITE
    )

    return ApiResponse(
        success=True,
        message="Logged out successfully",
        data={}
    )


@router.get("/me", response_model=ApiResponse, status_code=status.HTTP_200_OK)
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current authenticated user information."""
    return ApiResponse(
        success=True,
        message="User retrieved successfully",
        data=UserData(
            email=current_user["email"],
            name=current_user.get("name"),
            account_status=current_user.get("account_status")
        )
    )

async def get_oauth_service(db: AsyncSession = Depends(get_db)):
    """Dependency injection for OAuthService."""
    from app.services.oauth_service import OAuthService
    user_repository = UserRepository(db)
    return OAuthService(user_repository=user_repository)


@router.get("/google/login", response_model=ApiResponse, status_code=status.HTTP_200_OK)
async def google_login(
    response: Response,
    oauth_service = Depends(get_oauth_service)
):
    """
    Initiate Google OAuth flow.
    
    Returns Google OAuth authorization URL that frontend should redirect to.
    The state parameter is included for CSRF protection and stored in HTTP-only cookie.
    
    Frontend should:
    1. Call this endpoint
    2. Redirect user to the returned auth_url
    3. User authenticates with Google
    4. Google redirects back to /auth/google/callback
    
    Security:
    - State token is stored in HTTP-only cookie for CSRF validation
    - Cookie expires in 10 minutes (enough time for OAuth flow)
    """
    from app.schemas.oauth import GoogleAuthUrlResponse
    
    result = oauth_service.generate_auth_url()
    
    # Store state in HTTP-only cookie for CSRF validation
    response.set_cookie(
        key="oauth_state",
        value=result["state"],
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAME_SITE,
        max_age=600  
    )
    
    return ApiResponse(
        success=True,
        message="Google OAuth URL generated",
        data=GoogleAuthUrlResponse(
            auth_url=result["auth_url"],
            state=result["state"]
        )
    )


@router.get("/google/callback")
async def google_callback(
    code: str,
    state: str,
    oauth_state: str = Cookie(None),
    oauth_service = Depends(get_oauth_service)
):
    """
    Handle Google OAuth callback.
    
    This endpoint:
    1. Validates CSRF state token (security check)
    2. Receives authorization code from Google
    3. Exchanges code for user information
    4. Creates new user OR logs in existing user (unified flow)
    5. Sets JWT tokens in HTTP-only cookies
    6. Redirects to frontend with success/error
    
    Query Parameters:
        code: Authorization code from Google (required)
        state: CSRF protection token from Google (required)
    
    Cookies:
        oauth_state: Stored state token for CSRF validation (required)
    
    Redirects to:
        Success: {FRONTEND_URL}/?auth=success&new_user=true/false
        Error: {FRONTEND_URL}/?auth=error&message=...
    
    Security:
        - Validates state parameter matches stored oauth_state cookie
        - Prevents CSRF attacks by ensuring callback is from legitimate OAuth flow
    """
    from fastapi.responses import RedirectResponse
    from urllib.parse import quote
    
    try:
        # CSRF Protection: Validate state parameter
        if not oauth_state:
            raise AppException(
                message="Missing OAuth state. Please restart the login process.",
                status_code=400
            )
        
        if oauth_state != state:
            raise AppException(
                message="Invalid OAuth state. Possible CSRF attack detected.",
                status_code=400
            )
        
        # Handle Google login (unified login/register)
        result = await oauth_service.handle_google_login(code, state)
        
        # Set JWT tokens in cookies (same as email/password login)
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        refresh_token_expires = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        
        # Redirect to frontend with success
        is_new_user = "true" if result["is_new_user"] else "false"
        redirect_url = f"{settings.FRONTEND_URL}/?auth=success&new_user={is_new_user}"
        
        # Create redirect response with cookies
        redirect_response = RedirectResponse(url=redirect_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
        
        redirect_response.set_cookie(
            key="access_token",
            value=result["access_token"],
            httponly=settings.COOKIE_HTTP_ONLY,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAME_SITE,
            max_age=int(access_token_expires.total_seconds())
        )
        redirect_response.set_cookie(
            key="refresh_token",
            value=result["refresh_token"],
            httponly=settings.COOKIE_HTTP_ONLY,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAME_SITE,
            max_age=int(refresh_token_expires.total_seconds())
        )
        
        # Delete oauth_state cookie after successful validation
        redirect_response.delete_cookie(
            key="oauth_state",
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAME_SITE
        )
        
        return redirect_response
        
    except AppException as e:
        # Redirect to frontend with error
        error_message = quote(e.message)
        redirect_url = f"{settings.FRONTEND_URL}/?auth=error&message={error_message}"
        
        # Create error redirect and clean up oauth_state cookie
        error_response = RedirectResponse(url=redirect_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
        error_response.delete_cookie(
            key="oauth_state",
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAME_SITE
        )
        return error_response
        
    except Exception as e:
        # Unexpected error
        error_message = quote("Authentication failed")
        redirect_url = f"{settings.FRONTEND_URL}/?auth=error&message={error_message}"
        
        # Create error redirect and clean up oauth_state cookie
        error_response = RedirectResponse(url=redirect_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
        error_response.delete_cookie(
            key="oauth_state",
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAME_SITE
        )
        return error_response
