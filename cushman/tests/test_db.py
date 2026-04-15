import sqlite3
import unittest
from cushman.db import Database

class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")

    def test_init(self):
        self.assertIsNotNone(self.db.conn)
        self.assertEqual(self.db.db_path, ":memory:")

    def test_execute(self):
        result = self.db.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        self.assertTrue(result)

        result = self.db.execute("INSERT INTO test (name) VALUES ('test')")
        self.assertTrue(result)

    def test_query(self):
        self.db.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        self.db.execute("INSERT INTO test (name) VALUES ('test')")
        
        rows = self.db.query("SELECT * FROM test")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], 'test')

    def test_close(self):
        self.db.close()
        with self.assertRaises(sqlite3.ProgrammingError):
            self.db.execute("SELECT 1")