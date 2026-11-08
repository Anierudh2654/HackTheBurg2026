#!/usr/bin/env python3
"""
Fetch primary texts + CourtListener bulk data, hash everything, write a manifest.

    export GBA_CONTACT_EMAIL=you@example.com          # required: goes in the User-Agent
    python fetch_and_hash.py texts                    # Part B: official PDFs/HTML (small, minutes)
    python fetch_and_hash.py bulk --list              # Part A: show latest bulk files + sizes (no download)
    python fetch_and_hash.py bulk                     # Part A: download + filter to Delaware (LARGE, hours)
    python fetch_and_hash.py bulk --skip-opinions     # cheaper, see NOTE below

Outputs (./data_out): raw/ (saved files), de_citation_map.csv, de_clusters.csv, manifest.json, MANIFEST.md

NOTE on --skip-opinions: the citation map uses OPINION ids, the clusters file uses CLUSTER ids. The only
file that maps one to the other is the opinions file (the largest, includes full text). --skip-opinions assumes
opinion_id == cluster_id, which is often true for older cases but NOT guaranteed. Fine for a demo; label it so.

Not verified by the author (no network in the build sandbox): bulk file names/sizes/columns other than the
citation-map header (id, depth, cited_opinion_id, citing_opinion_id) given in FLP's docs. The script reads
headers from the files themselves and records them in the manifest, so nothing is assumed in the output.
"""
import bz2, csv, datetime as dt, hashlib, json, os, re, sys, time, urllib.parse, urllib.request
import urllib.robotparser, xml.etree.ElementTree as ET

OUT = os.environ.get("GBA_DATA_OUT", "data_out")
RAW = os.path.join(OUT, "raw")
EMAIL = os.environ.get("GBA_CONTACT_EMAIL")
if not EMAIL: sys.exit("Set GBA_CONTACT_EMAIL (honest contact in User-Agent).")
UA = f"GuardedLegalAgent/1.0 (contact: {EMAIL})"
TODAY = dt.date.today().isoformat()
os.makedirs(RAW, exist_ok=True)
_csv_limit = sys.maxsize
while True:
    try:
        csv.field_size_limit(_csv_limit)
        break
    except OverflowError:
        _csv_limit //= 10

S3 = "https://com-courtlistener-storage.s3-us-west-2.amazonaws.com"
TERMS_URL = "https://wiki.free.law/c/courtlistener/help/api/bulk-data/bulk-legal-data"
TERMS_LINE = "FLP: bulk files are 'free of known copyright restrictions' (Public Domain Mark); snapshots, quarterly."
DE_COURTS = {"del", "delch"}   # CourtListener court ids for Delaware Supreme Court / Court of Chancery (verify in courts file)

# Part B: URLs seen on official sites during research on 2026-11-07
TEXTS = [
  dict(item="Match Group 315 A.3d 446 (Del. 2024), No. 368, 2022", url="https://courts.delaware.gov/Opinions/Download.aspx?id=362250", official=True, fname="match_group_2024.pdf"),
  dict(item="SB 21 (SS 1) bill detail page, 153rd GA", url="https://legis.delaware.gov/BillDetail/141930", official=True, fname="sb21_ss1_billdetail.html"),
  dict(item="SB 21 (SS 1) enrolled text HTML", url="https://legis.delaware.gov/json/BillDetail/GenerateHtmlDocument?legislationId=141930&legislationTypeId=6&docTypeId=2&legislationName=SS1forSB21", official=True, fname="sb21_ss1_text.html"),
  dict(item="SB 21 session law, 85 Del. Laws c. 6 (PDF)", url="https://legis.delaware.gov/SessionLaws/Chapter/GetPdfDocument?fileAttachmentId=647918", official=True, fname="sb21_session_law_85_del_laws_c6.pdf"),
  dict(item="HB 353 (2026) bill detail page", url="https://legis.delaware.gov/BillDetail?LegislationId=143065", official=True, fname="hb353_billdetail.html"),
  dict(item="HB 353 as enacted, 85 Del. Laws c. 279 (PDF)", url="https://www.legis.delaware.gov/SessionLaws/Chapter/GetPdfDocument?fileAttachmentId=655934", official=True, fname="hb353_session_law_85_del_laws_c279.pdf"),
]
# Weinberger: no official courts.delaware.gov copy found. MANUAL step, see MANIFEST.md.

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def robots_ok(url):
    u = urllib.parse.urlparse(url)
    rp = urllib.robotparser.RobotFileParser(f"{u.scheme}://{u.netloc}/robots.txt")
    try: rp.read()
    except Exception: return None   # unknown
    return rp.can_fetch(UA, url)

