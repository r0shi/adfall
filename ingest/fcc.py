"""Thin client for the FCC Online Public Inspection File (OPIF) API.

The FCC's edge rejects Python's urllib with HTTP 403 but accepts curl with the
same headers, so every request shells out to curl. All endpoints are public
and need no key. Terms: https://www.fcc.gov/developer/api-terms-of-service
("This product uses the FCC Data API but is not endorsed or certified by the FCC").
"""
import json, subprocess, time, urllib.parse

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/128 Safari/537.36"
BASE = "https://publicfiles.fcc.gov/api/manager"
FILES = "https://files.fcc.gov/download"


class FccError(Exception):
    pass


def get_json(url, tries=4, timeout=90):
    err = None
    for i in range(tries):
        r = subprocess.run(["curl", "-s", "-m", str(timeout), "-A", UA, url], capture_output=True, text=True)
        try:
            d = json.loads(r.stdout)
            if d.get("statusCode") in (200, "200") or d.get("status") == "success":
                return d
            err = d.get("statusMessage")
        except ValueError:
            err = r.stdout[:120] or r.stderr[:120]
        time.sleep(1.5 * (i + 1))
    raise FccError(f"{url}: {err}")


def folder_by_path(entity_id, path, service="tv"):
    d = get_json(f"{BASE}/folder/path.json?entityId={entity_id}&sourceService={service}&folderPath={urllib.parse.quote(path)}")
    f = d.get("folder") or []
    return f[0] if f else None


def folder_by_id(entity_id, folder_id, service="tv"):
    return get_json(f"{BASE}/folder/id/{folder_id}.json?entityId={entity_id}&sourceService={service}").get("folder") or {}


def walk(entity_id, path, service="tv", pause=0.1):
    """Yield (folder_path, file_record) for every file under `path`."""
    top = folder_by_path(entity_id, path, service)
    if not top:
        return
    stack = [(top["entity_folder_id"], path)]
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


def download(file_manager_id, dest, timeout=180):
    r = subprocess.run(["curl", "-s", "-L", "-m", str(timeout), "-A", UA, "-o", dest, "-w", "%{http_code}",
                        f"{FILES}/{file_manager_id}.pdf"], capture_output=True, text=True)
    return r.stdout.strip() == "200"
