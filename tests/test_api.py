"""Run with:  python -m unittest discover tests -v   (or: python -m campus.selftests)"""
import unittest

from campus.selftests import CASES, Ctx


class TestCampusApp(unittest.TestCase):
    pass


def _make(case):
    def t(self):
        case["fn"](Ctx())
    return t


for _c in CASES:
    setattr(TestCampusApp, f"test_{_c['id'].replace('-', '_')}_{_c['type'].lower()}", _make(_c))

if __name__ == "__main__":
    unittest.main()
