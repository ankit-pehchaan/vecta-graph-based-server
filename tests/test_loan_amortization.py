import unittest


from app.services.finance_calculators import amortize_balance_trajectory


class TestLoanAmortization(unittest.TestCase):
    def test_monthly_loan_interest_reasonable(self):
        balances, summary = amortize_balance_trajectory(
            principal=10_000,
            annual_rate_percent=5.0,
            term_years=10,
            payment_frequency="monthly",
            extra_payment=0.0,
        )

        # Balance hits (or is extremely close to) zero
        self.assertAlmostEqual(balances[-1], 0.0, places=6)

        # Total principal paid ~= principal
        self.assertAlmostEqual(summary.total_principal, 10_000.0, places=2)

        # Payment count should be <= scheduled
        self.assertLessEqual(summary.payoff_periods, summary.periods)

        # Total interest for this scenario is in a sane range (approx ~2.73k)
        self.assertGreater(summary.total_interest, 2_000.0)
        self.assertLess(summary.total_interest, 3_200.0)

    def test_extra_payment_reduces_interest_and_term(self):
        _, base = amortize_balance_trajectory(
            principal=10_000,
            annual_rate_percent=5.0,
            term_years=10,
            payment_frequency="monthly",
            extra_payment=0.0,
        )
        _, extra = amortize_balance_trajectory(
            principal=10_000,
            annual_rate_percent=5.0,
            term_years=10,
            payment_frequency="monthly",
            extra_payment=50.0,
        )

        self.assertLess(extra.total_interest, base.total_interest)
        self.assertLess(extra.payoff_periods, base.payoff_periods)


if __name__ == "__main__":
    unittest.main()