def get(url, dest, resume=False):
    have = os.path.getsize(dest) if resume and os.path.exists(dest) else 0
    req = urllib.request.Request(url, headers={"User-Agent": UA, **({"Range": f"bytes={have}-"} if have else {})})
    with urllib.request.urlopen(req, timeout=120) as r:
        status = r.status
        # Only append when the server honored the Range request. Otherwise
        # restart the file so a full 200 response cannot corrupt a partial file.
        append = have > 0 and status == 206
        if have > 0 and status != 206:
            have = 0
        with open(dest, "ab" if append else "wb") as f:
            while chunk := r.read(1 << 20): f.write(chunk)
    return status

def do_texts():
    man = []
    for t in TEXTS:
        rb = robots_ok(t["url"]); dest = f"{RAW}/{t['fname']}"
        row = dict(item=t["item"], url=t["url"], retrieval_date=TODAY, official=t["official"],
                   robots_allows=rb, terms_checked=False, sha256=None, bytes=None, status="skipped")
        if rb is False:
            row["status"] = "robots_disallowed: download by hand from the URL, then run: python fetch_and_hash.py hash <file>"
        else:
            try:
                row["http"] = get(t["url"], dest); row["sha256"] = sha256_file(dest)
                row["bytes"] = os.path.getsize(dest); row["status"] = "ok"
            except Exception as e:
                row["status"] = f"error: {e}"
        print(row["status"], "-", t["item"]); man.append(row); time.sleep(2)
    write_manifest(texts=man)

def s3_list(prefix="bulk-data/"):
    out, token = [], None
    while True:
        q = {"list-type": "2", "prefix": prefix, **({"continuation-token": token} if token else {})}
        with urllib.request.urlopen(urllib.request.Request(f"{S3}/?{urllib.parse.urlencode(q)}", headers={"User-Agent": UA}), timeout=60) as r:
            root = ET.fromstring(r.read())
        ns = {"s": root.tag.split("}")[0].strip("{")}
        for c in root.findall("s:Contents", ns):
            out.append((c.find("s:Key", ns).text, int(c.find("s:Size", ns).text)))
        if root.find("s:IsTruncated", ns).text != "true": return out
        token = root.find("s:NextContinuationToken", ns).text

def latest(files, stem):
    c = sorted([f for f in files if re.search(rf"/{stem}-\d{{4}}-\d{{2}}-\d{{2}}\.csv(\.bz2)?$", f[0])])
    return c[-1] if c else None

def rows_of(path):
    op = bz2.open if path.endswith(".bz2") else open
    with op(path, "rt", encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f); yield rd.fieldnames
        for r in rd: yield r

