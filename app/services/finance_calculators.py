from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np


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


@dataclass(frozen=True)
class MonteCarloResult:
    """Result of Monte Carlo simulation."""
    percentile_10: list[float]   # Conservative scenario
    percentile_25: list[float]   # Below median
    percentile_50: list[float]   # Median (expected)
    percentile_75: list[float]   # Above median
    percentile_90: list[float]   # Optimistic scenario
    years: list[int]             # Time points (0, 1, 2, ... N)
    final_median: float
    final_mean: float
    probability_of_success: float  # % of simulations meeting target
    initial_value: float
    monthly_contribution: float
    expected_return: float
    volatility: float
    num_simulations: int


# Risk profile presets for Monte Carlo simulations
MONTE_CARLO_PRESETS: dict[str, dict[str, float]] = {
    "conservative": {"expected_return": 5.0, "volatility": 8.0},
    "balanced": {"expected_return": 7.0, "volatility": 12.0},
    "growth": {"expected_return": 9.0, "volatility": 18.0},
    "aggressive": {"expected_return": 11.0, "volatility": 25.0},
}


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


def monte_carlo_projection(
    initial_value: float,
    monthly_contribution: float,
    years: int,
    expected_return_percent: float,
    volatility_percent: float,
    num_simulations: int = 1000,
    target_value: Optional[float] = None,
    seed: Optional[int] = None,
) -> MonteCarloResult:
    """
    Run Monte Carlo simulation for investment/retirement projections.

    Uses geometric Brownian motion model:
    - Monthly returns drawn from log-normal distribution
    - Contributions added monthly

    Args:
        initial_value: Starting portfolio value
        monthly_contribution: Regular monthly investment
        years: Projection horizon
        expected_return_percent: Annual expected return as percent (e.g., 7.0)
        volatility_percent: Annual volatility as percent (e.g., 15.0)
        num_simulations: Number of simulation paths (default 1000)
        target_value: Optional target for success probability calculation
        seed: Optional random seed for reproducibility

    Returns:
        MonteCarloResult with percentile trajectories
    """
    if seed is not None:
        np.random.seed(seed)

    # Convert annual parameters to monthly
    monthly_return = (expected_return_percent / 100) / 12
    monthly_volatility = (volatility_percent / 100) / np.sqrt(12)

    months = years * 12

    # Initialize simulation array: (num_simulations, months + 1)
    simulations = np.zeros((num_simulations, months + 1))
    simulations[:, 0] = initial_value

    # Generate random returns using geometric Brownian motion
    for month in range(1, months + 1):
        # Random monthly returns (log-normal via normal of log-returns)
        random_returns = np.random.normal(
            monthly_return - 0.5 * monthly_volatility**2,  # Drift adjustment
            monthly_volatility,
            num_simulations
        )

        # Apply returns and add contribution
        simulations[:, month] = (
            simulations[:, month - 1] * np.exp(random_returns)
            + monthly_contribution
        )

    # Downsample to yearly for visualization
    yearly_indices = [i * 12 for i in range(years + 1)]
    yearly_simulations = simulations[:, yearly_indices]

    # Calculate percentiles at each year
    percentiles = np.percentile(yearly_simulations, [10, 25, 50, 75, 90], axis=0)

    # Calculate success probability if target provided
    success_prob = 0.0
    if target_value is not None and target_value > 0:
        success_count = np.sum(simulations[:, -1] >= target_value)
        success_prob = (success_count / num_simulations) * 100

    return MonteCarloResult(
        percentile_10=percentiles[0].tolist(),
        percentile_25=percentiles[1].tolist(),
        percentile_50=percentiles[2].tolist(),
        percentile_75=percentiles[3].tolist(),
        percentile_90=percentiles[4].tolist(),
        years=list(range(years + 1)),
        final_median=float(percentiles[2, -1]),
        final_mean=float(np.mean(simulations[:, -1])),
        probability_of_success=success_prob,
        initial_value=initial_value,
        monthly_contribution=monthly_contribution,
        expected_return=expected_return_percent,
        volatility=volatility_percent,
        num_simulations=num_simulations,
    )


def retirement_projection(
    current_age: int,
    retirement_age: int,
    current_super: float,
    annual_salary: float,
    employer_contribution_rate: float = 11.5,
    personal_contribution_rate: float = 0.0,
    risk_profile: Literal["conservative", "balanced", "growth", "aggressive"] = "balanced",
    target_retirement_balance: Optional[float] = None,
) -> MonteCarloResult:
    """
    Specialized Monte Carlo for Australian superannuation projection.

    Args:
        current_age: User's current age
        retirement_age: Target retirement age
        current_super: Current superannuation balance
        annual_salary: Annual salary for contribution calculation
        employer_contribution_rate: Super guarantee rate (percent, default 11.5%)
        personal_contribution_rate: Additional personal contribution (percent)
        risk_profile: Investment risk profile
        target_retirement_balance: Optional target for success probability

    Returns:
        MonteCarloResult with retirement projections
    """
    years = retirement_age - current_age
    if years <= 0:
        raise ValueError("Retirement age must be greater than current age")

    # Calculate monthly contributions
    total_contribution_rate = employer_contribution_rate + personal_contribution_rate
    annual_contribution = annual_salary * (total_contribution_rate / 100)
    monthly_contribution = annual_contribution / 12

    # Get preset parameters
    preset = MONTE_CARLO_PRESETS.get(risk_profile, MONTE_CARLO_PRESETS["balanced"])

    return monte_carlo_projection(
        initial_value=current_super,
        monthly_contribution=monthly_contribution,
        years=years,
        expected_return_percent=preset["expected_return"],
        volatility_percent=preset["volatility"],
        target_value=target_retirement_balance,
    )


def goal_projection(
    goal_amount: float,
    current_savings: float,
    monthly_savings: float,
    timeline_years: int,
    risk_profile: Literal["conservative", "balanced", "growth"] = "balanced",
) -> MonteCarloResult:
    """
    Monte Carlo projection for general savings goals.

    Returns probability of achieving goal and percentile trajectories.
    """
    preset = MONTE_CARLO_PRESETS.get(risk_profile, MONTE_CARLO_PRESETS["balanced"])

    return monte_carlo_projection(
        initial_value=current_savings,
        monthly_contribution=monthly_savings,
        years=timeline_years,
        expected_return_percent=preset["expected_return"],
        volatility_percent=preset["volatility"],
        target_value=goal_amount,
    )

