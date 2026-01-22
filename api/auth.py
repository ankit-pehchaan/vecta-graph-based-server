"""Auth API routes."""

from __future__ import annotations

import secrets
from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response, status
from fastapi.responses import RedirectResponse

from auth.config import AuthConfig
from auth.dependencies import (
    enforce_login_rate_limit,
    enforce_register_rate_limit,
    get_auth_service,
    get_current_user,
    get_oauth_service,
    require_csrf,
    set_cookie,
)
from auth.exceptions import AuthException
from auth.schemas import ApiResponse, GoogleAuthUrlResponse, LoginRequest, RegisterInitiateRequest, RegisterVerifyRequest
from auth.services.auth_service import AuthService
from auth.services.oauth_service import OAuthService

router = APIRouter()


def _set_csrf_cookie(response: Response, csrf_token: str) -> None:
    set_cookie(
        response,
        key=AuthConfig.CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=int(timedelta(days=7).total_seconds()),
        http_only=AuthConfig.CSRF_COOKIE_HTTP_ONLY,
    )


@router.post("/register/initiate", response_model=ApiResponse, status_code=status.HTTP_200_OK)
async def register_initiate(
    payload: RegisterInitiateRequest,
    response: Response,
    csrf_token: str | None = Header(default=None, alias=AuthConfig.CSRF_HEADER_NAME),
    _: None = Depends(require_csrf),
    __: None = Depends(enforce_register_rate_limit),
    auth_service: AuthService = Depends(get_auth_service),
) -> ApiResponse:
    try:
        verification_token = await auth_service.initiate_registration(
            name=payload.name,
            email=payload.email,
            password=payload.password,
            confirm=payload.confirm_password,
        )
    except AuthException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    set_cookie(
        response,
        key="verification_token",
        value=verification_token,
        max_age=AuthConfig.VERIFICATION_TOKEN_EXPIRY_MINUTES * 60,
    )
    if csrf_token:
        _set_csrf_cookie(response, csrf_token)

    return ApiResponse(
        success=True,
        message="OTP sent to your email",
        data={"verification_token": verification_token},
    )


@router.post("/register/verify", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def register_verify(
    payload: RegisterVerifyRequest,
    response: Response,
    csrf_token: str | None = Header(default=None, alias=AuthConfig.CSRF_HEADER_NAME),
    verification_token: str | None = Cookie(default=None),
    _: None = Depends(require_csrf),
    auth_service: AuthService = Depends(get_auth_service),
) -> ApiResponse:
    if not verification_token:
        raise HTTPException(status_code=400, detail="Missing verification token")

    try:
        result = await auth_service.verify_registration(verification_token, payload.otp)
    except AuthException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    access_max_age = int(timedelta(minutes=AuthConfig.ACCESS_TOKEN_EXPIRE_MINUTES).total_seconds())
    refresh_max_age = int(timedelta(days=AuthConfig.REFRESH_TOKEN_EXPIRE_DAYS).total_seconds())
    set_cookie(response, "access_token", result["tokens"]["access_token"], max_age=access_max_age)
    set_cookie(response, "refresh_token", result["tokens"]["refresh_token"], max_age=refresh_max_age)
    response.delete_cookie("verification_token", domain=AuthConfig.COOKIE_DOMAIN)
    if csrf_token:
        _set_csrf_cookie(response, csrf_token)

    return ApiResponse(
        success=True,
        message="Registration successful",
        data={
            "user": {
                "id": result["user"].get("id"),
                "email": result["user"].get("email"),
                "name": result["user"].get("name"),
                "oauth_provider": result["user"].get("oauth_provider"),
            },
            "access_token": result["tokens"]["access_token"],
            "refresh_token": result["tokens"]["refresh_token"],
        },
    )


@router.post("/login", response_model=ApiResponse, status_code=status.HTTP_200_OK)
async def login(
    payload: LoginRequest,
    response: Response,
    csrf_token: str | None = Header(default=None, alias=AuthConfig.CSRF_HEADER_NAME),
    _: None = Depends(require_csrf),
    __: None = Depends(enforce_login_rate_limit),
    auth_service: AuthService = Depends(get_auth_service),
) -> ApiResponse:
    try:
        result = await auth_service.login(payload.email, payload.password)
    except AuthException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    access_max_age = int(timedelta(minutes=AuthConfig.ACCESS_TOKEN_EXPIRE_MINUTES).total_seconds())
    refresh_max_age = int(timedelta(days=AuthConfig.REFRESH_TOKEN_EXPIRE_DAYS).total_seconds())
    set_cookie(response, "access_token", result["tokens"]["access_token"], max_age=access_max_age)
    set_cookie(response, "refresh_token", result["tokens"]["refresh_token"], max_age=refresh_max_age)
    if csrf_token:
        _set_csrf_cookie(response, csrf_token)

    return ApiResponse(
        success=True,
        message="Login successful",
        data={
            "user": {
                "id": result["user"].get("id"),
                "email": result["user"].get("email"),
                "name": result["user"].get("name"),
                "oauth_provider": result["user"].get("oauth_provider"),
            },
            "access_token": result["tokens"]["access_token"],
            "refresh_token": result["tokens"]["refresh_token"],
        },
    )


@router.post("/logout", response_model=ApiResponse, status_code=status.HTTP_200_OK)
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    _: None = Depends(require_csrf),
    auth_service: AuthService = Depends(get_auth_service),
) -> ApiResponse:
    try:
        await auth_service.logout(refresh_token)
    except AuthException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    response.delete_cookie("access_token", domain=AuthConfig.COOKIE_DOMAIN)
    response.delete_cookie("refresh_token", domain=AuthConfig.COOKIE_DOMAIN)
    return ApiResponse(success=True, message="Logged out", data={})


