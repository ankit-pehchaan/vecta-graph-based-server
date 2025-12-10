from abc import ABC, abstractmethod
from typing import Optional


class IVerificationRepository(ABC):
    @abstractmethod
    async def save(self, token: str, email: str, data: dict) -> dict:
        """Save pending verification data.
        
        Args:
            token: Unique verification token (UUID)
            email: User's email address
            data: Verification data including name, username, password, otp, etc.
            
        Returns:
            The saved verification data
        """
        pass

    @abstractmethod
    async def get_by_token(self, token: str) -> Optional[dict]:
        """Retrieve pending verification by token.
        
        Args:
            token: Verification token
            
        Returns:
            Verification data if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_by_email(self, email: str) -> Optional[dict]:
        """Retrieve pending verification by email.
        
        Args:
            email: User's email address
            
        Returns:
            Verification data if found, None otherwise
        """
        pass

    @abstractmethod
    async def delete_by_token(self, token: str) -> None:
        """Delete pending verification by token.
        
        Args:
            token: Verification token
        """
        pass

    @abstractmethod
    async def delete_by_email(self, email: str) -> None:
        """Delete pending verification by email.
        
        Args:
            email: User's email address
        """
        pass

    @abstractmethod
    async def increment_attempts(self, token: str) -> None:
        """Increment failed verification attempts.

        Args:
            token: Verification token
        """
        pass

    @abstractmethod
    async def update_otp(self, token: str, new_otp: str) -> bool:
        """Update OTP and reset attempts for a verification token.

        Args:
            token: Verification token
            new_otp: New OTP to set

        Returns:
            True if updated successfully, False otherwise
        """
        pass
