"""Reproducible synthetic CM04 HTML/PDF cases for browser checks (synthetic data only)."""
import argparse
from pathlib import Path
import unittest

from tests import test_cumulative_report_v4 as module
from tests import test_external_comparisons_v4 as external_fixture

OUTPUT = Path(".")


class Full(module.RenderedComparisonFixture):
    def test_write(self):
        self.define(external_fixture.SOURCE, "us2026-nonsocial-fear")
        b, c = self.others(module.B, module.C)
        self.pair(self.fixture.case_id, "a"); self.pair(b, "b"); self.pair(c, "c")
        write(self, "full")


class Single(module.RenderedComparisonFixture):
    def test_write(self):
        self.pair(self.fixture.case_id, "a")
        write(self, "single")


class Missing(module.RenderedComparisonFixture):
    target = dict(module.A, s11=None)

    def test_write(self):
        self.define("us2026-nonsocial-fear")
        b, c = self.others(module.B, module.C)
        self.pair(self.fixture.case_id, "a"); self.pair(b, "b"); self.pair(c, "c")
        write(self, "missing")


def write(case, name):
    run_id, _ = case.issue()
    html, pdf, _ = case.files(run_id)
    (OUTPUT / f"{name}.html").write_text(html, encoding="utf-8")
    (OUTPUT / f"{name}.pdf").write_bytes(pdf)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    OUTPUT = parser.parse_args().output
    OUTPUT.mkdir(parents=True, exist_ok=True)
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(kind) for kind in (Full, Single, Missing))
    if not unittest.TextTestRunner(verbosity=0).run(suite).wasSuccessful():
        raise SystemExit(1)
