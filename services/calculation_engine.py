"""
Calculation engine for deterministic financial computations (AU context).

This module is LLM-free and provides validation + calculation for a set of
non-super calculators. It is intended for internal use by the orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable


CalculationInputs = dict[str, Any]
CalculationResult = dict[str, Any]
Validator = Callable[[CalculationInputs], list[str]]
Calculator = Callable[[CalculationInputs], CalculationResult]


@dataclass(frozen=True)
class CalculatorSpec:
    name: str
    validator: Validator
    calculator: Calculator


def _missing(inputs: CalculationInputs, fields: list[str]) -> list[str]:
    return [f for f in fields if inputs.get(f) in (None, "", [])]


# === Core Calculators ===
def _validate_budget(inputs: CalculationInputs) -> list[str]:
    return _missing(inputs, ["income", "expenses"])


def _budget(inputs: CalculationInputs) -> CalculationResult:
    income = float(inputs["income"])
    expenses = float(inputs["expenses"])
    return {
        "surplus": income - expenses,
        "income": income,
        "expenses": expenses,
    }


def _validate_net_worth(inputs: CalculationInputs) -> list[str]:
    return _missing(inputs, ["assets", "liabilities"])


def _net_worth(inputs: CalculationInputs) -> CalculationResult:
    assets = float(inputs["assets"])
    liabilities = float(inputs["liabilities"])
    return {
        "net_worth": assets - liabilities,
        "assets": assets,
        "liabilities": liabilities,
    }


def _validate_savings_goal(inputs: CalculationInputs) -> list[str]:
    return _missing(inputs, ["target_amount", "monthly_contribution", "annual_rate"])


def _savings_goal(inputs: CalculationInputs) -> CalculationResult:
    target = float(inputs["target_amount"])
    contrib = float(inputs["monthly_contribution"])
    rate = float(inputs["annual_rate"]) / 12.0
    if contrib <= 0:
        months = None
    elif rate == 0:
        months = target / contrib
    else:
        ratio = (target * rate / contrib) + 1.0
        if ratio <= 0:
            months = None
        else:
            months = math.log(ratio) / math.log(1.0 + rate)
    return {"target_amount": target, "monthly_contribution": contrib, "monthly_rate": rate, "months": months}


def _validate_compound_interest(inputs: CalculationInputs) -> list[str]:
    return _missing(inputs, ["principal", "annual_rate", "years"])


def _compound_interest(inputs: CalculationInputs) -> CalculationResult:
    principal = float(inputs["principal"])
    rate = float(inputs["annual_rate"])
    years = float(inputs["years"])
    n = float(inputs.get("compounds_per_year", 12))
    amount = principal * (1 + rate / n) ** (n * years)
    return {"future_value": amount, "principal": principal, "interest_earned": amount - principal}


def _validate_debt_repayment(inputs: CalculationInputs) -> list[str]:
    return _missing(inputs, ["balance", "annual_rate", "monthly_payment"])


def _debt_repayment(inputs: CalculationInputs) -> CalculationResult:
    balance = float(inputs["balance"])
    rate = float(inputs["annual_rate"]) / 12.0
    payment = float(inputs["monthly_payment"])
    if payment <= 0:
        return {"months": None, "total_interest": None}
    months = 0
    total_interest = 0.0
    remaining = balance
    while remaining > 0 and months < 1000:
        interest = remaining * rate
        total_interest += interest
        remaining = remaining + interest - payment
        months += 1
        if remaining < 0:
            remaining = 0
    return {"months": months, "total_interest": total_interest, "starting_balance": balance}




def _validate_loan(inputs: CalculationInputs) -> list[str]:
    return _missing(inputs, ["principal", "annual_rate", "years"])


def _loan(inputs: CalculationInputs) -> CalculationResult:
    principal = float(inputs["principal"])
    rate = float(inputs["annual_rate"]) / 12.0
    months = int(float(inputs["years"]) * 12)
    if rate == 0:
        payment = principal / months
    else:
        payment = principal * rate * (1 + rate) ** months / ((1 + rate) ** months - 1)
    total_paid = payment * months
    return {"monthly_payment": payment, "total_paid": total_paid, "total_interest": total_paid - principal}


def _validate_affordability(inputs: CalculationInputs) -> list[str]:
    return _missing(inputs, ["income", "expenses", "annual_rate", "years"])


def _loan_affordability(inputs: CalculationInputs) -> CalculationResult:
    income = float(inputs["income"])
    expenses = float(inputs["expenses"])
    surplus = income - expenses
    rate = float(inputs["annual_rate"]) / 12.0
    months = int(float(inputs["years"]) * 12)
    if surplus <= 0:
        return {"max_borrowing": 0}
    if rate == 0:
        return {"max_borrowing": surplus * months}
    max_borrow = surplus * ((1 + rate) ** months - 1) / (rate * (1 + rate) ** months)
    return {"max_borrowing": max_borrow}


def _validate_credit_card(inputs: CalculationInputs) -> list[str]:
    return _missing(inputs, ["balance", "annual_rate", "monthly_payment"])


def _credit_card_payoff(inputs: CalculationInputs) -> CalculationResult:
    return _debt_repayment(inputs)


def _validate_retirement(inputs: CalculationInputs) -> list[str]:
    return _missing(inputs, ["current_savings", "annual_contribution", "annual_return", "years_to_retire", "annual_spending"])


def _retirement(inputs: CalculationInputs) -> CalculationResult:
    current = float(inputs["current_savings"])
    contrib = float(inputs["annual_contribution"])
    rate = float(inputs["annual_return"])
    years = float(inputs["years_to_retire"])
    spending = float(inputs["annual_spending"])
    withdrawal_rate = float(inputs.get("withdrawal_rate", 0.04))
    required = spending / withdrawal_rate if withdrawal_rate > 0 else None
    if rate == 0:
        projected = current + contrib * years
    else:
        projected = current * (1 + rate) ** years + contrib * (((1 + rate) ** years - 1) / rate)
    gap = required - projected if required is not None else None
    return {
        "required_corpus": required,
        "projected_corpus": projected,
        "gap": gap,
        "years_to_retire": years,
    }


def _validate_rent_vs_buy(inputs: CalculationInputs) -> list[str]:
    return _missing(inputs, ["rent_monthly", "home_price", "deposit", "annual_rate", "years", "annual_maintenance"])


def _rent_vs_buy(inputs: CalculationInputs) -> CalculationResult:
    rent = float(inputs["rent_monthly"])
    price = float(inputs["home_price"])
    deposit = float(inputs["deposit"])
    rate = float(inputs["annual_rate"])
    years = float(inputs["years"])
    maintenance = float(inputs["annual_maintenance"])
    loan_principal = max(0.0, price - deposit)
    loan = _loan({"principal": loan_principal, "annual_rate": rate, "years": years})
    total_rent = rent * 12.0 * years
    total_buy_cost = loan["total_interest"] + maintenance * years
    return {
        "total_rent_cost": total_rent,
        "total_buy_interest": loan["total_interest"],
        "total_buy_cost": total_buy_cost,
        "monthly_mortgage": loan["monthly_payment"],
    }


def _validate_investment_return(inputs: CalculationInputs) -> list[str]:
    return _missing(inputs, ["initial_value", "final_value", "years"])


def _investment_return(inputs: CalculationInputs) -> CalculationResult:
    initial = float(inputs["initial_value"])
    final = float(inputs["final_value"])
    years = float(inputs["years"])
    if initial <= 0 or years <= 0:
        cagr = None
    else:
        cagr = (final / initial) ** (1 / years) - 1
    return {"cagr": cagr, "total_return": final - initial, "final_value": final}


def _validate_rental_yield(inputs: CalculationInputs) -> list[str]:
    return _missing(inputs, ["annual_rent", "property_value"])


def _rental_yield(inputs: CalculationInputs) -> CalculationResult:
    annual_rent = float(inputs["annual_rent"])
    value = float(inputs["property_value"])
    return {"rental_yield": annual_rent / value if value else None}


def _validate_property_loan_compare(inputs: CalculationInputs) -> list[str]:
    return _missing(inputs, ["principal", "owner_rate", "investor_rate", "years"])


def _property_loan_compare(inputs: CalculationInputs) -> CalculationResult:
    principal = float(inputs["principal"])
    years = float(inputs["years"])
    owner = _loan({"principal": principal, "annual_rate": float(inputs["owner_rate"]), "years": years})
    investor = _loan({"principal": principal, "annual_rate": float(inputs["investor_rate"]), "years": years})
    return {"owner": owner, "investor": investor}


def _validate_insurance_needs(inputs: CalculationInputs) -> list[str]:
    return _missing(inputs, ["annual_income", "years_support", "debt"])


def _insurance_needs(inputs: CalculationInputs) -> CalculationResult:
    income = float(inputs["annual_income"])
    years_support = float(inputs["years_support"])
    debt = float(inputs["debt"])
    need = income * years_support + debt
    return {"coverage_needed": need}


def _validate_inflation(inputs: CalculationInputs) -> list[str]:
    return _missing(inputs, ["amount_today", "annual_inflation", "years"])


def _inflation(inputs: CalculationInputs) -> CalculationResult:
    amount = float(inputs["amount_today"])
    rate = float(inputs["annual_inflation"])
    years = float(inputs["years"])
    future = amount * (1 + rate) ** years
    return {"future_value": future, "amount_today": amount}


def _validate_emergency_fund(inputs: CalculationInputs) -> list[str]:
    return _missing(inputs, ["monthly_expenses", "months"])


def _emergency_fund(inputs: CalculationInputs) -> CalculationResult:
    monthly = float(inputs["monthly_expenses"])
    months = float(inputs["months"])
    return {"target_amount": monthly * months, "months": months}


CALCULATORS: dict[str, CalculatorSpec] = {
    "budget": CalculatorSpec("budget", _validate_budget, _budget),
    "net_worth": CalculatorSpec("net_worth", _validate_net_worth, _net_worth),
    "savings_goal": CalculatorSpec("savings_goal", _validate_savings_goal, _savings_goal),
    "compound_interest": CalculatorSpec("compound_interest", _validate_compound_interest, _compound_interest),
    "debt_repayment": CalculatorSpec("debt_repayment", _validate_debt_repayment, _debt_repayment),
    "mortgage": CalculatorSpec("mortgage", _validate_loan, _loan),
    "loan": CalculatorSpec("loan", _validate_loan, _loan),
    "loan_affordability": CalculatorSpec("loan_affordability", _validate_affordability, _loan_affordability),
    "credit_card_payoff": CalculatorSpec("credit_card_payoff", _validate_credit_card, _credit_card_payoff),
    "retirement": CalculatorSpec("retirement", _validate_retirement, _retirement),
    "rent_vs_buy": CalculatorSpec("rent_vs_buy", _validate_rent_vs_buy, _rent_vs_buy),
    "investment_return": CalculatorSpec("investment_return", _validate_investment_return, _investment_return),
    "rental_yield": CalculatorSpec("rental_yield", _validate_rental_yield, _rental_yield),
    "property_loan_compare": CalculatorSpec("property_loan_compare", _validate_property_loan_compare, _property_loan_compare),
    "insurance_needs": CalculatorSpec("insurance_needs", _validate_insurance_needs, _insurance_needs),
    "inflation": CalculatorSpec("inflation", _validate_inflation, _inflation),
    "emergency_fund": CalculatorSpec("emergency_fund", _validate_emergency_fund, _emergency_fund),
}


def validate_inputs(calc_type: str, inputs: CalculationInputs) -> list[str]:
    if calc_type not in CALCULATORS:
        return ["calculation_type"]
    return CALCULATORS[calc_type].validator(inputs)


def calculate(calc_type: str, inputs: CalculationInputs) -> CalculationResult:
    if calc_type not in CALCULATORS:
        raise ValueError(f"Unknown calculation type: {calc_type}")
    return CALCULATORS[calc_type].calculator(inputs)

