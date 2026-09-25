"""292251: con WAL, una lectura en curso (como la de /sugeridos/generar) no
bloquea la escritura de otra conexión (como _ensure_tables en /lista)."""

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.core import db as core_db


class TestWal(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name) / "t.db"
        seed = sqlite3.connect(self.path)
        seed.execute("CREATE TABLE t (x INTEGER)")
        seed.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(100)])
        seed.commit()
        seed.close()
        self._patch = patch.object(core_db, "DB_PATH", self.path)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def _escritura_con_lectura_abierta(self) -> None:
        with core_db.get_connection() as lector, core_db.get_connection() as escritor:
            escritor.execute("PRAGMA busy_timeout = 100")
            cursor = lector.execute("SELECT x FROM t")
            cursor.fetchone()  # lectura a medias: retiene el snapshot/lock
            escritor.execute("INSERT INTO t VALUES (-1)")
            escritor.commit()

    def test_enable_wal_persiste_en_el_archivo(self):
        with core_db.get_connection() as conn:
            self.assertEqual(core_db.enable_wal(conn), "wal")
        with core_db.get_connection() as conn:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()["journal_mode"], "wal")

    def test_sin_wal_la_lectura_bloquea_la_escritura(self):
        with self.assertRaises(sqlite3.OperationalError):
            self._escritura_con_lectura_abierta()

    def test_con_wal_la_lectura_no_bloquea_la_escritura(self):
        with core_db.get_connection() as conn:
            core_db.enable_wal(conn)
        self._escritura_con_lectura_abierta()


if __name__ == "__main__":
    unittest.main()
