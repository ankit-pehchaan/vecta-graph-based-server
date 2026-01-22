"""Google OAuth service."""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx

from auth.config import AuthConfig
from auth.exceptions import AuthException
from auth.services.auth_service import AuthService


class OAuthService:
    def __init__(self, auth_service: AuthService) -> None:
        self._auth_service = auth_service

    def generate_auth_url(self) -> dict[str, str]:
        if not AuthConfig.GOOGLE_CLIENT_ID or not AuthConfig.GOOGLE_REDIRECT_URI:
            raise AuthException("Google OAuth not configured", status_code=500)

        state = secrets.token_urlsafe(24)
        query = urlencode(
            {
                "client_id": AuthConfig.GOOGLE_CLIENT_ID,
                "redirect_uri": AuthConfig.GOOGLE_REDIRECT_URI,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "prompt": "select_account",
            }
        )
        return {"auth_url": f"https://accounts.google.com/o/oauth2/v2/auth?{query}", "state": state}

    async def handle_google_callback(self, code: str) -> dict[str, str | bool | dict]:
        if not AuthConfig.GOOGLE_CLIENT_ID or not AuthConfig.GOOGLE_CLIENT_SECRET:
            raise AuthException("Google OAuth not configured", status_code=500)
        if not AuthConfig.GOOGLE_REDIRECT_URI:
            raise AuthException("Google OAuth redirect URI not configured", status_code=500)

        token_payload = {
            "code": code,
            "client_id": AuthConfig.GOOGLE_CLIENT_ID,
            "client_secret": AuthConfig.GOOGLE_CLIENT_SECRET,
            "redirect_uri": AuthConfig.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        }

        async with httpx.AsyncClient(timeout=10) as client:
            token_response = await client.post(
                "https://oauth2.googleapis.com/token",
                data=token_payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_response.status_code != 200:
                raise AuthException("Failed to exchange Google code", status_code=400)
            token_data = token_response.json()

            access_token = token_data.get("access_token")
            if not access_token:
                raise AuthException("Google token missing access token", status_code=400)

            userinfo_response = await client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if userinfo_response.status_code != 200:
                raise AuthException("Failed to fetch Google user info", status_code=400)
            userinfo = userinfo_response.json()

        email = userinfo.get("email")
        name = userinfo.get("name")
        if not email:
            raise AuthException("Google account missing email", status_code=400)

        return await self._auth_service.login_oauth(email=email, name=name, provider="google")

