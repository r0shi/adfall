#!/usr/bin/env python3
"""OCR image-only PDFs (Nexstar, Sinclair, Gray and others file scans/prints with no text layer).

Engines
  vision     Apple Vision via the `ocrmac` package (default on macOS). ~0.2 s/page at scale 1.5 in one
             process, about 5x tesseract, with the same parse results on WideOrbit/Katz prints.
  tesseract  the tesseract CLI, psm 6, scale 2.2 (~1 s/page). Fallback / non-Mac.
Text is cached at data/ocr/<file_id>.txt (pages separated by form feeds) and picked up by
ingest.parse. Each attempt is recorded in the Postgres `ocr` table; a failure is retried on later runs
until OCR_MAX_ATTEMPTS and then left alone (ingest.status lists them), never retried forever.
Worker processes only render and read PDFs; the ledger is written by the parent process.

  python3 -m ingest.ocr --workers 6                 # everything downloaded that parsed as image-only
  python3 -m ingest.ocr --engine tesseract --ids a,b
  python3 -m ingest.ocr --pages 4                   # cap pages per document (default 12)
"""
import argparse, datetime, logging, os, re, subprocess, sys, tempfile, time
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp
from . import db
from .runlog import Stage

log = logging.getLogger("ingest.ocr")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OCR_DIR = os.path.join(ROOT, "data", "ocr")
OCR_MAX_ATTEMPTS = 3
SCALES = {"vision": 1.5, "tesseract": 2.2}       # pypdfium2 render scale (1.0 = 72 dpi)


def vision_text(img, level="accurate"):
    """Apple Vision OCR of a PIL image, rebuilt into text lines in reading order.
    Vision returns one box per text run with normalized coordinates (origin bottom-left); runs whose
    vertical centres are within half a line height are joined left-to-right with two spaces."""
    from ocrmac import ocrmac
    res = ocrmac.OCR(img, recognition_level=level, language_preference=["en-US"]).recognize()
    boxes = sorted((1 - (b[1] + b[3]), b[0], b[3], t) for t, c, b in res)      # top, left, height, text
    rows = []
    for top, left, h, t in boxes:
        if rows and abs(rows[-1][0] - top) < max(h, rows[-1][2]) * 0.5:
            rows[-1][1].append((left, t))
        else:
            rows.append([top, [(left, t)], h])
    text = "\n".join("  ".join(t for _, t in sorted(r[1])) for r in rows)
    return re.sub(r"[^\x00-\x7fÀ-ÿ]", "", text)          # Vision appends ł ą ẠỊ to digits; nothing in these documents needs them


def tesseract_text(img):
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "p.png"); img.save(p)
        r = subprocess.run(["tesseract", p, "-", "--psm", "6"], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"tesseract exit {r.returncode}: {r.stderr.strip()[:200]}")
        return r.stdout


def ocr_pdf(job):
    """Worker: (fid, rel_path, engine, max_pages) -> dict(status, pages_done, pages_total, chars, seconds, error)."""
    fid, path, engine, max_pages = job
    out = os.path.join(OCR_DIR, fid + ".txt")
    t0 = time.time()
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(os.path.join(ROOT, path))
        total = len(pdf)
        texts = []
        pages = list(range(total)) if total <= max_pages else list(range(max_pages - 2)) + [total - 2, total - 1]
        for i in pages:
            img = pdf[i].render(scale=SCALES[engine]).to_pil()
            texts.append(vision_text(img) if engine == "vision" else tesseract_text(img))
        text = "\n\f\n".join(texts)
        tmp = f"{out}.{os.getpid()}.part"               # unique per worker: two OCR runs never write the same temp file
        with open(tmp, "w") as fh:
            fh.write(text)
        os.replace(tmp, out)
        return {"fid": fid, "status": "ok", "pages_done": len(texts), "pages_total": total, "chars": len(text), "seconds": time.time() - t0, "error": None}
    except Exception as e:
        return {"fid": fid, "status": "failed", "pages_done": 0, "pages_total": None, "chars": 0, "seconds": time.time() - t0, "error": f"{type(e).__name__}: {str(e)[:200]}"}


def candidates(con, st, ids=None, max_attempts=OCR_MAX_ATTEMPTS):
    """Downloaded documents the parser found no text layer in, minus those already OCR'd or given up on.
    Cached text without a ledger row (an OCR run killed before its commit, or text produced by another run) is
    adopted into the ledger as engine='cached', so `parse --only-failed` picks it up instead of it lying unused."""
    if ids:
        rows = con.execute("SELECT file_id, local_path FROM opif_file WHERE file_id = ANY(%s)", (list(ids),)).fetchall()
        return [(r[0], r[1]) for r in rows]
    rows = con.execute("""SELECT f.file_id, f.local_path, o.status, o.attempts
                          FROM opif_file f JOIN document d USING (file_id) LEFT JOIN ocr o USING (file_id)
                          WHERE f.downloaded AND f.deleted_at IS NULL AND d.needs_ocr ORDER BY f.file_id""").fetchall()
    jobs, given_up, cached, adopted = [], 0, 0, 0
    for fid, path, status, attempts in rows:
        txt = os.path.join(OCR_DIR, fid + ".txt")
        if os.path.exists(txt):
            cached += 1
            if status is None:
                size = os.path.getsize(txt)
                con.execute("""INSERT INTO ocr(file_id,engine,status,attempts,chars,ocr_at) VALUES(%s,'cached','ok',1,%s,%s) ON CONFLICT (file_id) DO NOTHING""",
                            (fid, size, datetime.datetime.fromtimestamp(os.path.getmtime(txt)).astimezone()))
                adopted += 1
            continue
        if status == "failed" and (attempts or 0) >= max_attempts:
            given_up += 1
            continue
        jobs.append((fid, path))
    con.commit()                         # the OCR loop that follows commits every 20 documents; start it without an open transaction
    if adopted:
        st.warn("%d documents had OCR text on disk but no ledger row; recorded as engine=cached so parse --only-failed picks them up", adopted)
        st.count("adopted", adopted)
    return jobs, given_up, cached


