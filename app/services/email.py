"""Email service for sending OTP and other notifications."""

import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import settings


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
                <h1>🔐 Email Verification</h1>
                <p>Welcome to {settings.SMTP_FROM_NAME}!</p>
            </div>
            
            <p>Thank you for registering. Please use the verification code below to complete your registration:</p>
            
            <div class="otp-box">
                <p>Your verification code is:</p>
                <div class="otp-code">{otp}</div>
            </div>
            
            <p><span class="warning">⚠️ This code will expire in {settings.OTP_EXPIRY_MINUTES} minutes.</span></p>
            
            <p>If you didn't request this code, please ignore this email.</p>
            
            <div class="footer">
                <p>This is an automated message, please do not reply.</p>
                <p>&copy; 2024 {settings.SMTP_FROM_NAME}. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """


async def send_otp_email(email: str, otp: str) -> bool:
    """
    Send OTP to user's email address via SMTP.
    
    Args:
        email: Recipient email address
        otp: One-time password to send
        
    Returns:
        True if email sent successfully, False otherwise
    """
    try:
        # Create message
        message = MIMEMultipart("alternative")
        message["Subject"] = f"Your {settings.SMTP_FROM_NAME} Verification Code"
        message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        message["To"] = email
        
        # Create plain text version
        text_content = f"""
        Welcome to {settings.SMTP_FROM_NAME}!
        
        Your verification code is: {otp}
        
        This code will expire in {settings.OTP_EXPIRY_MINUTES} minutes.
        
        If you didn't request this code, please ignore this email.
        """
        
        # Create HTML version
        html_content = _create_otp_email_html(otp)
        
        # Attach both versions
        part1 = MIMEText(text_content, "plain")
        part2 = MIMEText(html_content, "html")
        message.attach(part1)
        message.attach(part2)
        
        # Send email
        await aiosmtplib.send(
            message,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USERNAME,
            password=settings.SMTP_PASSWORD,
            start_tls=True,
        )
        
        print(f"✅ OTP email sent successfully to {email}")
        return True
        
    except Exception as e:
        print(f"Failed to send OTP email to {email}: {str(e)}")
        return False
