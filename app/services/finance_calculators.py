from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


FREQUENCY_PER_YEAR: dict[str, int] = {
    "weekly": 52,
    "fortnightly": 26,
    "monthly": 12,
}


@dataclass(frozen=True)
class LoanScheduleSummary:
    total_paid: float
    total_interest: float
    total_principal: float
    periods: int
    payoff_periods: int


def pmt(principal: float, rate_per_period: float, num_periods: int) -> float:
    """Standard amortizing payment (without extra payments)."""
    if num_periods <= 0:
        return 0.0
    if rate_per_period == 0:
        return principal / num_periods
    denom = 1 - (1 + rate_per_period) ** (-num_periods)
    if denom == 0:
        return principal / num_periods
    return principal * (rate_per_period / denom)


def estimate_interest_rate(
    principal: float,
    emi: float,
    tenure_months: int,
    tolerance: float = 0.0001,
    max_iterations: int = 100
) -> float:
    """
    Estimate annual interest rate from EMI, principal, and tenure using Newton-Raphson.

    Args:
        principal: Loan amount
        emi: Monthly EMI payment
        tenure_months: Loan term in months
        tolerance: Convergence tolerance
        max_iterations: Maximum iterations

    Returns:
        Estimated annual interest rate as percentage (e.g., 8.5 for 8.5%)
    """
    if principal <= 0 or emi <= 0 or tenure_months <= 0:
        return 0.0

    # If total payments equal principal, rate is ~0
    if abs(emi * tenure_months - principal) < 1:
        return 0.0

    # Initial guess: 10% annual = ~0.83% monthly
    r = 0.01  # monthly rate guess

    for _ in range(max_iterations):
        # PMT formula rearranged: EMI = P * r * (1+r)^n / ((1+r)^n - 1)
        # We want to find r such that PMT(P, r, n) = EMI

        factor = (1 + r) ** tenure_months
        calculated_emi = principal * r * factor / (factor - 1)

        # Derivative of PMT with respect to r (for Newton-Raphson)
        # This is complex, so we use secant method instead
        diff = calculated_emi - emi

        if abs(diff) < tolerance:
            break

        # Adjust rate based on difference
        if calculated_emi > emi:
            r *= 0.95  # Rate too high
        else:
            r *= 1.05  # Rate too low

        # Clamp to reasonable bounds
        r = max(0.0001, min(r, 0.05))  # 0.01% to 60% annual

    # Convert monthly rate to annual percentage
    annual_rate = r * 12 * 100
    return round(annual_rate, 2)


def amortize_balance_trajectory(
    principal: float,
    annual_rate_percent: float,
    term_years: int,
    payment_frequency: Literal["weekly", "fortnightly", "monthly"],
    extra_payment: float = 0.0,
) -> tuple[list[float], LoanScheduleSummary]:
    """
    Compute remaining balance trajectory per period.

    Returns:
        balances: list of remaining balance at each period boundary (including period 0).
        summary: totals and payoff info.
    """
    freq = FREQUENCY_PER_YEAR[payment_frequency]
    n = int(term_years * freq)
    r = max(0.0, annual_rate_percent) / 100.0
    i = r / freq

    base_payment = pmt(principal, i, n)
    payment = base_payment + max(0.0, extra_payment)

    balance = float(principal)
    balances = [balance]
    total_interest = 0.0
    total_principal = 0.0
    total_paid = 0.0
    payoff_period = n

    for period in range(1, n + 1):
        interest = balance * i
        principal_paid = payment - interest
        if principal_paid < 0:
            # Payment doesn't cover interest (invalid scenario); stop principal paydown.
            principal_paid = 0.0

        if principal_paid >= balance:
            # final payment
            principal_paid = balance
            paid_this_period = principal_paid + interest
            balance = 0.0
            total_paid += paid_this_period
            total_interest += interest
            total_principal += principal_paid
            balances.append(balance)
            payoff_period = period
            break

        balance -= principal_paid
        total_paid += payment
        total_interest += interest
        total_principal += principal_paid
        balances.append(balance)

    summary = LoanScheduleSummary(
        total_paid=total_paid,
        total_interest=total_interest,
        total_principal=total_principal,
        periods=n,
        payoff_periods=payoff_period,
    )
    return balances, summary



