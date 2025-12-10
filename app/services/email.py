"""Email service for sending OTP and other notifications via AWS SES."""

import logging
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from app.core.config import settings

logger = logging.getLogger(__name__)


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
                <p>Welcome to {settings.SES_FROM_NAME}!</p>
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
                <p>2024 {settings.SES_FROM_NAME}. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """


def _create_otp_email_text(otp: str) -> str:
    """Create plain text version of OTP email."""
    return f"""
Welcome to {settings.SES_FROM_NAME}!

Your verification code is: {otp}

This code will expire in {settings.OTP_EXPIRY_MINUTES} minutes.

If you didn't request this code, please ignore this email.

---
This is an automated message, please do not reply.
2024 {settings.SES_FROM_NAME}. All rights reserved.
    """


def _get_ses_client():
    """Get boto3 SES client."""
    return boto3.client(
        'ses',
        region_name=settings.AWS_SES_REGION
    )


async def send_otp_email(email: str, otp: str) -> bool:
    """
    Send OTP to user's email address via AWS SES.

    Args:
        email: Recipient email address
        otp: One-time password to send

    Returns:
        True if email sent successfully, False otherwise
    """
    try:
        ses_client = _get_ses_client()

        # Build the email message
        subject = f"Your {settings.SES_FROM_NAME} Verification Code"
        html_body = _create_otp_email_html(otp)
        text_body = _create_otp_email_text(otp)

        # Construct the source with display name
        source = f"{settings.SES_FROM_NAME} <{settings.SES_FROM_EMAIL}>"

        # Build send_email parameters
        send_params = {
            'Source': source,
            'Destination': {
                'ToAddresses': [email]
            },
            'Message': {
                'Subject': {
                    'Data': subject,
                    'Charset': 'UTF-8'
                },
                'Body': {
                    'Text': {
                        'Data': text_body,
                        'Charset': 'UTF-8'
                    },
                    'Html': {
                        'Data': html_body,
                        'Charset': 'UTF-8'
                    }
                }
            }
        }

        # Add configuration set if specified
        if settings.SES_CONFIGURATION_SET:
            send_params['ConfigurationSetName'] = settings.SES_CONFIGURATION_SET

        # Send the email
        response = ses_client.send_email(**send_params)

        message_id = response.get('MessageId', 'unknown')
        logger.info(f"OTP email sent successfully to {email}, MessageId: {message_id}")
        return True

    except NoCredentialsError:
        logger.error("AWS credentials not found. Configure AWS credentials for SES access.")
        return False
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']

        if error_code == 'MessageRejected':
            logger.error(f"SES rejected message to {email}: {error_message}")
        elif error_code == 'MailFromDomainNotVerified':
            logger.error(f"SES sender domain not verified: {error_message}")
        elif error_code == 'ConfigurationSetDoesNotExist':
            logger.error(f"SES configuration set does not exist: {error_message}")
        else:
            logger.error(f"SES ClientError sending to {email}: {error_code} - {error_message}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending OTP email to {email}: {str(e)}")
        return False


async def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str | None = None
) -> bool:
    """
    Send a generic email via AWS SES.

    Args:
        to_email: Recipient email address
        subject: Email subject
        html_body: HTML content of the email
        text_body: Plain text content (optional, will strip HTML if not provided)

    Returns:
        True if email sent successfully, False otherwise
    """
    try:
        ses_client = _get_ses_client()

        source = f"{settings.SES_FROM_NAME} <{settings.SES_FROM_EMAIL}>"

        # Build message body
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

        response = ses_client.send_email(**send_params)

        message_id = response.get('MessageId', 'unknown')
        logger.info(f"Email sent successfully to {to_email}, MessageId: {message_id}")
        return True

    except NoCredentialsError:
        logger.error("AWS credentials not found for SES.")
        return False
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        logger.error(f"SES error sending to {to_email}: {error_code} - {error_message}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending email to {to_email}: {str(e)}")
        return False
