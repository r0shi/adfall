"""Thin client for the FCC Online Public Inspection File (OPIF) API.

The FCC's edge rejects Python's urllib with HTTP 403 but accepts curl with the
same headers, so every request shells out to curl. All endpoints are public
and need no key. Terms: https://www.fcc.gov/developer/api-terms-of-service
("This product uses the FCC Data API but is not endorsed or certified by the FCC").

Every call returns or raises explicitly: get_json raises FccError (with the HTTP status
and the last error text) after `tries` attempts with exponential backoff; download returns
a (status, reason) pair and never leaves a partial file at `dest`.
"""
import hashlib, json, logging, os, subprocess, time, urllib.parse

log = logging.getLogger("ingest.fcc")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/128 Safari/537.36"
BASE = "https://publicfiles.fcc.gov/api/manager"
FILES = "https://files.fcc.gov/download"
MIN_PDF_BYTES = 200


class FccError(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


def _curl(args, timeout):
    r = subprocess.run(["curl", "-s", "-S", "-m", str(timeout), "-A", UA, *args], capture_output=True, text=True)
    return r


def get_json(url, tries=5, timeout=90):
    err, code = None, None
    for i in range(tries):
        r = _curl(["-w", "\n%{http_code}", url], timeout)
        body, _, code = r.stdout.rpartition("\n")
        code = code.strip()
        try:
            d = json.loads(body)
            if d.get("statusCode") in (200, "200") or d.get("status") == "success":
                return d
            err = d.get("statusMessage") or d.get("message") or body[:120]
        except ValueError:
            err = (body[:120] or r.stderr.strip()[:120] or f"HTTP {code}")
        if code in ("403",):                       # blocked: no point hammering
            break
        time.sleep(min(60, 1.5 * 2 ** i) if code in ("429", "503", "502", "000", "") else 1.5 * (i + 1))
    raise FccError(f"{url}: HTTP {code} {err}", code=code)


def folder_by_path(entity_id, path, service="tv"):
    d = get_json(f"{BASE}/folder/path.json?entityId={entity_id}&sourceService={service}&folderPath={urllib.parse.quote(path)}")
    f = d.get("folder") or []
    return f[0] if f else None


def folder_by_id(entity_id, folder_id, service="tv"):
    return get_json(f"{BASE}/folder/id/{folder_id}.json?entityId={entity_id}&sourceService={service}").get("folder") or {}


def walk(entity_id, path, service="tv", pause=0.1):
    """Yield (folder_path, file_record) for every file under `path`. The first yield is
    ("__count__", file_count) with the API's own count for the folder, or nothing if the folder is absent.
    Raises FccError if any folder call fails after retries; the caller decides whether the partial
    listing is kept."""
    top = folder_by_path(entity_id, path, service)
    if not top:
        return
    d = folder_by_id(entity_id, top["entity_folder_id"], service)
    yield "__count__", d.get("file_count")
    stack = []
    for f in d.get("files") or []:
        yield path, f
    for sf in d.get("subfolders") or []:
        stack.append((sf["entity_folder_id"], path + "/" + sf["folder_name"]))
    while stack:
        fid, fpath = stack.pop()
        d = folder_by_id(entity_id, fid, service)
        for f in d.get("files") or []:
            yield fpath, f
        for sf in d.get("subfolders") or []:
            stack.append((sf["entity_folder_id"], fpath + "/" + sf["folder_name"]))
        time.sleep(pause)


def file_history(start, end, count=500, offset=0):
    """Global change feed: every file added/removed across all stations in [start, end]."""
    return get_json(f"{BASE}/file/history.json?startDate={start}&endDate={end}&count={count}&offset={offset}").get("history") or []


def check_pdf(path):
    """(ok, reason) for a file on disk: a real PDF of plausible size, fully written."""
    try:
        size = os.path.getsize(path)
    except OSError as e:
        return False, f"missing: {e}"
    if size < MIN_PDF_BYTES:
        return False, f"too small ({size} bytes)"
    with open(path, "rb") as fh:
        head = fh.read(8)
        if not head.startswith(b"%PDF"):
            return False, f"not a PDF (starts {head[:8]!r})"
        fh.seek(max(0, size - 4096))
        tail = fh.read()
    if b"%%EOF" not in tail and b"endobj" not in tail and b"stream" not in tail:
        return False, "truncated (no PDF trailer)"
    return True, None


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(file_manager_id, dest, timeout=180, tries=3):
    """Download one PDF to `dest` atomically (via dest.part). Returns (ok, reason, size)."""
    part = dest + ".part"
    reason = None
    for i in range(tries):
        if os.path.exists(part):
            os.remove(part)
        r = _curl(["-L", "-o", part, "-w", "%{http_code}", f"{FILES}/{file_manager_id}.pdf"], timeout)
        code = r.stdout.strip()
        if code == "200":
            ok, why = check_pdf(part)
            if ok:
                os.replace(part, dest)
                return True, None, os.path.getsize(dest)
            reason = why
            if why and why.startswith("not a PDF"):          # an HTML error page with status 200: treat as server trouble
                time.sleep(2 * (i + 1)); continue
            break
        reason = f"HTTP {code}" + (f" ({r.stderr.strip()[:80]})" if code in ("000", "") and r.stderr else "")
        if code in ("404", "403", "410"):
            break                                            # permanent for this attempt; the caller caps attempts
        time.sleep(min(30, 2 * 2 ** i))
    if os.path.exists(part):
        os.remove(part)
    return False, reason, None