def record(con, r, engine):
    con.execute("""INSERT INTO ocr(file_id,engine,status,attempts,pages_done,pages_total,chars,seconds,error,ocr_at)
                   VALUES(%s,%s,%s,1,%s,%s,%s,%s,%s,%s) ON CONFLICT (file_id) DO UPDATE SET engine=EXCLUDED.engine, status=EXCLUDED.status,
                   attempts=ocr.attempts+1, pages_done=EXCLUDED.pages_done, pages_total=EXCLUDED.pages_total, chars=EXCLUDED.chars,
                   seconds=EXCLUDED.seconds, error=EXCLUDED.error, ocr_at=EXCLUDED.ocr_at""",
                (r["fid"], engine, r["status"], r["pages_done"], r["pages_total"], r["chars"], round(r["seconds"], 2), r["error"], db.now()))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["vision", "tesseract"], default="vision" if sys.platform == "darwin" else "tesseract")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--pages", type=int, default=12, help="max pages per document")
    ap.add_argument("--ids", help="comma-separated file ids (re-OCR even if cached)")
    ap.add_argument("--retry-given-up", action="store_true")
    ap.add_argument("--redo-legacy", action="store_true", help="re-OCR documents whose text came from the pre-ledger tesseract run (no ocr row)")
    ap.add_argument("--max-fail-rate", type=float, default=0.05)
    a = ap.parse_args(argv)
    os.makedirs(OCR_DIR, exist_ok=True)
    with Stage("ocr", args=vars(a), max_fail_rate=a.max_fail_rate) as st:
        con = db.connect()
        if a.retry_given_up:
            n = con.execute("UPDATE ocr SET attempts=0 WHERE status='failed'").rowcount; con.commit()
            log.info("reset %d given-up OCR attempts", n)
        if a.redo_legacy:
            rows = con.execute("""SELECT f.file_id, f.local_path FROM opif_file f JOIN document d USING (file_id) LEFT JOIN ocr o USING (file_id)
                                  WHERE d.source='ocr' AND o.file_id IS NULL ORDER BY f.file_id""").fetchall()
            jobs = [(r[0], r[1]) for r in rows]; given_up = cached = 0
            log.info("redo-legacy: %d documents OCR'd by the old tesseract run will be redone with %s", len(jobs), a.engine)
            for fid, _ in jobs:
                p = os.path.join(OCR_DIR, fid + ".txt")
                if os.path.exists(p):
                    os.rename(p, p + ".tesseract")      # keep the old text next to the new one for comparison
        elif a.ids is not None:
            ids = [x for x in a.ids.split(",") if x]
            if not ids:
                raise SystemExit("--ids given but empty")
            jobs = candidates(con, st, ids); given_up = cached = 0
            for fid in ids:
                p = os.path.join(OCR_DIR, fid + ".txt")
                if os.path.exists(p):
                    os.remove(p)
        else:
            jobs, given_up, cached = candidates(con, st)
        log.info("OCR %d image-only PDFs with %d workers (engine=%s, max pages %d); %d already cached, %d given up after %d failures",
                 len(jobs), a.workers, a.engine, a.pages, cached, given_up, OCR_MAX_ATTEMPTS)
        st.count("queued", len(jobs)); st.count("cached", cached); st.count("given_up", given_up)
        if given_up:
            st.warn("%d documents failed OCR %d times and are skipped (--retry-given-up to retry)", given_up, OCR_MAX_ATTEMPTS)
        jobs = [(fid, path, a.engine, a.pages) for fid, path in jobs]
        n = ok = failed = pages = 0; secs = 0.0
        ctx = mp.get_context("spawn")                    # pyobjc/Vision is not fork-safe
        with ProcessPoolExecutor(a.workers, mp_context=ctx) as ex:
            for r in ex.map(ocr_pdf, jobs, chunksize=2):
                n += 1; st.attempt()
                pages += r["pages_done"]; secs += r["seconds"]
                record(con, r, a.engine)
                if r["status"] == "ok":
                    ok += 1
                    if r["chars"] < 50:
                        st.warn("  %s: OCR produced only %d chars over %d pages", r["fid"], r["chars"], r["pages_done"])
                else:
                    failed += 1; st.fail(r["fid"], f"ocr: {r['error']}")
                if n % 20 == 0:
                    con.commit()
                st.progress(n, len(jobs), every=100, label="ocr")
        con.commit()
        st.count("ok", ok); st.count("failed", failed); st.count("pages", pages)
        if pages:
            log.info("  %d pages, %.2f cpu-s/page, %.2f wall-s/page", pages, secs / pages, (time.time() - st.t0) / pages)
        con.close()


if __name__ == "__main__":
    main()
