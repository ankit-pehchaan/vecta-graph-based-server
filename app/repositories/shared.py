"""Shared repository instances for the application.

All services should use these shared instances to ensure data consistency.
"""
from app.repositories.memory import InMemoryUserRepository
from app.repositories.financial_profile import InMemoryFinancialProfileRepository

# Singleton instances - shared across all services
user_repository = InMemoryUserRepository()
profile_repository = InMemoryFinancialProfileRepository()

