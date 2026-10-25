"""Postgres is the pipeline's single store: crawl state (opif_file, opif_listing), the OCR ledger (ocr),
parsed documents (document), sync markers (meta) and stage runs (pipeline_run) all live next to the entities.

    from . import db
    con = db.connect()                       # one connection per process; parse/OCR workers never touch the DB
    for r in con.execute("SELECT file_id, local_path FROM opif_file WHERE downloaded"):
        r[0], r["file_id"]                   # rows index by position and by column name

DATABASE_URL comes from the environment or .env (see ingest.pg); the default is the compose service.
connect() refuses to run against a schema that is behind db/migrations (run `make migrate`), so a stage
never writes into a table it does not expect.
"""
import datetime, glob, os
import psycopg
from . import pg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_checked = set()


def row_factory(cursor):
    """psycopg row factory: tuples that also accept column names (r["file_id"]) and expose keys()."""
    desc = cursor.description
    names = [d.name for d in desc] if desc else []
    index = {n: i for i, n in enumerate(names)}

    class Row(tuple):
        __slots__ = ()

        def __getitem__(self, k, _get=tuple.__getitem__):
            return _get(self, index[k] if isinstance(k, str) else k)

        def keys(self):
            return list(names)

        def asdict(self):
            return dict(zip(names, self))

    return Row


def connect(autocommit=False):
    url = pg.url()
    con = psycopg.connect(url, autocommit=autocommit, row_factory=row_factory)
    if url not in _checked:
        check_schema(con)
        _checked.add(url)
    return con


def check_schema(con):
    want = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "db", "migrations", "*.sql")))
    try:
        have = {r[0] for r in con.execute("SELECT name FROM schema_migrations")}
    except psycopg.errors.UndefinedTable:
        con.rollback(); have = set()
    missing = [m for m in want if m not in have]
    if missing:
        raise SystemExit(f"database schema is behind: {', '.join(missing)} not applied; run `make migrate`")


def dbname():
    """For status headers: the database part of DATABASE_URL."""
    return pg.url().rsplit("/", 1)[-1].split("?")[0]


def now():
    """Timezone-aware local time; stored as timestamptz, so the instant survives the server's UTC setting."""
    return datetime.datetime.now().astimezone()
