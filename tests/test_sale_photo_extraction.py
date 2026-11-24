import unittest
from app.services.sale_photo_service import (
    SalePhotoError,
    normalize_sale_photo,
)


class SalePhotoTests(unittest.TestCase):
    def line(self, **values):
        return normalize_sale_photo({"lines": [values]})["lines"][0]

    def test_blank_payment(self):
        line = self.line(quantity=2, line_total=18000)
        self.assertIsNone(line["paid_amount"])
        self.assertIsNone(line["product_id"])
        self.assertIsNone(line["unit_price"])
        self.assertEqual(line["suggested_unit_price"], 9000)

    def test_explicit_zero_payment(self):
        self.assertEqual(self.line(paid_amount=0)["paid_amount"], 0)

    def test_invalid_amounts(self):
        for value in (True, -1, 1.5, "1,500", 2_000_000_001):
            with self.subTest(value=value):
                self.assertIsNone(self.line(line_total=value)["line_total"])

    def test_date_and_total(self):
        result = normalize_sale_photo({
            "document_date": "07/04/26",
            "document_total": 20000,
            "lines": [{"quantity": 2, "line_total": 18000}],
        })
        self.assertIsNone(result["document_date"])
        self.assertEqual(len(result["warnings"]), 2)

    def test_indivisible_total(self):
        line = self.line(quantity=3, line_total=10000)
        self.assertIsNone(line["suggested_unit_price"])
        self.assertTrue(line["warnings"])

    def test_duplicates(self):
        result = normalize_sale_photo({
            "lines": [{"description": "Riz"}, {"description": "Riz"}],
        })
        self.assertEqual(len(result["lines"]), 2)

    def test_inconsistent_price_and_overpayment(self):
        line = self.line(
            quantity=2,
            unit_price=9000,
            line_total=10000,
            paid_amount=11000,
        )
        self.assertEqual(len(line["warnings"]), 2)

    def test_invalid_structure(self):
        with self.assertRaises(SalePhotoError):
            normalize_sale_photo({"lines": "texte"})
