import os
import csv
import json
import glob
import pandas as pd
from collections import defaultdict

# -------------------------------------------------------------------
# 0) CONFIG
# -------------------------------------------------------------------

# The directory containing query_{action_tracker_id}.csv files
# (the same place your script downloaded them)
QUERY_CSV_DIR = "downloaded_csv"

# The name of the final URL variations CSV from your Selenium flow
FINAL_URL_VARIATIONS_CSV = "final_url_variations.csv"

# Output file
OUTPUT_CSV = "processed_by_tracker.csv"

# Known keywords
KEYWORDS = {
    "billing", "paypal", "account", "checkout", "login", "shipping", "confirmation",
    "subscribe", "purchase", "payment", "blocked", "order", "thank-you",
    "thanks", "cart", "subscription", "success", "check-out"
}

# If you want partial substring ignoring case, we do: any kw.lower() in some_string.lower().


# -------------------------------------------------------------------
# 1) LOAD final_url_variations.csv
# -------------------------------------------------------------------
df = pd.read_csv(FINAL_URL_VARIATIONS_CSV)
df = df.drop(columns=['total_rows', 'keyword_percent'])

# We assume columns like:
#   domain, action_tracker_ids, campaign_ids, patterns, total_rows, keyword_percent
# We can ignore total_rows,keyword_percent per your instructions.

# If your CSV might contain multiple trackers in one row, we parse them.

def parse_comma_strings(val):
    """
    For a string '47064,47065' -> ['47064','47065'].
    """
    if pd.isnull(val) or str(val).strip() == "":
        return []
    return [x.strip() for x in str(val).split(",") if x.strip()]

# Parse columns
if "action_tracker_ids" not in df.columns:
    df["action_tracker_ids"] = ""

df["action_tracker_ids"] = df["action_tracker_ids"].apply(parse_comma_strings)

if "campaign_ids" not in df.columns:
    df["campaign_ids"] = ""
df["campaign_ids"] = df["campaign_ids"].apply(parse_comma_strings)

# If 'patterns' is a JSON-like string, parse it:
def parse_patterns(val):
    if pd.isnull(val):
        return []
    s = str(val).strip()
    # if it looks like '["/billing","/checkout"]' etc.
    if s.startswith("[") and s.endswith("]"):
        try:
            arr = json.loads(s)
            if isinstance(arr, list):
                return arr
            else:
                return [str(arr)]
        except:
            return [s]
    # else treat as a single pattern
    return [s]

if "patterns" not in df.columns:
    df["patterns"] = ""
df["patterns"] = df["patterns"].apply(parse_patterns)

# -------------------------------------------------------------------
# 2) EXPLODE so each row has a single action_tracker_id + campaign_id
# -------------------------------------------------------------------

def explode_trackers(row):
    """
    For each ID in row["action_tracker_ids"], produce a sub-row
    with a single 'action_tracker_id', plus the entire row.
    """
    trackers = row["action_tracker_ids"]
    if not trackers:
        # produce a single row with None
        sub = row.copy()
        sub["action_tracker_id"] = None
        return [sub]
    results = []
    for tid in trackers:
        sub = row.copy()
        sub["action_tracker_id"] = tid
        results.append(sub)
    return results

expanded_rows = []
for i, raw_row in df.iterrows():
    subs = explode_trackers(raw_row)
    expanded_rows.extend(subs)

df_trackers = pd.DataFrame(expanded_rows)
df_trackers.drop("action_tracker_ids", axis=1, inplace=True)

# Now we have one row per action_tracker_id, but possibly multiple campaign_ids in each row.

df_exploded = df_trackers.explode("campaign_ids", ignore_index=True)
df_exploded.rename(columns={"campaign_ids":"campaign_id"}, inplace=True)

# So each row => (action_tracker_id, campaign_id, domain, patterns, ...)

# -------------------------------------------------------------------
# 3) GROUP BY (action_tracker_id, campaign_id) => unify patterns, domain, etc.
# -------------------------------------------------------------------
def flatten_unique(arrs):
    """Flatten lists, deduplicate, return sorted."""
    out = set()
    for item in arrs:
        if isinstance(item, list):
            for x in item:
                out.add(str(x).strip())
        elif pd.notnull(item):
            out.add(str(item).strip())
    return sorted(out)

