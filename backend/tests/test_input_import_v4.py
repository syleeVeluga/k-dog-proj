import unittest

from fastapi import HTTPException

from app.sheets_v4 import import_workbook, workbook_preflight


class InputImportV4Tests(unittest.TestCase):
    def test_mapping_is_complete_but_physical_profile_and_import_stay_disabled(self):
        result = workbook_preflight()
        self.assertEqual(len(result["entries"]), 90)
        self.assertFalse(result["excel_import_enabled"])
        self.assertEqual(result["physical_verification"], "not_received_G01_G04")
        self.assertIn("E40_completion_formula", result["unverified_checks"])
        with self.assertRaises(HTTPException) as caught:
            import_workbook(b"synthetic workbook bytes")
        self.assertEqual(caught.exception.status_code, 409)

    def test_synthetic_d_j_mismatch_and_f_g_examples_detected_without_import(self):
        entry = workbook_preflight()["entries"][0]
        sheet, cell = entry["input_address"].split("!")
        result = workbook_preflight({entry["internal_address"]: "='wrong'!D999", f"{sheet}!F{cell[1:]}": "예시 관찰 메모",
                                     f"{sheet}!G{cell[1:]}": "sample form review"})
        self.assertEqual(result["differences"][0]["code"], entry["code"])
        self.assertEqual(len(result["example_memo_addresses"]), 2)
        self.assertFalse(result["excel_import_enabled"])
        matching = workbook_preflight({entry["internal_address"]: f"='{sheet}'!${cell[0]}${cell[1:]}"})
        self.assertEqual(matching["differences"], [])
        self.assertFalse(matching["excel_import_enabled"])


if __name__ == "__main__":
    unittest.main()
