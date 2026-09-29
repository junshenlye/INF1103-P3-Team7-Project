"""Tests for the validation boundary before AI processing."""

import unittest

from src import io_manager


class ValidateInputTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "modules": [
                {
                    "module_name": "INF1103",
                    "credit_units": 6,
                    "files": ["assessment.png"],
                    "additional_context": "Project is due in week 8.",
                }
            ]
        }

    def test_validates_each_input_in_one_process(self):
        errors = io_manager.validate_input(1, self.payload, None)

        self.assertEqual(errors, [])

    def test_rejects_an_illogical_module_count(self):
        errors = io_manager.validate_input(2, self.payload, None)

        self.assertEqual(errors, ["Module count does not match the data payload."])

    def test_rejects_an_illogical_credit_value(self):
        self.payload["modules"][0]["credit_units"] = -1

        errors = io_manager.validate_input(1, self.payload, None)

        self.assertEqual(errors, ["Module 1 credit units must be positive."])

    def test_returns_frontend_data_unchanged_for_the_ai_manager(self):
        schedule_data = {"week": 8, "status": "retry"}

        ai_input, errors = io_manager.prepare_ai_input(
            1,
            self.payload,
            schedule_data,
        )

        self.assertEqual(errors, [])
        self.assertIs(ai_input["modules"], self.payload["modules"])
        self.assertIs(ai_input["repeating_schedule_data"], schedule_data)


if __name__ == "__main__":
    unittest.main()
