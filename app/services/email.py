"""Email service for sending OTP and other notifications.

Supports multiple email providers (AWS SES, Resend) configured via EMAIL_PROVIDER env var.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


# =============================================================================
# Email Provider Interface
# =============================================================================

class EmailProvider(ABC):
    """Abstract base class for email providers."""

    @abstractmethod
    async def send(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None
    ) -> bool:
        """Send an email. Returns True on success, False on failure."""
        pass


# =============================================================================
# AWS SES Provider
# =============================================================================

class SESProvider(EmailProvider):
    """AWS SES email provider."""

    def __init__(self):
        import boto3
        self.client = boto3.client('ses', region_name=settings.AWS_SES_REGION)

    async def send(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None
    ) -> bool:
        from botocore.exceptions import ClientError, NoCredentialsError

        try:
            source = f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM_ADDRESS}>"

            body = {
                'Html': {
                    'Data': html_body,
                    'Charset': 'UTF-8'
                }
            }

            if text_body:
                body['Text'] = {
                    'Data': text_body,
                    'Charset': 'UTF-8'
                }

            send_params = {
                'Source': source,
                'Destination': {
                    'ToAddresses': [to_email]
                },
                'Message': {
                    'Subject': {
                        'Data': subject,
                        'Charset': 'UTF-8'
                    },
                    'Body': body
                }
            }

            if settings.SES_CONFIGURATION_SET:
                send_params['ConfigurationSetName'] = settings.SES_CONFIGURATION_SET

            response = self.client.send_email(**send_params)

            message_id = response.get('MessageId', 'unknown')
            logger.info(f"[SES] Email sent to {to_email}, MessageId: {message_id}")
            return True

        except NoCredentialsError:
            logger.error("[SES] AWS credentials not found")
            return False
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(f"[SES] Error sending to {to_email}: {error_code} - {error_message}")
            return False
        except Exception as e:
            logger.error(f"[SES] Unexpected error sending to {to_email}: {str(e)}")
            return False


# =============================================================================
# Resend Provider
# =============================================================================

class ResendProvider(EmailProvider):
    """Resend email provider."""

    def __init__(self):
        if not settings.RESEND_API_KEY:
            raise ValueError("RESEND_API_KEY is required when using Resend provider")

        import resend
        resend.api_key = settings.RESEND_API_KEY
        self.resend = resend

    async def send(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None
    ) -> bool:
        try:
            from_address = f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM_ADDRESS}>"

            params = {
                "from": from_address,
                "to": [to_email],
                "subject": subject,
                "html": html_body,
            }

            if text_body:
                params["text"] = text_body

            response = self.resend.Emails.send(params)

            email_id = response.get('id', 'unknown') if isinstance(response, dict) else getattr(response, 'id', 'unknown')
            logger.info(f"[Resend] Email sent to {to_email}, ID: {email_id}")
            return True

        except Exception as e:
            logger.error(f"[Resend] Error sending to {to_email}: {str(e)}")
            return False


# =============================================================================
# Provider Factory
# =============================================================================

_provider_instance: Optional[EmailProvider] = None


def get_email_provider() -> EmailProvider:
    """Get the configured email provider (singleton)."""
    global _provider_instance

    if _provider_instance is None:
        provider_name = settings.EMAIL_PROVIDER.lower()

        if provider_name == "ses":
            _provider_instance = SESProvider()
            logger.info("Email provider initialized: AWS SES")
        elif provider_name == "resend":
            _provider_instance = ResendProvider()
            logger.info("Email provider initialized: Resend")
        else:
            raise ValueError(f"Unknown email provider: {provider_name}. Use 'ses' or 'resend'.")

    return _provider_instance


# =============================================================================
# Email Templates
# =============================================================================

def _create_otp_email_html(otp: str) -> str:
    """Create HTML template for OTP email."""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: Arial, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 600px;
                margin: 0 auto;
                padding: 20px;
            }}
            .container {{
                background-color: #f9f9f9;
                border-radius: 10px;
                padding: 30px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            }}
            .header {{
                text-align: center;
                color: #2c3e50;
                margin-bottom: 30px;
            }}
            .otp-box {{
                background-color: #fff;
                border: 2px solid #3498db;
                border-radius: 8px;
                padding: 20px;
                text-align: center;
                margin: 20px 0;
            }}
            .otp-code {{
                font-size: 32px;
                font-weight: bold;
                color: #3498db;
                letter-spacing: 8px;
                margin: 10px 0;
            }}
            .footer {{
                text-align: center;
                color: #7f8c8d;
                font-size: 12px;
                margin-top: 30px;
            }}
            .warning {{
                color: #e74c3c;
                font-weight: bold;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Email Verification</h1>
                <p>Welcome to {settings.EMAIL_FROM_NAME}!</p>
            </div>

            <p>Thank you for registering. Please use the verification code below to complete your registration:</p>

            <div class="otp-box">
                <p>Your verification code is:</p>
                <div class="otp-code">{otp}</div>
            </div>

            <p><span class="warning">This code will expire in {settings.OTP_EXPIRY_MINUTES} minutes.</span></p>

            <p>If you didn't request this code, please ignore this email.</p>

            <div class="footer">
                <p>This is an automated message, please do not reply.</p>
                <p>2024 {settings.EMAIL_FROM_NAME}. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """


def _create_otp_email_text(otp: str) -> str:
    """Create plain text version of OTP email."""
    return f"""
Welcome to {settings.EMAIL_FROM_NAME}!

Your verification code is: {otp}

This code will expire in {settings.OTP_EXPIRY_MINUTES} minutes.

If you didn't request this code, please ignore this email.

---
This is an automated message, please do not reply.
2024 {settings.EMAIL_FROM_NAME}. All rights reserved.
    """


# =============================================================================
# Public API
# =============================================================================

async def send_otp_email(email: str, otp: str) -> bool:
    """
    Send OTP to user's email address.

    Args:
        email: Recipient email address
        otp: One-time password to send

    Returns:
        True if email sent successfully, False otherwise
    """
    provider = get_email_provider()

    subject = f"Your {settings.EMAIL_FROM_NAME} Verification Code"
    html_body = _create_otp_email_html(otp)
    text_body = _create_otp_email_text(otp)

    return await provider.send(email, subject, html_body, text_body)


async def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: Optional[str] = None
) -> bool:
    """
    Send a generic email.

    Args:
        to_email: Recipient email address
        subject: Email subject
        html_body: HTML content of the email
        text_body: Plain text content (optional)

    Returns:
        True if email sent successfully, False otherwise
    """
    provider = get_email_provider()
    return await provider.send(to_email, subject, html_body, text_body)