@router.get("/me", response_model=ApiResponse, status_code=status.HTTP_200_OK)
async def me(current_user: dict = Depends(get_current_user)) -> ApiResponse:
    return ApiResponse(
        success=True,
        message="User retrieved",
        data={
            "user": {
                "id": current_user.get("id"),
                "email": current_user.get("email"),
                "name": current_user.get("name"),
                "oauth_provider": current_user.get("oauth_provider"),
            }
        },
    )


@router.get("/google/login", response_model=ApiResponse, status_code=status.HTTP_200_OK)
async def google_login(
    response: Response,
    oauth_service: OAuthService = Depends(get_oauth_service),
) -> ApiResponse:
    try:
        result = oauth_service.generate_auth_url()
    except AuthException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    set_cookie(
        response,
        key="oauth_state",
        value=result["state"],
        max_age=600,
    )

    return ApiResponse(
        success=True,
        message="Google OAuth URL generated",
        data=GoogleAuthUrlResponse(**result).model_dump(),
    )


@router.get("/google/callback")
async def google_callback(
    code: str,
    state: str,
    oauth_state: str | None = Cookie(default=None),
    oauth_service: OAuthService = Depends(get_oauth_service),
):
    try:
        if not oauth_state:
            raise AuthException("Missing OAuth state. Please retry.", status_code=400)
        if oauth_state != state:
            raise AuthException("Invalid OAuth state.", status_code=400)

        result = await oauth_service.handle_google_callback(code)

        access_max_age = int(timedelta(minutes=AuthConfig.ACCESS_TOKEN_EXPIRE_MINUTES).total_seconds())
        refresh_max_age = int(timedelta(days=AuthConfig.REFRESH_TOKEN_EXPIRE_DAYS).total_seconds())

        csrf_token = secrets.token_urlsafe(24)
        redirect_url = f"{AuthConfig.FRONTEND_URL}?auth=success&new_user={'true' if result.get('is_new_user') else 'false'}"
        redirect_response = RedirectResponse(url=redirect_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

        set_cookie(redirect_response, "access_token", result["tokens"]["access_token"], max_age=access_max_age)
        set_cookie(redirect_response, "refresh_token", result["tokens"]["refresh_token"], max_age=refresh_max_age)
        _set_csrf_cookie(redirect_response, csrf_token)

        redirect_response.delete_cookie("oauth_state", domain=AuthConfig.COOKIE_DOMAIN)
        return redirect_response
    except AuthException as exc:
        error_message = quote(exc.message)
        redirect_url = f"{AuthConfig.FRONTEND_URL}?auth=error&message={error_message}"
        error_response = RedirectResponse(url=redirect_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
        error_response.delete_cookie("oauth_state", domain=AuthConfig.COOKIE_DOMAIN)
        return error_response

