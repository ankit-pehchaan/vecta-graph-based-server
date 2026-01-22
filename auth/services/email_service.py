"""Email delivery service."""

from __future__ import annotations

import httpx

from auth.config import AuthConfig


class EmailService:
    async def send_otp_email(self, email: str, otp: str) -> bool:
        if AuthConfig.EMAIL_PROVIDER != "resend":
            return False
        if not AuthConfig.RESEND_API_KEY:
            return False

        payload = {
            "from": f"{AuthConfig.EMAIL_FROM_NAME} <{AuthConfig.EMAIL_FROM_ADDRESS}>",
            "to": [email],
            "subject": "Your Vecta verification code",
            "html": f"<p>Your verification code is <strong>{otp}</strong>.</p>",
        }
        headers = {"Authorization": f"Bearer {AuthConfig.RESEND_API_KEY}"}

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers=headers,
                json=payload,
            )
        return response.status_code == 200

