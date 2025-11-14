import unittest

from freemad import load_config
from freemad import ValidationManager


class TestValidationEnums(unittest.TestCase):
    def test_validator_names_keys(self):
        cfg = load_config()
        vm = ValidationManager(cfg)
        results, conf = vm.validate_many({"A": "ok"})
        self.assertIn("A", results)
        keys = set(results["A"].keys())
        # Ensure enum-driven names are serialized as expected
        self.assertTrue({"syntax", "sandbox", "security", "coverage"}.issubset(keys))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
