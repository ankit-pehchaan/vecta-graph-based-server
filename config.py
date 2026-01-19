"""
Configuration management for the application.
"""

import os
from pathlib import Path


# =============================================================================
# BRANCH DEFINITIONS FOR DFS TRAVERSAL
# =============================================================================
# Defines logical groupings of nodes for depth-first traversal.
# The system completes all nodes in a branch before moving to the next.

BRANCHES = {
    "life_topology": {
        "description": "Personal and family circumstances",
        "nodes": ["Personal", "Marriage", "Dependents"],
        "entry_node": "Personal",
    },
    "income_expenses": {
        "description": "Earning and spending structure",
        "nodes": ["Income", "Expenses", "Savings"],
        "entry_node": "Income",
    },
    "wealth": {
        "description": "Assets and liabilities",
        "nodes": ["Assets", "Loan"],
        "entry_node": "Assets",
    },
    "protection": {
        "description": "Insurance and retirement/superannuation",
        "nodes": ["Insurance", "Retirement"],
        "entry_node": "Insurance",
    },
}

# Default branch traversal order (can be overridden by goal context)
DEFAULT_BRANCH_ORDER = [
    "life_topology",
    "income_expenses",
    "wealth",
    "protection",
]

# Goal deduction happens after each branch completes
GOAL_DEDUCTION_POINTS = [
    "life_topology",      # Family-related goals (child_education, family_protection)
    "income_expenses",    # Cashflow-related goals (emergency_fund, debt_reduction)
    "wealth",             # Net worth goals (home_purchase, wealth_creation)
    "protection",         # Protection gap goals (insurance needs, retirement timeline)
]


def get_branch_for_node(node_name: str) -> str | None:
    """Get which branch a node belongs to."""
    for branch_name, branch_config in BRANCHES.items():
        if node_name in branch_config["nodes"]:
            return branch_name
    return None


def get_branch_nodes(branch_name: str) -> list[str]:
    """Get all nodes in a branch."""
    return BRANCHES.get(branch_name, {}).get("nodes", [])

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    
    # Load .env from project root
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
    else:
        # Try loading from current directory as fallback
        load_dotenv(override=True)
except ImportError:
    # python-dotenv not installed, skip loading .env
    pass


class Config:
    """Application configuration."""
    
    # Model configuration
    MODEL_ID: str = os.getenv("MODEL_ID", "gpt-4.1")
    
    # OpenAI API Key (required for agents)
    OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
    
    # Database paths
    DB_DIR: str = os.getenv("DB_DIR", "tmp")
    
    # API configuration
    CORS_ORIGINS: list[str] = os.getenv("CORS_ORIGINS", "*").split(",")
    
    @classmethod
    def get_db_path(cls, filename: str) -> str:
        """Get full database path."""
        os.makedirs(cls.DB_DIR, exist_ok=True)
        return os.path.join(cls.DB_DIR, filename)
    
    @classmethod
    def validate(cls) -> None:
        """Validate required configuration."""
        if not cls.OPENAI_API_KEY:
            raise ValueError(
                "OPENAI_API_KEY not set. Please set it in .env file or environment variable.\n"
                "Create a .env file in the project root with: OPENAI_API_KEY=your_key_here"
            )

