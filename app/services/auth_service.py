from app.interfaces.user_repository import IUserRepository
from app.core.security import get_password_hash, create_access_token, create_refresh_token
from app.core.exceptions import UserAlreadyExistsException
from app.core.constants import ErrorDetails


class AuthService:
    def __init__(self, user_repository: IUserRepository):
        self.user_repository = user_repository

    async def register_user(self, username: str, password: str) -> dict:
        """Register a new user with hashed password and return tokens."""
        # Check if user already exists
        existing_user = await self.user_repository.get_by_username(username)
        if existing_user:
            raise UserAlreadyExistsException(
                message=ErrorDetails.USER_ALREADY_EXISTS,
                data={"username": username, "detail": ErrorDetails.USER_ALREADY_EXISTS}
            )

        # Hash the password
        hashed_password = get_password_hash(password)

        # Save user to repository
        user_data = {
            "username": username,
            "hashed_password": hashed_password
        }
        saved_user = await self.user_repository.save(user_data)
        
        # Generate tokens
        token_data = {"sub": username}
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)
        
        return {
            "user": saved_user,
            "access_token": access_token,
            "refresh_token": refresh_token
        }
