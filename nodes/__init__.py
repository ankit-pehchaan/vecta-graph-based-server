"""
Financial Life Knowledge Graph - Node System (Australian Market)

This package provides a comprehensive node-based graph structure for
representing a user's financial life, including personal information,
family structure, financial situation, assets, liabilities, goals,
insurance, and retirement planning.

All nodes are Pydantic BaseModel classes for validation and LLM-friendly
serialization. Relationships are represented as separate Edge objects,
enabling flexible graph modeling with hybrid in-memory/DB storage support.

Production-grade for Australian personal finance:
- Multi-stream income (salary, rental, dividends)
- Portfolio-style assets, liabilities, insurance
- Australian superannuation and insurance taxonomy
"""

# Base classes
from nodes.base import BaseGraph, BaseNode, Edge

# Personal information
from nodes.personal import EmploymentType, MaritalStatus, Personal

# Family nodes (Marriage = spouse financial details, Dependents = children/parents)
from nodes.family import Dependents, Marriage

# Financial nodes (Income supports multi-stream, Expenses by category)
from nodes.financial import Expenses, Income, IncomeType, Savings, TaxCategory

# Asset nodes (portfolio-style, multi-category)
from nodes.assets import AssetCategory, Assets

# Liability nodes (portfolio-style, multi-debt)
from nodes.liabilities import LiabilityType, Loan

# Insurance nodes (portfolio-style, AU taxonomy)
from nodes.insurance import (
    CoveredPerson,
    Insurance,
    InsuranceHolder,
    InsurancePolicy,  # Alias for backward compatibility
    InsuranceType,
)

# Retirement / Superannuation nodes (AU-specific)
from nodes.retirement import (
    Retirement,
    SuperAccountType,
    SuperContributionType,
)

__all__ = [
    # Base classes (not used as data collection nodes)
    "BaseNode",
    "Edge",
    "BaseGraph",
    # Personal
    "Personal",
    "EmploymentType",
    "MaritalStatus",
    # Family
    "Marriage",
    "Dependents",
    # Financial (Income, Expenses, Savings)
    "Income",
    "IncomeType",
    "TaxCategory",
    "Expenses",
    "Savings",
    # Assets
    "Assets",
    "AssetCategory",
    # Liabilities
    "Loan",
    "LiabilityType",
    # Insurance (AU taxonomy)
    "Insurance",
    "InsurancePolicy",  # Alias for backward compatibility
    "InsuranceType",
    "InsuranceHolder",
    "CoveredPerson",
    # Retirement / Superannuation
    "Retirement",
    "SuperAccountType",
    "SuperContributionType",
]
