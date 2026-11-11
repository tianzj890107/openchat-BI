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


class _GroupCursor:
    def __init__(self, connection):
        self.connection = connection
        self.description = []
        self._last = ''

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        self._last = sql
        self.connection.statements.append((sql, params))

    def fetchone(self):
        if 'pg_export_snapshot' in self._last:
            return {'pg_export_snapshot': 'snapshot-1234'}
        return None


class _GroupConnection:
    def __init__(self):
        self.statements = []
        self.autocommit = False
        self.closed = False
        self.cancelled = False

    def cursor(self):
        return _GroupCursor(self)

    def rollback(self):
        pass

    def close(self):
        self.closed = True

    def cancel(self):
        self.cancelled = True


def test_snapshot_group_shares_exported_snapshot_across_connections():
    database = PostgresDatabase(DatabaseConfig(dsn="postgresql://example/db"))
    connections = [_GroupConnection() for _ in range(3)]
    database._connect = lambda: connections.pop(0)

    with database.snapshot_group(3) as readers:
        assert len(readers) == 3
        assert readers[0].connection.statements[0][0].startswith('BEGIN ISOLATION LEVEL REPEATABLE READ')
        assert any('pg_export_snapshot' in sql for sql, _ in readers[0].connection.statements)
        for reader in readers[1:]:
            snapshot_sql = [str(sql) for sql, _ in reader.connection.statements
                            if 'SET TRANSACTION SNAPSHOT' in str(sql)]
            assert snapshot_sql and "'snapshot-1234'" in snapshot_sql[0]
    assert all(connection.closed for connection in connections)


def test_query_error_keeps_sqlstate_and_driver_detail_private():
    class FailingCursor(_Cursor):
        def execute(self, sql, params=()):
            if sql == "SELECT fail_state":
                exc = RuntimeError('relation "secret_table" does not exist')
                exc.sqlstate = '42P01'
                raise exc
            return super().execute(sql, params)

    class FailingConnection(_Connection):
        def cursor(self):
            return FailingCursor(self)

    database = PostgresDatabase(DatabaseConfig(dsn="postgresql://example/db"))
    reader = _SnapshotReader(database, FailingConnection())
    with pytest.raises(DatabaseQueryError) as caught:
        reader.run("SELECT fail_state", ())
    assert caught.value.sqlstate == '42P01'
    assert '42P01' in str(caught.value)
    assert 'secret_table' not in str(caught.value)
    assert 'secret_table' in caught.value.original_message
    assert caught.value.query_duration_ms >= 0
