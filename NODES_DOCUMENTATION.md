# Vecta - Data Collection Fields

## Node 1: Personal

- age
- occupation
- employment_type
- marital_status
- health_conditions

---

## Node 2: Marriage

- spouse_age
- spouse_employment_type
- spouse_income_annual

---

## Node 3: Dependents

- number_of_children
- children_ages
- annual_education_cost
- child_pathway
- education_funding_preference
- supporting_parents
- monthly_parent_support

---

## Node 4: Income

- income_streams_annual
- primary_income_type
- is_stable
- total_annual_income

**income_streams_annual keys:** salary, wages, business_income, rental_income, dividend_income, interest_income, capital_gains, super_pension, government_benefit, family_tax_benefit, other

---

## Node 5: Expenses

- monthly_expenses
- total_monthly

**monthly_expenses keys:** rent_mortgage, utilities, food, transport, insurance, education, entertainment, childcare, health, other

---

## Node 6: Savings

- total_savings
- emergency_fund_months

---

## Node 7: Assets

- asset_current_amount
- total_assets

**asset_current_amount keys:** property, investment_property, cash_deposits, superannuation, stocks_etfs, managed_funds, bonds, crypto, gold, vehicle, business, other

---

## Node 8: Liabilities (Loan)

- liabilities
- has_debt
- total_outstanding
- total_monthly_payments

**liabilities keys:** home_loan, investment_property_loan, personal_loan, car_loan, credit_card, line_of_credit, buy_now_pay_later, hecs_help, business_loan, tax_liability, other

**LiabilityDetails object fields:**
- outstanding_amount
- monthly_payment
- interest_rate
- remaining_term_months

---

## Node 9: Insurance

- coverages
- has_life_insurance
- has_tpd_insurance
- has_income_protection
- has_private_health
- spouse_has_life_insurance
- spouse_has_income_protection

**coverages keys:** life, tpd, income_protection, trauma, private_health, home, contents, car, landlord

**InsuranceCoverage object fields:**
- covered_person
- held_through
- coverage_amount
- premium_amount
- premium_frequency
- waiting_period_weeks
- benefit_period_months
- excess_amount

---

## Node 10: Retirement

- super_balance
- super_account_type
- employer_contribution_rate
- salary_sacrifice_monthly
- personal_contribution_monthly
- spouse_super_balance
- target_retirement_age
- target_retirement_amount
- investment_option

---

## Node 11: Goals

- goal_type
- target_amount
- target_year
- priority
- status

**goal_type values:**
- retirement, early_retirement
- home_purchase, investment_property, home_renovation
- child_education, child_wedding, starting_family, aged_care
- life_insurance, tpd_insurance, income_protection, health_insurance
- travel, wedding, vehicle_purchase, major_purchase
- business_start, wealth_creation, debt_free, emergency_fund
- self_education
- other
