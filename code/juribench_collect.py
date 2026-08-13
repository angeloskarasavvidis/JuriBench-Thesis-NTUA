# %% [markdown]
# # JuriBench — Large Scale Collection (fixed)
#
# Fixed from `code/student-code/juribench_student.py`:
# - API token pulled from env var, not hardcoded
# - Cell 5 combine filenames now match Cell 2-4 output filenames
# - `cluster_id` added to FIELDNAMES (traceability / future backfill)
# - `issue_area` + `issue_area_source` columns added (join wiring TBD — see code/issues.md)
# - target/date reconciled to docstring's stated intent: 1000/court, 2020-01-01 -> 2024-12-31
#
# Stratification (by court x ideology x date) intentionally NOT implemented here —
# downstream task, out of scope for this collector.
#
# **Target:** 1000 substantive opinions per court x 3 courts = 3000 total
# **Period:** 2020-01-01 -> 2024-12-31
# **Courts:** SCOTUS . CA5 . CA9
#
# Each court runs in its own cell and saves immediately to a separate CSV.
# If one cell fails or times out, re-run only that cell -- the others are already saved.
#
# **Outputs:**
# - `juribench_scotus_2020_2024.csv`
# - `juribench_ca5_2020_2024.csv`
# - `juribench_ca9_2020_2024.csv`
#
# Run Cell 1 (shared setup) first, then each court cell independently.
#

# %%
# ============================================================
# CELL 1 — Shared setup: run this once before any court cell
# ============================================================

import csv, os, re, sys, time
import requests
from dotenv import load_dotenv
from html.parser import HTMLParser

csv.field_size_limit(sys.maxsize)  # opinion_text can exceed default 131072-char field limit

# ── CONFIG — CL_API_TOKEN read from .env, do not hardcode ──
load_dotenv()
API_TOKEN = os.environ.get("CL_API_TOKEN", "")
if not API_TOKEN:
    raise SystemExit("Set CL_API_TOKEN in .env (see .env.example) before running the collector.")
# ─────────────────────────────────────────────────────────────

BASE_URL = "https://www.courtlistener.com/api/rest/v4"
HEADERS  = {"Authorization": f"Token {API_TOKEN}"}

# Date range
DATE_AFTER  = "2020-01-01"
DATE_BEFORE = "2024-12-31"

# Target per court
TARGET = 1000

# Columns saved (cluster_id kept for traceability; issue_area TBD join)
FIELDNAMES = [
    "jurisdiction", "court_id", "cluster_id", "case_name", "date_filed",
    "court", "judge_name", "judge_id", "syllabus", "opinion_text",
    "issue_area", "issue_area_source",
]

SKIP_NAMES = {"per curiam","per_curiam","percuriam","the court","court",""}
NOISE_WORDS = {
    "opinion","unpublished","memorandum","order","filed","submitted",
    "argued","before","panel","for","publication","the","united","states",
    "court","of","appeals","ninth","fifth","circuit","per","curiam",
    "honorable","judge","judges","chief","senior","visiting","district",
}

# ── HTML stripper ────────────────────────────────────────────
class _StripHTML(HTMLParser):
    def __init__(self): super().__init__(); self.parts = []
    def handle_data(self, d): self.parts.append(d)
    def get_text(self): return " ".join(self.parts)

def strip_html(html):
    p = _StripHTML(); p.feed(html); return p.get_text()

