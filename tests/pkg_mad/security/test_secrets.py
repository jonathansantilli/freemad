import os
import unittest

from freemad import get_secret, SecretSpec


class TestSecrets(unittest.TestCase):
    def test_env_secret(self):
        os.environ["FREE_MAD_TEST_KEY"] = "VALUE"
        v = get_secret(SecretSpec(source="env", name="FREE_MAD_TEST_KEY"))
        self.assertEqual(v, "VALUE")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
