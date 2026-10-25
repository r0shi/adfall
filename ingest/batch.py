#!/usr/bin/env python3
"""National crawl driver: one state at a time, crawl -> parse -> OCR -> parse, with the Postgres refresh
(load_pg, entities, identity, entities, marts) running in the background after each state while the next
state downloads. Holds the "pipeline" lock so two drivers cannot overlap.

  python3 -m ingest.batch --targets data/crawl_targets_2026_national.txt --years 2026
  python3 -m ingest.batch ... --states TX,OH          # a subset, in that order
  python3 -m ingest.batch ... --all                   # redo states already marked done (cheap: crawl skips complete listings)

Resumable: each state that finishes crawl+parse+ocr+parse gets a pipeline_run row (stage=batch_state, batch=<ST>,
status ok); a rerun skips those unless --all. A state whose crawl fails is recorded failed and the driver moves on;
three consecutive failed states abort the run (the FCC edge is refusing us). Monitor with `make status` or
`tail -f data/logs/batch-*.log`; every stage keeps its own log in data/logs/.
"""
import argparse, datetime, json, logging, os, subprocess, sys, threading, time
from . import db
from .runlog import Stage, run_db, hms, ROOT

log = logging.getLogger("ingest.batch")
PY = sys.executable


def stage_cmd(mod, *args):
    return [PY, "-m", f"ingest.{mod}", *args]


def run_stage(cmd, batch, timeout=None):
    """Run one stage as a subprocess; returns (exit_code, seconds, summary_line)."""
    env = {**os.environ, "TVW_BATCH": batch}
    t0 = time.time()
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    summary = next((ln for ln in reversed((p.stderr or "").splitlines()) if "== SUMMARY" in ln), (p.stderr or "").strip().splitlines()[-1:] or [""])
    summary = summary if isinstance(summary, str) else (summary[0] if summary else "")
    return p.returncode, time.time() - t0, summary


class PgRefresher:
    """Serialises the Postgres refresh chain in a background thread; a request made while one is running
    is coalesced into one more run after it finishes."""
    CHAIN = [("load_pg",), ("entities",), ("identity",), ("entities",), ("pg", "marts")]

    def __init__(self, st):
        self.st, self.pending, self.running, self.lock = st, False, False, threading.Lock()
        self.thread, self.failures = None, 0

    def request(self, label):
        with self.lock:
            self.pending = True
            if not self.running:
                self.running = True
                self.thread = threading.Thread(target=self._loop, args=(label,), daemon=True)
                self.thread.start()

    def _loop(self, label):
        while True:
            with self.lock:
                if not self.pending:
                    self.running = False
                    return
                self.pending = False
            log.info("[pg] refresh after %s: %s", label, " -> ".join(" ".join(c) for c in self.CHAIN))
            for c in self.CHAIN:
                rc, secs, summ = run_stage(stage_cmd(*c), batch="pg:" + label)
                log.info("[pg]   %-12s exit=%d %s  %s", " ".join(c), rc, hms(secs), summ[-160:])
                if rc != 0:
                    self.failures += 1
                    self.st.fail("pg-refresh/" + " ".join(c), f"exit {rc} after {label}: {summ[-200:]}")
                    break
            self.st.count("pg_refreshes")

    def wait(self):
        t = self.thread
        if t:
            t.join()


def done_states(con):
    return {r[0] for r in con.execute("SELECT batch FROM pipeline_run WHERE stage='batch_state' AND status='ok'")}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default=os.path.join(ROOT, "data", "crawl_targets_2026_national.txt"))
    ap.add_argument("--years", default="2026")
    ap.add_argument("--states", help="comma-separated subset, in order")
    ap.add_argument("--all", action="store_true", help="do not skip states already marked done")
    ap.add_argument("--workers", type=int, default=6, help="download workers")
    ap.add_argument("--ocr-workers", type=int, default=4)
    ap.add_argument("--parse-workers", type=int, default=6)
    ap.add_argument("--no-pg", action="store_true", help="skip the Postgres refresh chain")
    ap.add_argument("--db", default=db.DEFAULT_DB)
    a = ap.parse_args(argv)
    states = []
    for line in open(a.targets):
        parts = line.split()
        if parts and not line.startswith("#"):
            states.append((parts[0], parts[1].split(",")))
    if a.states:
        want = a.states.split(",")
        states = sorted([s for s in states if s[0] in want], key=lambda s: want.index(s[0]))
    with Stage("pipeline", args=vars(a), db_path=a.db, max_fail_rate=0.2, min_failures=3) as st:
        con = run_db(a.db)
        skip = set() if a.all else done_states(con)
        todo = [s for s in states if s[0] not in skip]
        total_docs = sum(len(f) for _, f in todo)
        log.info("batch: %d states (%d stations) to do, %d skipped as done: %s", len(todo), total_docs, len(skip), " ".join(s for s, _ in todo))
        pgr = PgRefresher(st)
        consecutive_fail = 0
        t_start = time.time()
        for i, (state, facs) in enumerate(todo, 1):
            t0 = time.time()
            log.info("=== [%d/%d] %s: %d stations", i, len(todo), state, len(facs))
            steps = [("crawl", stage_cmd("crawl", "--stations-file", a.targets, "--state", state, "--years", a.years, "--download", "--workers", str(a.workers))),
                     ("parse", stage_cmd("parse", "--stations", ",".join(facs), "--workers", str(a.parse_workers))),
                     ("ocr", stage_cmd("ocr", "--workers", str(a.ocr_workers))),
                     ("parse2", stage_cmd("parse", "--only-failed", "--stations", ",".join(facs), "--workers", str(a.parse_workers)))]
            failed = None
            with Stage("batch_state", args={"state": state, "stations": len(facs)}, db_path=a.db, lock=False, batch=state) as sst:
                for name, cmd in steps:
                    rc, secs, summ = run_stage(cmd, batch=state)
                    log.info("  %-6s exit=%d %s  %s", name, rc, hms(secs), summ[-200:])
                    sst.count(name + "_seconds", round(secs))
                    if rc != 0:
                        failed = name
                        sst.fail(f"{state}/{name}", f"exit {rc}: {summ[-200:]}")
                        if name == "crawl":
                            break                        # nothing new to parse; keep going with the next state
                if failed:
                    raise RuntimeError(f"{state}: stage {failed} failed")
            # (Stage raises SystemExit(1) on failure; we are outside it here only when ok)
            consecutive_fail = 0
            st.count("states_ok")
            if not a.no_pg:
                pgr.request(state)
            el = time.time() - t_start
            log.info("=== %s done in %s; %d/%d states, elapsed %s, eta %s", state, hms(time.time() - t0), i, len(todo), hms(el), hms(el / i * (len(todo) - i)))
        pgr.wait()
        st.count("pg_refresh_failures", pgr.failures)


def _main_wrapper():
    """A failed state must not end the whole run: catch the SystemExit from the inner Stage and continue."""
    import types
    main_src = main
    # re-implement the loop with per-state error handling by wrapping Stage exits
    orig = Stage.__exit__

    def soft_exit(self, et, ev, tb):
        try:
            return orig(self, et, ev, tb)
        except SystemExit:
            if self.name == "batch_state":
                return True                              # swallow: the driver records and moves on
            raise
    Stage.__exit__ = soft_exit
    try:
        main_src()
    finally:
        Stage.__exit__ = orig


if __name__ == "__main__":
    _main_wrapper()
