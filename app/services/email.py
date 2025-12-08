"""Email service for sending OTP and other notifications."""


async def send_otp_email(email: str, otp: str) -> bool:
    """
    Send OTP to user's email address.
    
    A mock implementation that prints to console.
    In production, this will integrate with email providers
    
    Args:
        email: Recipient email address
        otp: One-time password to send
        
    Returns:
        True if email sent successfully, False otherwise
    """
    print(f"   Sending OTP to {email}: {otp}")
    print(f"   Subject: Verify Your Email")
    print(f"   Body: Your verification code is: {otp}")
    print(f"   This code will expire in 3 minutes.")
    return True
