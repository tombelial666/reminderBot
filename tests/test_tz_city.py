import unittest

import remind_bot as rb


class TZCityMappingTests(unittest.TestCase):
    def test_ru_cities(self):
        self.assertEqual(rb.tz_from_city("Москва"), "Europe/Moscow")
        self.assertEqual(rb.tz_from_city("Санкт-Петербург"), "Europe/Moscow")

    def test_en_cities(self):
        self.assertEqual(rb.tz_from_city("Bangkok"), "Asia/Bangkok")
        self.assertEqual(rb.tz_from_city("London"), "Europe/London")

    def test_th_cities(self):
        self.assertEqual(rb.tz_from_city("กรุงเทพฯ"), "Asia/Bangkok")

    def test_passthrough_tz(self):
        self.assertEqual(rb.tz_from_city("Europe/Moscow"), "Europe/Moscow")
        self.assertIsNone(rb.tz_from_city("NotACityOrTZ"))


if __name__ == "__main__":
    unittest.main()


