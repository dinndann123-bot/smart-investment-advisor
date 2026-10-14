"""Offline contract checks for source verification API (no external requests)."""
import unittest
from fastapi import HTTPException
from news_verification_api import clean_symbol

class NewsVerificationContract(unittest.TestCase):
    def test_valid_symbol(self):
        self.assertEqual(clean_symbol("aapl"),"AAPL")
        self.assertEqual(clean_symbol("BRK.B"),"BRK.B")
    def test_reject_untrusted_symbol(self):
        for value in ("AAPL/../../etc", "AAPL?x=1", "", "AAPL BBB"):
            with self.assertRaises(HTTPException):
                clean_symbol(value)
if __name__=="__main__":
    unittest.main()
