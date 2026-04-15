import sqlite3

class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def execute(self, query, params=None):
        if not self.conn:
            raise sqlite3.ProgrammingError("Cannot operate on a closed database")
        try:
            cursor = self.conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            self.conn.commit()
            return True
        except Exception as e:
            self.conn.rollback()
            return False

    def query(self, query, params=None):
        if not self.conn:
            raise sqlite3.ProgrammingError("Cannot operate on a closed database")
        try:
            cursor = self.conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor.fetchall()
        except Exception as e:
            return []

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None