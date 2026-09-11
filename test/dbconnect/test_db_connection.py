# python .\test_db_connection.py
import unittest

try:
    from dbconnect import check_connection
except ModuleNotFoundError:
    from db_connection import check_connection


class DatabaseConnectionTest(unittest.TestCase):
    def test_connection_and_schema(self) -> None:
        schema, version = check_connection()

        self.assertEqual(schema, "s_brain")
        self.assertTrue(version)


if __name__ == "__main__":
    unittest.main()