grouped = (
    df_exploded
    .groupby(["action_tracker_id","campaign_id"], as_index=False)
    .agg({
        "patterns": lambda c: flatten_unique(c),
        "domain": lambda c: flatten_unique(c)
        # if you have other columns to unify, add them here
    })
)

# columns => action_tracker_id, campaign_id, patterns, domain

# -------------------------------------------------------------------
# 4) FOR EACH (tracker_id,campaign_id), find which KEYWORDS appear in all patterns
#    partial substring ignoring case, store them as `found_keywords`
# -------------------------------------------------------------------
def find_keywords_in_patterns(patterns_list):
    """
    patterns_list is e.g. ["/billing/(?:/.*)?", "..."]
    We'll check partial substring ignoring case for each known KEYWORD.
    We unify all that appear.
    """
    found = set()
    # join patterns into one big text or check individually
    for pat in patterns_list:
        pat_lower = pat.lower()
        for kw in KEYWORDS:
            if kw.lower() in pat_lower:  # partial substring
                found.add(kw)
    return sorted(found)

grouped["found_keywords"] = grouped["patterns"].apply(find_keywords_in_patterns)

# -------------------------------------------------------------------
# 5) OPEN query_{action_tracker_id}.csv to see how many lines match ANY of those found_keywords
# -------------------------------------------------------------------
# We'll define a function that, given a tracker_id and a set of found keywords,
# opens 'downloaded_csv/query_{tracker_id}.csv' and checks each row's pageUrl for partial substring ignoring case.
# Then returns (used_count, total_count).
import os

def count_usage_in_csv(tracker_id, found_kws):
    """
    found_kws is a list of keywords (strings).
    We'll open 'downloaded_csv/query_{tracker_id}.csv',
    read 'pageUrl' from each row, ignoring case,
    if ANY kw is in pageUrl.lower(), we count usage.
    Return (used_count, total_count).
    If no CSV found, return (0,0).
    """
    path = os.path.join(QUERY_CSV_DIR, f"query_{tracker_id}.csv")
    if not os.path.exists(path):
        return (0,0)
    used_count = 0
    total_count = 0
    found_kws_lower = [k.lower() for k in found_kws]
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_count += 1
            page_url = (row.get("pageUrl","") or "").lower()
            # if ANY keyword is substring
            if any(kw in page_url for kw in found_kws_lower):
                used_count += 1
    return (used_count, total_count)

# We'll apply this row by row in the aggregator
def usage_stats(row):
    tid = row["action_tracker_id"]
    fkw = row["found_keywords"]
    if pd.isnull(tid):
        return 0,0
    used, tot = count_usage_in_csv(tid, fkw)
    return used, tot

grouped["(used_count, total_count)"] = grouped.apply(usage_stats, axis=1)
grouped["used_count"] = grouped["(used_count, total_count)"].apply(lambda x: x[0])
grouped["total_count"] = grouped["(used_count, total_count)"].apply(lambda x: x[1])
grouped.drop("(used_count, total_count)", axis=1, inplace=True)

# compute used_percent
def compute_used_percent(r):
    if r["total_count"] == 0:
        return 0.0
    return round((r["used_count"] / r["total_count"]) * 100, 2)

grouped["used_percent"] = grouped.apply(compute_used_percent, axis=1)

# unify patterns & domain => join them with '|'
grouped["domain"] = grouped["domain"].apply(lambda arr: "|".join(arr))
grouped["patterns"] = grouped["patterns"].apply(lambda arr: "|".join(arr))
grouped["found_keywords"] = grouped["found_keywords"].apply(lambda arr: "|".join(arr))

# reorder columns
final_cols = [
    "action_tracker_id",
    "campaign_id",
    "domain",
    "patterns",
    "found_keywords",
    "used_count",
    "total_count",
    "used_percent"
]
grouped = grouped[final_cols]

# -------------------------------------------------------------------
# 6) WRITE THE FINAL CSV
# -------------------------------------------------------------------

grouped = grouped.rename(columns={'used_count':'rows_keyword_found_in', 'total_count':'total_rows', 'used_percent':'percent_keyword_match'})
grouped.to_csv(OUTPUT_CSV, index=False)
print(f"Done! Wrote {OUTPUT_CSV}")