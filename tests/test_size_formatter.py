"""Unit tests for nominal storage capacity formatting."""

import unittest

from services.size_formatter import SizeFormatter


class SizeFormatterTests(unittest.TestCase):
    """Verify common manufacturer capacities are normalized for display."""

    def test_common_gigabyte_capacities(self) -> None:
        cases = {
            250_059_350_016: "250 GB",
            320_072_933_376: "320 GB",
            500_107_862_016: "500 GB",
            640_135_028_736: "640 GB",
        }
        for size_bytes, expected in cases.items():
            with self.subTest(size_bytes=size_bytes):
                self.assertEqual(SizeFormatter.format(size_bytes), expected)

    def test_common_terabyte_capacities(self) -> None:
        cases = {
            1_000_204_886_016: "1 TB",
            2_000_398_934_016: "2 TB",
            4_000_787_030_016: "4 TB",
            6_001_175_126_016: "6 TB",
            8_000_000_000_000: "8 TB",
            16_000_000_000_000: "16 TB",
        }
        for size_bytes, expected in cases.items():
            with self.subTest(size_bytes=size_bytes):
                self.assertEqual(SizeFormatter.format(size_bytes), expected)


if __name__ == "__main__":
    unittest.main()
