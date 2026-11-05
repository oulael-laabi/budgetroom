"""Run: python3 -m unittest discover tests"""
import io, os, shutil, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class BudgetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        shutil.copytree(REPO / "seed", Path(self.tmp) / "data")
        os.environ["BUDGET_DATA"] = str(Path(self.tmp) / "data")
        os.environ["BUDGET_TODAY"] = "2026-11-05"
        sys.path.insert(0, str(REPO))
        import budget
        budget.ROOT = Path(os.environ["BUDGET_DATA"])
        self.b = budget

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = self.b.main(list(args))
        return code, buf.getvalue()

    def test_snapshot_math(self):
        snap = self.b.snapshot(self.b.load_profile("yasmine"))
        # 3000 income - 1250 fixed - 150 savings = 1600 flexible; rent/phone excluded
        self.assertEqual(snap["flex_budget"], 1600)
        self.assertEqual(snap["flex_spent"], 630)
        self.assertEqual(snap["days_left"], 26)

    def test_extra_income_raises_budget(self):
        snap = self.b.snapshot(self.b.load_profile("lea"))
        self.assertAlmostEqual(snap["flex_budget"], 550)

    def test_afford_verdicts(self):
        p = self.b.load_profile("yasmine")
        self.assertEqual(self.b.afford(self.b.load_profile("lea"), 10)["verdict"], "yes")
        self.assertEqual(self.b.afford(p, 20)["verdict"], "tight")  # already behind pace
        self.assertEqual(self.b.afford(p, 100)["verdict"], "tight")
        self.assertEqual(self.b.afford(p, 2000)["verdict"], "no")
        self.assertIsNotNone(self.b.afford(p, 350, "leisure")["cat_warning"])

    def test_add_and_undo(self):
        code, out = self.run_cli("add", "yasmine", "85", "food", "groceries")
        self.assertEqual(code, 0)
        self.assertIn("375 MAD", out)
        self.run_cli("undo", "yasmine")
        self.assertEqual(len(self.b.read_ledger("yasmine")), 10)

    def test_allowance_flow(self):
        self.run_cli("request", "yasmine", "300", "train ticket")
        code, out = self.run_cli("approve", "karim", "1")
        self.assertIn("approved", out)
        self.assertEqual(self.b.read_ledger("yasmine")[-1]["type"], "income")
        self.assertEqual(self.b.read_ledger("karim")[-1]["category"], "family")
        code, _ = self.run_cli("approve", "karim", "1")
        self.assertEqual(code, 1)  # cannot approve twice

    def test_child_cannot_approve(self):
        self.run_cli("request", "yasmine", "100", "books")
        code, _ = self.run_cli("approve", "yasmine", "1")
        self.assertEqual(code, 1)

    def test_currency_format(self):
        self.assertEqual(self.b.money(1200, "MAD"), "1,200 MAD")
        self.assertEqual(self.b.money(12.5, "EUR"), "€12.50")
        self.assertEqual(self.b.money(-3, "USD"), "-$3")


if __name__ == "__main__":
    unittest.main()
