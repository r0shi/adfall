#!/usr/bin/env python3
"""OCR image-only PDFs (Nexstar, Sinclair and some others file scans/prints with no text layer).

Renders pages with pypdfium2 and runs the tesseract CLI; text is cached at
data/ocr/<file_manager_id>.txt and picked up by ingest.parse.

  python3 -m ingest.ocr --workers 6          # all downloaded docs that parsed as kind=other without text
"""
import argparse, json, os, subprocess, sys, tempfile
from concurrent.futures import ProcessPoolExecutor
from . import db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OCR_DIR = os.path.join(ROOT, "data", "ocr")
SCALE = 2.2          # ~160 dpi; enough for WideOrbit/Katz print at tesseract psm 6


def ocr_pdf(args):
    fid, path, max_pages = args
    out = os.path.join(OCR_DIR, fid + ".txt")
    if os.path.exists(out):
        return fid, "cached"
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(os.path.join(ROOT, path))
        texts = []
        with tempfile.TemporaryDirectory() as td:
            for i in range(min(len(pdf), max_pages)):
                png = os.path.join(td, f"p{i}.png")
                pdf[i].render(scale=SCALE).to_pil().save(png)
                r = subprocess.run(["tesseract", png, "-", "--psm", "6"], capture_output=True, text=True)
                texts.append(r.stdout)
        with open(out, "w") as fh:
            fh.write("\n\f\n".join(texts))
        return fid, "ok"
    except Exception as e:
        return fid, f"error: {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--max-pages", type=int, default=12)
    ap.add_argument("--db", default=db.DEFAULT_DB)
    a = ap.parse_args()
    os.makedirs(OCR_DIR, exist_ok=True)
    con = db.connect(a.db)
    rows = con.execute("""SELECT f.file_manager_id, f.local_path, d.fields FROM files f JOIN docs d USING(file_manager_id)
                          WHERE f.downloaded=1 AND d.kind='other'""").fetchall()
    jobs = [(r[0], r[1], a.max_pages) for r in rows if not json.loads(r[2] or "{}").get("has_text", True)]
    print(f"OCR {len(jobs)} image-only PDFs with {a.workers} workers", file=sys.stderr)
    n = 0
    with ProcessPoolExecutor(a.workers) as ex:
        for fid, st in ex.map(ocr_pdf, jobs, chunksize=4):
            n += 1
            if st.startswith("error") or n % 100 == 0:
                print(f"  {n}/{len(jobs)} {fid} {st}", file=sys.stderr)
    print("done", file=sys.stderr)


if __name__ == "__main__":
    main()
