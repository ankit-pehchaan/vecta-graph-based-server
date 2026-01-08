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
    Estimate annual interest rate from EMI, principal, and tenure using bisection method.

    Uses the EMI formula: EMI = P × r × (1+r)^n / ((1+r)^n - 1)
    Where r = monthly rate, n = tenure in months, P = principal

    Args:
        principal: Loan amount (e.g., 30000)
        emi: Monthly EMI payment (e.g., 900)
        tenure_months: Loan term in months (e.g., 36)
        tolerance: Convergence tolerance for EMI match
        max_iterations: Maximum iterations for bisection

    Returns:
        Estimated annual interest rate as percentage (e.g., 8.5 for 8.5%)
        Returns 0.0 if inputs are invalid or rate cannot be determined
    """
    if principal <= 0 or emi <= 0 or tenure_months <= 0:
        return 0.0

    # If total payments equal principal (no interest), rate is 0
    total_payment = emi * tenure_months
    if total_payment <= principal:
        return 0.0

    def calculate_emi(monthly_rate: float) -> float:
        """Calculate EMI for given monthly rate."""
        if monthly_rate <= 0:
            return principal / tenure_months
        factor = (1 + monthly_rate) ** tenure_months
        return principal * monthly_rate * factor / (factor - 1)

    # Bisection method: find rate where calculated EMI matches actual EMI
    # Rate bounds: 0.01% to 50% annual (0.0000083 to 0.0417 monthly)
    low = 0.0001 / 12   # ~0.01% annual
    high = 0.50 / 12    # ~50% annual

    # Verify bounds bracket the solution
    emi_low = calculate_emi(low)
    emi_high = calculate_emi(high)

    if emi < emi_low or emi > emi_high:
        # EMI outside reasonable range, try wider bounds
        high = 1.0 / 12  # 100% annual
        emi_high = calculate_emi(high)
        if emi > emi_high:
            return 0.0  # Cannot determine - EMI too high for any reasonable rate

    # Bisection search
    for _ in range(max_iterations):
        mid = (low + high) / 2
        emi_mid = calculate_emi(mid)

        if abs(emi_mid - emi) < tolerance:
            break

        if emi_mid < emi:
            low = mid  # Need higher rate
        else:
            high = mid  # Need lower rate

    # Convert monthly rate to annual percentage
    annual_rate = mid * 12 * 100
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