def do_bulk(list_only, skip_opinions):
    files = s3_list()
    want = {s: latest(files, s) for s in ["courts", "dockets", "opinion-clusters", "citation-map", "citations", "opinions"]}
    for s, v in want.items(): print(f"{s:18} {v[0] if v else 'NOT FOUND'}  {v[1]/1e6 if v else 0:,.0f} MB")
    if list_only: return
    paths = {}
    for s, v in want.items():
        if not v or (s == "opinions" and skip_opinions): continue
        dest = f"{RAW}/{os.path.basename(v[0])}"
        print("downloading", v[0]); get(f"{S3}/{v[0]}", dest, resume=True); paths[s] = dest
    # filter chain
    it = rows_of(paths["courts"]); hdr = next(it)
    court_ids = {r["id"] for r in it if r["id"] in DE_COURTS}
    assert court_ids, f"no Delaware court ids found; headers were {hdr}"
    it = rows_of(paths["dockets"]); next(it)
    dockets = {r["id"] for r in it if r["court_id"] in court_ids}
    it = rows_of(paths["opinion-clusters"]); chdr = next(it)
    clusters = [r for r in it if r["docket_id"] in dockets]
    cids = {r["id"] for r in clusters}
    # reporter citations (separate table: cluster_id, volume, reporter, page ...)
    cites = {}
    if "citations" in paths:
        it = rows_of(paths["citations"]); next(it)
        for r in it:
            if r["cluster_id"] in cids: cites.setdefault(r["cluster_id"], []).append(f"{r['volume']} {r['reporter']} {r['page']}")
    with open(f"{OUT}/de_clusters.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["cluster_id", "case_name", "date_filed", "citations", "court_id", "docket_id"])
        dcourt = {}
        for r in clusters: w.writerow([r["id"], r.get("case_name", ""), r.get("date_filed", ""), "; ".join(cites.get(r["id"], [])), "del/delch", r["docket_id"]])
    # opinion id -> cluster id
    if skip_opinions: op2cl = {c: c for c in cids}
    else:
        it = rows_of(paths["opinions"]); next(it)
        op2cl = {r["id"]: r["cluster_id"] for r in it if r["cluster_id"] in cids}
    n = 0
    with open(f"{OUT}/de_citation_map.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["citing_cluster_id", "cited_cluster_id", "citing_opinion_id", "cited_opinion_id", "depth"])
        it = rows_of(paths["citation-map"]); mhdr = next(it)
        for r in it:
            a, b = r["citing_opinion_id"], r["cited_opinion_id"]
            if a in op2cl and b in op2cl: w.writerow([op2cl[a], op2cl[b], a, b, r["depth"]]); n += 1
    meta = dict(terms_url=TERMS_URL, terms_summary=TERMS_LINE, download_date=TODAY, skip_opinions=skip_opinions,
                files={s: dict(name=os.path.basename(p), bytes=os.path.getsize(p), sha256=sha256_file(p)) for s, p in paths.items()},
                clusters_header=chdr, citation_map_header=mhdr, delaware_clusters=len(clusters), delaware_citation_edges=n)
    for p in (f"{OUT}/de_clusters.csv", f"{OUT}/de_citation_map.csv"):
        meta["files"][os.path.basename(p)] = dict(bytes=os.path.getsize(p), sha256=sha256_file(p), rows=sum(1 for _ in open(p)) - 1)
    write_manifest(bulk=meta)

def write_manifest(texts=None, bulk=None):
    p = f"{OUT}/manifest.json"; m = json.load(open(p)) if os.path.exists(p) else {}
    if texts is not None: m["texts"] = texts
    if bulk is not None: m["bulk"] = bulk
    json.dump(m, open(p, "w"), indent=2)
    L = [f"# Manifest (generated {TODAY})", "", "| item | URL | retrieved | SHA-256 | official | terms checked | status |", "|---|---|---|---|---|---|---|"]
    for t in m.get("texts", []):
        L.append(f"| {t['item']} | {t['url']} | {t['retrieval_date']} | {t['sha256'] or ''} | {'yes' if t['official'] else 'no'} | {'yes' if t['terms_checked'] else 'no'} | {t['status']} |")
    if "bulk" in m:
        L += ["", f"Bulk terms: {m['bulk']['terms_url']} - {m['bulk']['terms_summary']}", "", "| file | bytes | rows | SHA-256 |", "|---|---|---|---|"]
        L += [f"| {k} | {v['bytes']} | {v.get('rows','')} | {v['sha256']} |" for k, v in m["bulk"]["files"].items()]
        L += ["", f"Headers: clusters={m['bulk']['clusters_header']}  citation_map={m['bulk']['citation_map_header']}"]
    open(f"{OUT}/MANIFEST.md", "w").write("\n".join(L))

def do_hash(files):
    """For files you downloaded by hand (e.g. Weinberger). Prompts for URL, appends to manifest."""
    m = json.load(open(f"{OUT}/manifest.json")) if os.path.exists(f"{OUT}/manifest.json") else {}
    texts = m.get("texts", [])
    for fp in files:
        url = input(f"Source URL for {fp}: ").strip(); off = input("Official source? (y/n): ").strip().lower() == "y"
        texts.append(dict(item=os.path.basename(fp), url=url, retrieval_date=TODAY, official=off, robots_allows=None,
                          terms_checked=False, sha256=sha256_file(fp), bytes=os.path.getsize(fp), status="manual"))
    write_manifest(texts=texts)

if __name__ == "__main__":
    a = sys.argv[1:]
    if not a: sys.exit(__doc__)
    if a[0] == "texts": do_texts()
    elif a[0] == "bulk": do_bulk("--list" in a, "--skip-opinions" in a)
    elif a[0] == "hash": do_hash(a[1:])
    else: sys.exit(__doc__)
