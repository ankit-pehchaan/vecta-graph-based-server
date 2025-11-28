from typing import Optional
from app.interfaces.user_repository import IUserRepository


class InMemoryUserRepository(IUserRepository):
    def __init__(self):
        self._users: dict[str, dict] = {}

    async def get_by_username(self, username: str) -> Optional[dict]:
        """Retrieve a user by username."""
        return self._users.get(username)

    async def save(self, user_data: dict) -> dict:
        """Save user data and return the saved user."""
        username = user_data["username"]
        self._users[username] = user_data
        return user_data
