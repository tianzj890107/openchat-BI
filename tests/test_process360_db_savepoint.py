from types import SimpleNamespace

import pytest

from bi_agent.process360.db import (
    DatabaseConfig, DatabaseQueryError, PostgresDatabase, _SnapshotReader,
)


class _Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.description = []
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        self.connection.statements.append(sql)
        if sql == "SELECT fail":
            raise RuntimeError("statement failed")
        if sql == "SELECT ok":
            self.description = [SimpleNamespace(name="value")]
            self._rows = [dict(value=1)]
            return
        self.description = []
        self._rows = []

    def fetchmany(self, size):
        rows, self._rows = self._rows, []
        return rows[:size]


class _Connection:
    def __init__(self):
        self.statements = []

    def cursor(self):
        return _Cursor(self)


def test_snapshot_reader_rolls_back_failed_statement_to_savepoint():
    database = PostgresDatabase(DatabaseConfig(dsn="postgresql://example/db"))
    connection = _Connection()
    reader = _SnapshotReader(database, connection)

    with pytest.raises(DatabaseQueryError):
        reader.run("SELECT fail", ())
    result = reader.run("SELECT ok", ())

    assert result.rows == [dict(value=1)]
    assert 'SAVEPOINT "process360_sp_1"' in connection.statements
    assert 'ROLLBACK TO SAVEPOINT "process360_sp_1"' in connection.statements
    assert 'RELEASE SAVEPOINT "process360_sp_1"' in connection.statements
    assert 'SAVEPOINT "process360_sp_2"' in connection.statements
