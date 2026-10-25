"""Run bookkeeping shared by every pipeline stage: log files, locks, counts, and the pipeline_run table.

    from .runlog import Stage
    with Stage("crawl", args=vars(a), db_path=a.db) as st:
        st.count("listed", n)
        st.fail(file_id, "HTTP 404")       # logged with the id and reason, counted, summarised
        ...
    # on exit: SUMMARY line, pipeline_run row closed, exit 1 if the stage failed or
    # failures exceeded max_fail_rate of the work attempted

Every stage writes data/logs/<stage>-<YYYYmmdd-HHMMSS>.log (INFO and above) and mirrors it to stderr.
A per-stage lock in data/locks/ stops two instances of the same stage from overlapping; the batch
driver (ingest.batch) additionally holds the "pipeline" lock so two full pipeline runs cannot overlap.
Stage runs are recorded in the SQLite pipeline_run table (copied to Postgres by load_pg), with start,
end, status, counts and the log path, so `ingest.status` can show what ran and what failed last.
"""
import datetime, fcntl, json, logging, os, socket, sqlite3, sys, time, traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "data", "logs")
LOCK_DIR = os.path.join(ROOT, "data", "locks")
DEFAULT_DB = os.path.join(ROOT, "data", "political.sqlite")

RUN_SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline_run (
  run_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  stage     TEXT NOT NULL,
  batch     TEXT,                 -- label from the batch driver (e.g. the state), NULL for ad-hoc runs
  started   TEXT NOT NULL,
  ended     TEXT,
  status    TEXT NOT NULL,        -- running | ok | failed | killed
  pid       INTEGER,
  host      TEXT,
  args      TEXT,                 -- JSON
  counts    TEXT,                 -- JSON {name: n}
  failures  INTEGER DEFAULT 0,
  error     TEXT,
  log_path  TEXT
);
CREATE INDEX IF NOT EXISTS pipeline_run_stage ON pipeline_run(stage, started);
"""

log = logging.getLogger("ingest")


def run_db(path=DEFAULT_DB):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path, timeout=120)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=120000")
    con.executescript(RUN_SCHEMA)
    return con


def pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class LockHeld(SystemExit):
    pass


def acquire_lock(name, block=False):
    """Return an open lock file holding an exclusive flock, or raise LockHeld with the holder's pid."""
    os.makedirs(LOCK_DIR, exist_ok=True)
    path = os.path.join(LOCK_DIR, name + ".lock")
    fh = open(path, "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | (0 if block else fcntl.LOCK_NB))
    except BlockingIOError:
        fh.seek(0)
        holder = fh.read().strip()
        fh.close()
        raise LockHeld(f"{name}: already running ({holder or 'unknown holder'}); lock {path}")
    fh.seek(0); fh.truncate()
    fh.write(f"pid {os.getpid()} since {datetime.datetime.now().isoformat(timespec='seconds')}\n"); fh.flush()
    return fh


def lock_holder(name):
    """Who holds a lock, or None. Non-blocking probe used by ingest.status."""
    path = os.path.join(LOCK_DIR, name + ".lock")
    if not os.path.exists(path):
        return None
    fh = open(path, "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fh, fcntl.LOCK_UN)
        return None
    except BlockingIOError:
        fh.seek(0)
        return fh.read().strip() or "unknown"
    finally:
        fh.close()


def setup_logging(stage, ts):
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, f"{stage}-{ts}.log")
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(path); fh.setFormatter(fmt); root.addHandler(fh)
    sh = logging.StreamHandler(sys.stderr); sh.setFormatter(logging.Formatter("%(message)s")); root.addHandler(sh)
    logging.getLogger("pypdf").setLevel(logging.ERROR)           # "Ignoring wrong pointing object" noise
    logging.getLogger("pypdf._reader").setLevel(logging.ERROR)
    return path


class Stage:
    def __init__(self, name, args=None, db_path=DEFAULT_DB, lock=True, max_fail_rate=0.02, min_failures=20, batch=None):
        self.name, self.args, self.db_path, self.use_lock = name, args or {}, db_path, lock
        self.max_fail_rate, self.min_failures = max_fail_rate, min_failures
        self.batch = batch or os.environ.get("TVW_BATCH")
        self.counts, self.failures, self.attempted = {}, [], 0
        self.run_id, self.lock_fh, self.log_path, self.t0 = None, None, None, None
        self.warnings = 0

    # ---- public API for stages
    def count(self, key, n=1):
        self.counts[key] = self.counts.get(key, 0) + n

    def attempt(self, n=1):
        """Units of work attempted; the failure threshold is relative to this."""
        self.attempted += n

    def fail(self, item, reason, level=logging.WARNING):
        self.failures.append((str(item), str(reason)[:300]))
        log.log(level, "FAIL %s: %s", item, str(reason)[:300])

    def warn(self, msg, *a):
        self.warnings += 1
        log.warning(msg, *a)

    def progress(self, done, total, every=250, label=""):
        if done % every == 0 or done == total:
            el = time.time() - self.t0
            rate = done / el if el > 0 else 0
            eta = (total - done) / rate if rate > 0 else 0
            log.info("  %s%d/%d  %.1f/s  elapsed %s  eta %s", (label + " ") if label else "", done, total, rate, hms(el), hms(eta))

    # ---- context manager
    def __enter__(self):
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.t0 = time.time()
        if self.use_lock:
            self.lock_fh = acquire_lock(self.name)
        self.log_path = setup_logging(self.name, ts)
        con = run_db(self.db_path)
        # anything still 'running' for this stage with a dead pid was killed
        for rid, pid in con.execute("SELECT run_id, pid FROM pipeline_run WHERE stage=? AND status='running'", (self.name,)):
            if not pid_alive(pid):
                con.execute("UPDATE pipeline_run SET status='killed', ended=COALESCE(ended, started), error='process disappeared (killed or crashed)' WHERE run_id=?", (rid,))
        cur = con.execute("INSERT INTO pipeline_run(stage,batch,started,status,pid,host,args,log_path) VALUES(?,?,?,?,?,?,?,?)",
                          (self.name, self.batch, datetime.datetime.now().isoformat(timespec="seconds"), "running", os.getpid(), socket.gethostname(),
                           json.dumps(self.args, default=str), os.path.relpath(self.log_path, ROOT)))
        self.run_id = cur.lastrowid
        con.commit(); con.close()
        log.info("== %s start  run_id=%s pid=%d batch=%s args=%s log=%s", self.name, self.run_id, os.getpid(), self.batch, json.dumps(self.args, default=str), os.path.relpath(self.log_path, ROOT))
        return self

    def __exit__(self, et, ev, tb):
        status, error = "ok", None
        if et is not None:
            status = "failed"
            error = f"{et.__name__}: {ev}" if not issubclass(et, (KeyboardInterrupt, SystemExit)) else f"{et.__name__}: {ev}"
            if issubclass(et, KeyboardInterrupt) or (issubclass(et, SystemExit) and ev.code not in (None, 0)):
                status = "killed" if issubclass(et, KeyboardInterrupt) else "failed"
            if not issubclass(et, (KeyboardInterrupt, SystemExit)):
                log.error("stage %s crashed:\n%s", self.name, "".join(traceback.format_exception(et, ev, tb)))
        nfail = len(self.failures)
        allowed = max(self.min_failures, int(self.attempted * self.max_fail_rate))
        if status == "ok" and nfail > allowed:
            status = "failed"
            error = f"{nfail} failures exceed threshold {allowed} (max_fail_rate={self.max_fail_rate}, attempted={self.attempted})"
        elapsed = time.time() - self.t0
        self.counts["seconds"] = round(elapsed, 1)
        con = run_db(self.db_path)
        con.execute("UPDATE pipeline_run SET ended=?, status=?, counts=?, failures=?, error=? WHERE run_id=?",
                    (datetime.datetime.now().isoformat(timespec="seconds"), status, json.dumps(self.counts), nfail, error, self.run_id))
        con.commit(); con.close()
        if self.failures:
            log.info("failures (%d): first %d listed; all are in the log above", nfail, min(nfail, 10))
            for item, reason in self.failures[:10]:
                log.info("    %s  %s", item, reason)
        counts = " ".join(f"{k}={v}" for k, v in self.counts.items())
        log.info("== SUMMARY stage=%s status=%s run_id=%s elapsed=%s failures=%d warnings=%d %s%s log=%s",
                 self.name, status.upper(), self.run_id, hms(elapsed), nfail, self.warnings, counts, (f" error={error}" if error else ""), os.path.relpath(self.log_path, ROOT))
        if self.lock_fh:
            fcntl.flock(self.lock_fh, fcntl.LOCK_UN); self.lock_fh.close()
        if et is not None:
            return False                       # re-raise
        if status != "ok":
            raise SystemExit(1)
        return False


def hms(s):
    s = int(s)
    return f"{s//3600}h{(s%3600)//60:02d}m{s%60:02d}s" if s >= 3600 else (f"{s//60}m{s%60:02d}s" if s >= 60 else f"{s}s")


def last_runs(con, limit_per_stage=1):
    """{stage: [row dicts]} most recent first."""
    out = {}
    for r in con.execute("SELECT * FROM pipeline_run ORDER BY run_id DESC"):
        d = dict(zip([c[0] for c in con.execute("SELECT * FROM pipeline_run LIMIT 0").description], r))
        out.setdefault(d["stage"], [])
        if len(out[d["stage"]]) < limit_per_stage:
            out[d["stage"]].append(d)
    return out