# ── Request with retry ───────────────────────────────────────
def req(url, params=None):
    for attempt in range(1, 5):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=60)
            r.raise_for_status()
            return r
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
            wait = attempt * 15
            print(f"  Timeout — waiting {wait}s (attempt {attempt}/4)...")
            time.sleep(wait)
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            if code in (429, 500, 502, 503, 504) and attempt < 4:
                wait = attempt * 15
                print(f"  HTTP {code} — waiting {wait}s (attempt {attempt}/4)...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"All retries failed for {url}")

# ── Step 0 filter ────────────────────────────────────────────
def is_substantive(judge_name, text):
    if not judge_name or judge_name.strip() == "":
        return False, "no judge name"
    if judge_name.strip().lower().replace(" ","") in SKIP_NAMES:
        return False, "per curiam"
    wc = len(text.split())
    if wc < 500:
        return False, f"too short ({wc} words)"
    return True, "ok"

# ── Syllabus extraction ──────────────────────────────────────
def extract_syllabus(text):
    text = re.sub(r'\r\n|\r', '\n', text)
    start = re.search(r'(?im)^\s*syllabus\s*$', text)
    if not start:
        start = re.search(r'(?i)syllabus\s+NOTE:', text)
    if start:
        after    = text[start.start():]
        note_end = re.search(r'NOTE:.*?convenience of the reader\.[^\n]*\n', after, flags=re.S|re.I)
        content  = text[start.start() + (note_end.end() if note_end else 50):]
        end_pos  = len(content)
        for pat in [r'(?im)^\s*Held[:\s]',
                    r'(?im)^\s*(CHIEF\s+)?JUSTICE\s+\w+\s+delivered',
                    r'(?im)^\s*(CHIEF\s+)?JUSTICE\s+\w+,\s+(concurring|dissenting)',
                    r'(?im)^\s*opinion\s+of\s+(the\s+court|justice)',
                    r'(?im)^\s*per\s+curiam']:
            m = re.search(pat, content)
            if m and m.start() < end_pos:
                end_pos = m.start()
        block = content[:end_pos].strip()
        for para in [p.strip() for p in re.split(r'\n{2,}', block) if p.strip()]:
            if len(para) > 80:
                return para
        if block:
            return block.split('\n')[0].strip()
    for para in [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]:
        if len(para) < 100: continue
        if sum(1 for c in para if c.isupper()) / max(len(para),1) > 0.5: continue
        if re.search(r'(?i)(argued|submitted|decided|filed|no\.\s*\d)', para[:60]): continue
        return para[:600]
    return ""

# ── Opinion text ─────────────────────────────────────────────
def get_opinion_text(sub_opinions):
    for op_url in sub_opinions:
        try:
            data = req(op_url).json()
            time.sleep(1)
            for field in ["html_with_citations","html_columbia","html_lawbox",
                          "html_anon_2020","html","plain_text","xml_harvard"]:
                raw = (data.get(field) or "").strip()
                if raw:
                    return strip_html(raw) if field != "plain_text" else raw
        except Exception as e:
            print(f"    Warning opinion fetch: {e}")
    return ""

# ── Judge name extraction ────────────────────────────────────
def smart_titlecase(s):
    alpha = [c for c in s if c.isalpha()]
    if not alpha: return s
    return s.title() if sum(1 for c in alpha if c.isupper())/len(alpha) > 0.6 else s

def parse_panel_string(raw):
    raw = re.sub(r',?\s*(?:Chief\s+)?(?:Senior\s+)?(?:Circuit|District|Visiting|Bankruptcy)?\s*Judge[s]?[,.]?',
                 ',', raw, flags=re.I)
    raw = re.sub(r'\band\b', ',', raw, flags=re.I)
    raw = re.sub(r'\b([A-Z])\.\s*', '', raw)
    last_names, seen = [], set()
    for part in [p.strip().strip('.,').strip() for p in raw.split(',')]:
        if not part or len(part) < 2 or len(part) > 40: continue
        if part.lower() in NOISE_WORDS: continue
        if part.lower().replace(" ","") in SKIP_NAMES: continue
        if re.search(r'\d', part): continue
        words = [w for w in part.split() if w.lower() not in NOISE_WORDS]
        if not words: continue
        last = words[-1].strip(".\'")
        if not re.match(r"^[A-Za-z'\-]{2,20}$", last): continue
        if last.lower() in SKIP_NAMES or last.lower() in NOISE_WORDS: continue
        last = smart_titlecase(last)
        if last.lower() not in seen:
            seen.add(last.lower())
            last_names.append(last)
    return last_names

def extract_judges_from_text(text):
    text = re.sub(r'\r\n|\r', '\n', text)
    m = re.search(r'(?i)\bBefore[:\s]+(.{10,300}?)(?:\n\n|$)', text, re.DOTALL)
    if m:
        result = parse_panel_string(m.group(1))
        if result: return result
    m = re.search(r'([A-Z][A-Za-z\'\. ,]{5,200}?),\s*Circuit\s+Judge', text)
    if m:
        result = parse_panel_string(m.group(1))
        if result: return result
    m = re.search(r'([A-Z][A-Za-z\'\-]+),\s*(?:Chief\s+)?(?:Senior\s+)?Circuit\s+Judge:', text)
    if m:
        last = smart_titlecase(m.group(1).strip())
        if last.lower() not in SKIP_NAMES:
            return [last]
    return []

def resolve_judges(panel_urls, judges_str, opinion_text=""):
    # Only use names, no API lookup — ideology added later
    names = []
    if judges_str:
        for raw in judges_str.split(","):
            n = raw.strip()
            if n and n.lower().replace(" ","") not in SKIP_NAMES:
                names.append(n)
        if names:
            return "; ".join(names), ""
    if opinion_text:
        extracted = extract_judges_from_text(opinion_text)
        if extracted:
            return "; ".join(extracted), ""
    return "", ""

# ── Core fetch function ──────────────────────────────────────

def fetch_court(court_id, jurisdiction, output_file, target=TARGET):
    from datetime import date

    MAX_CONSECUTIVE_DROPS = 7

    print(f"\n{'='*65}")
    print(f"  {jurisdiction} ({court_id})  |  target={target}  |  {DATE_AFTER} → {DATE_BEFORE}")
    print(f"{'='*65}")

    # Build month list (2020-01 -> 2024-12), iterate newest -> oldest
    months = []
    d = date(2020, 1, 1)
    while d <= date(2024, 12, 1):
        months.append(d)
        if d.month == 12:
            d = date(d.year + 1, 1, 1)
        else:
            d = date(d.year, d.month + 1, 1)
    months.reverse()

    print(f"  {len(months)} months | round-robin one candidate/month per pass, stop at target total")

    # Resume: pick up already-collected rows from a prior interrupted run
    results, dropped = [], 0
    seen_ids = set()
    dropped_file = output_file + ".dropped_ids"
    file_exists = os.path.exists(output_file) and os.path.getsize(output_file) > 0
    if file_exists:
        with open(output_file, encoding="utf-8") as f:
            results = list(csv.DictReader(f))
        seen_ids = {r["cluster_id"] for r in results if r.get("cluster_id")}
        print(f"  Resuming: {len(results)} rows already in {output_file}, skipping their cluster_ids")
    if os.path.exists(dropped_file):
        with open(dropped_file, encoding="utf-8") as f:
            dropped_ids = {line.strip() for line in f if line.strip()}
        seen_ids |= dropped_ids
        print(f"  Resuming: {len(dropped_ids)} previously-dropped cluster_ids also skipped")
    dropped_f = open(dropped_file, "a", encoding="utf-8")

    out_f  = open(output_file, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(out_f, fieldnames=FIELDNAMES)
    if not file_exists:
        writer.writeheader()
        out_f.flush()

    # Round-robin state: one queue/cursor per month, advanced one hit at a time.
    # Cycling months instead of draining one before the next means no single
    # month can monopolize the target — every month gets an equal number of
    # attempts before any month gets a second one.
    def month_bounds(month_start):
        if month_start.month == 12:
            return date(month_start.year + 1, 1, 1)
        return date(month_start.year, month_start.month + 1, 1)

    month_states = []
    for month_start in months:
        month_end = month_bounds(month_start)
        month_states.append({
            "month_start": month_start,
            "month_str":   month_start.strftime("%Y-%m"),
            "next_url":    f"{BASE_URL}/search/",
            "params": {
                "type": "o", "court": court_id,
                "filed_after":    month_start.strftime("%Y-%m-%d"),
                "filed_before":   month_end.strftime("%Y-%m-%d"),
                "stat_Published": "on",
                "order_by":       "score desc",
                "page_size":      20,
            },
            "queue":             [],
            "consecutive_drops": 0,
            "exhausted":         False,
            "kept":              0,
        })

    def refill_queue(m):
        while not m["queue"] and m["next_url"]:
            if m["params"]:
                resp = req(m["next_url"], m["params"])
                m["params"] = None
            else:
                resp = req(m["next_url"])
            data = resp.json()
            hits = data.get("results", [])
            m["next_url"] = data.get("next")
            time.sleep(2)
            if not hits:
                break
            for hit in hits:
                cid = hit.get("cluster_id")
                if cid and str(cid) not in seen_ids:
                    m["queue"].append(hit)

    while len(results) < target and any(not m["exhausted"] for m in month_states):
        for m in month_states:
            if len(results) >= target:
                break
            if m["exhausted"]:
                continue

            if not m["queue"]:
                refill_queue(m)
            if not m["queue"]:
                m["exhausted"] = True
                continue

            hit = m["queue"].pop(0)
            cluster_id = hit.get("cluster_id")
            if not cluster_id or str(cluster_id) in seen_ids:
                continue
            seen_ids.add(str(cluster_id))

            month_str  = m["month_str"]
            case_name  = hit.get("caseName") or hit.get("case_name", "Unknown")
            date_filed = hit.get("dateFiled") or hit.get("date_filed", "?")
            court_name = hit.get("court", court_id)

            print(f"  [{len(results)+1}] {month_str} | {case_name[:50]} ({date_filed})", end=" ")

            try:
                cluster = req(f"{BASE_URL}/clusters/{cluster_id}/").json()
                time.sleep(1)
            except Exception as e:
                print(f"→ SKIP (cluster failed: {e})")
                m["consecutive_drops"] += 1
                if m["consecutive_drops"] >= MAX_CONSECUTIVE_DROPS:
                    m["exhausted"] = True
                continue

            sub_opinions = cluster.get("sub_opinions", [])
            panel_urls   = cluster.get("panel", [])
            judges_str   = cluster.get("judges", "")

            full_text = get_opinion_text(sub_opinions)
            syllabus  = extract_syllabus(full_text) if full_text else ""
            judge_name_str, judge_id_str = resolve_judges(panel_urls, judges_str, full_text)

            ok, reason = is_substantive(judge_name_str, full_text)
            if not ok:
                print(f"→ DROP ({reason})")
                dropped += 1
                m["consecutive_drops"] += 1
                dropped_f.write(f"{cluster_id}\n")
                dropped_f.flush()
                if m["consecutive_drops"] >= MAX_CONSECUTIVE_DROPS:
                    print(f"  → {month_str}: {MAX_CONSECUTIVE_DROPS} consecutive drops, giving up on this month")
                    m["exhausted"] = True
                continue

            m["consecutive_drops"] = 0
            print(f"→ KEEP ✓")
            m["kept"] += 1
            row = {
                "jurisdiction":       jurisdiction,
                "court_id":           court_id,
                "cluster_id":         cluster_id,
                "case_name":          case_name,
                "date_filed":         date_filed,
                "court":              court_name,
                "judge_name":         judge_name_str,
                "judge_id":           judge_id_str,
                "syllabus":           syllabus,
                "opinion_text":       full_text,
                "issue_area":         "",   # TBD — SCDB (SCOTUS) / Lawma (circuit) join, see code/issues.md
                "issue_area_source":  "",
            }
            results.append(row)
            writer.writerow(row)
            out_f.flush()

    print("  → per-month yield:")
    for m in month_states:
        print(f"     {m['month_str']}: kept {m['kept']}" + ("  (exhausted)" if m["exhausted"] else ""))

    out_f.close()
    dropped_f.close()
    print(f"\n✓ Saved {len(results)} rows → {output_file}")
    print(f"  Final: kept={len(results)}, dropped={dropped}")
    return results

# %%
# ============================================================
# CELL 2 — SCOTUS  (Supreme Court of the United States)
# Target: 1000 cases | 2020–2024
# Output: juribench_scotus_2020_2024.csv
# ============================================================

scotus_cases = fetch_court(
    court_id     = "scotus",
    jurisdiction = "SCOTUS",
    output_file  = "juribench_scotus_2020_2024.csv",
    target       = TARGET,
)
print(f"\nSCOTUS done: {len(scotus_cases)} cases collected.")


# %%
# ============================================================
# CELL 3 — CA5  (5th Circuit Court of Appeals)
# Target: 1000 cases | 2020–2024
# Output: juribench_ca5_2020_2024.csv
# ============================================================

ca5_cases = fetch_court(
    court_id     = "ca5",
    jurisdiction = "CA5",
    output_file  = "juribench_ca5_2020_2024.csv",
    target       = TARGET,
)
print(f"\nCA5 done: {len(ca5_cases)} cases collected.")


# %%
# ============================================================
# CELL 4 — CA9  (9th Circuit Court of Appeals)
# Target: 1000 cases | 2020–2024
# Output: juribench_ca9_2020_2024.csv
# ============================================================

ca9_cases = fetch_court(
    court_id     = "ca9",
    jurisdiction = "CA9",
    output_file  = "juribench_ca9_2020_2024.csv",
    target       = TARGET,
)
print(f"\nCA9 done: {len(ca9_cases)} cases collected.")


# %%
# ============================================================
# CELL 5 — Combine all 3 CSVs into one master file
# Run only after all 3 court cells have completed
# ============================================================

import csv, sys
csv.field_size_limit(sys.maxsize)

master = []
for fname, jur in [
    ("juribench_scotus_2020_2024.csv", "SCOTUS"),
    ("juribench_ca5_2020_2024.csv",    "CA5"),
    ("juribench_ca9_2020_2024.csv",    "CA9"),
]:
    try:
        with open(fname, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        master.extend(rows)
        print(f"  {jur:8}: {len(rows):5} rows  ←  {fname}")
    except FileNotFoundError:
        print(f"  {jur:8}: FILE NOT FOUND — {fname} (cell not run yet?)")

if master:
    out = "juribench_combined_2020_2024.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=master[0].keys())
        writer.writeheader()
        writer.writerows(master)
    print(f"\n✓ Combined: {len(master)} total rows → {out}")
else:
    print("Nothing to combine yet.")


# %%
# ============================================================
# CELL 6 — Quick stats on the combined file
# ============================================================

import csv, sys
from collections import Counter
csv.field_size_limit(sys.maxsize)

try:
    with open("juribench_combined_2020_2024.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
except FileNotFoundError:
    print("Run Cell 5 first.")
    rows = []

if rows:
    by_jur  = Counter(r["jurisdiction"] for r in rows)
    by_year = Counter(r["date_filed"][:4] for r in rows if r.get("date_filed"))
    has_syllabus = sum(1 for r in rows if r.get("syllabus","").strip())
    has_judges   = sum(1 for r in rows if r.get("judge_name","").strip())
    no_text      = sum(1 for r in rows if len((r.get("opinion_text") or "").split()) < 10)

    print(f"Total rows    : {len(rows)}")
    print()
    print("By jurisdiction:")
    for jur, n in sorted(by_jur.items()):
        print(f"  {jur:8}: {n}")
    print()
    print("By year:")
    for yr, n in sorted(by_year.items()):
        print(f"  {yr}: {n}")
    print()
    print(f"Has syllabus  : {has_syllabus}/{len(rows)} ({has_syllabus/len(rows):.1%})")
    print(f"Has judge name: {has_judges}/{len(rows)} ({has_judges/len(rows):.1%})")
    print(f"Empty text    : {no_text}")
