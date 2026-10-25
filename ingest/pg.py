"""Postgres connection and migrations. DATABASE_URL from env or .env; default is the compose service.

  python3 -m ingest.pg migrate     # apply db/migrations/*.sql not yet applied
  python3 -m ingest.pg marts       # refresh materialized views
"""
import os, sys, glob
import psycopg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_URL = "postgresql://tvw:tvw@127.0.0.1:5434/tvw"


def url():
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    env = os.path.join(ROOT, ".env")
    if os.path.exists(env):
        for line in open(env):
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    return DEFAULT_URL


def connect(autocommit=False):
    return psycopg.connect(url(), autocommit=autocommit)


def migrate():
    with connect(autocommit=True) as con:
        con.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz DEFAULT now())")
        done = {r[0] for r in con.execute("SELECT name FROM schema_migrations")}
        for path in sorted(glob.glob(os.path.join(ROOT, "db", "migrations", "*.sql"))):
            name = os.path.basename(path)
            if name in done:
                continue
            print(f"applying {name}", file=sys.stderr)
            con.execute(open(path).read())
            con.execute("INSERT INTO schema_migrations(name) VALUES (%s)", (name,))


MARTS = ["spend_daily", "station_daily", "station_total", "buyer_station", "hex_total"]


def refresh_marts():
    from .runlog import Stage
    import logging
    with Stage('marts') as st, connect(autocommit=True) as con:
        for m in MARTS:
            logging.getLogger('ingest.pg').info(f"refresh {m}")
            con.execute(f"REFRESH MATERIALIZED VIEW {m}")
            st.count(m, con.execute(f"SELECT COUNT(*) FROM {m}").fetchone()[0])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "migrate"
    {"migrate": migrate, "marts": refresh_marts}[cmd]()
