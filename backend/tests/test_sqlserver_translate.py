"""Traductor SQLite -> T-SQL de core/sqlserver.py (sin conexión: solo texto)."""

import json
import unittest

from app.core.sqlserver import IN_LIST_MAX, translate


class TranslateTest(unittest.TestCase):
    def test_placeholders_y_percent_en_literal(self):
        sql, params = translate("SELECT 1 FROM t WHERE a = ? AND b LIKE 'PET%'", [1])
        # pytds aplica `sql % params` a todo el texto: el % del literal va escapado.
        self.assertIn("a = %s", sql)
        self.assertIn("'PET%%'", sql)
        self.assertEqual(params, [1])

    def test_like_en_colacion_ci(self):
        sql, _ = translate("SELECT 1 FROM t WHERE nombre LIKE ?", ["x"])
        self.assertIn("nombre COLLATE Latin1_General_100_CI_AS LIKE %s", sql)

    def test_limit_offset(self):
        sql, params = translate("SELECT * FROM t ORDER BY a LIMIT ? OFFSET ?", [10, 20])
        self.assertTrue(sql.endswith("OFFSET %s ROWS FETCH NEXT %s ROWS ONLY"))
        self.assertEqual(params, [20, 10])

    def test_limit_en_subquery_a_top(self):
        sql, _ = translate("SELECT * FROM (SELECT DISTINCT a FROM t ORDER BY a LIMIT 5) x", [])
        self.assertIn("(SELECT DISTINCT TOP 5 a FROM t ORDER BY a)", sql)

    def test_ddl_sqlite_es_noop(self):
        self.assertIsNone(translate("CREATE TABLE IF NOT EXISTS x (a TEXT)", [])[0])
        self.assertIsNone(translate("PRAGMA journal_mode = WAL", [])[0])

    def test_in_largo_viaja_como_json(self):
        valores = [str(i) for i in range(IN_LIST_MAX + 1)]
        marcas = ",".join("?" * len(valores))
        sql, params = translate(f"SELECT 1 FROM t WHERE p = ? AND m IN ({marcas})", ["G1", *valores])
        self.assertIn("OPENJSON(%s)", sql)
        self.assertEqual(params[0], "G1")
        self.assertEqual(json.loads(params[1]), valores)


if __name__ == "__main__":
    unittest.main()
