import unittest

import remind_bot as rb


class BackNavigationTests(unittest.TestCase):
    def test_simple_back_from_minute_to_hour(self):
        stack = ["main", "at_date", "at_hour", "at_minute"]
        user_data = {"pending_at_hhmm": "10:30"}
        prev = rb.apply_back_navigation(stack, user_data)
        self.assertEqual(prev, "at_hour")
        # pending_at_hhmm clears when returning to at_minute parent
        self.assertNotIn("pending_at_hhmm", user_data)

    def test_back_from_text_await_to_minute(self):
        stack = ["main", "at_date", "at_hour", "at_minute", "at_await"]
        user_data = {"pending_at_hhmm": "11:00"}
        prev = rb.apply_back_navigation(stack, user_data)
        self.assertEqual(prev, "at_minute")
        self.assertNotIn("pending_at_hhmm", user_data)

    def test_multi_back_to_main_does_not_underflow(self):
        stack = ["main", "in_minute"]
        user_data = {"pending_in_min": 15}
        p1 = rb.apply_back_navigation(stack, user_data)
        self.assertEqual(p1, "main")
        p2 = rb.apply_back_navigation(stack, user_data)
        self.assertEqual(p2, "main")

    def test_tz_time_clears_on_back(self):
        stack = ["main", "tz_time"]
        user_data = {"pending_tz_time": True}
        prev = rb.apply_back_navigation(stack, user_data)
        self.assertEqual(prev, "main")
        self.assertNotIn("pending_tz_time", user_data)


