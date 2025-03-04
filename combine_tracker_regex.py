import csv
import re
import json
import os
from collections import defaultdict

INPUT_CSV = "final_url_variations.csv"
OUTPUT_CSV = "tracker_regex.csv"


def escape_slashes_for_regex101(pattern: str) -> str:
    """
    Replaces every unescaped '/' with '\/'.
    If any unescaped slash remains after replacement, we raise an error.
    """
    # Use a regex that finds '/' not preceded by a backslash:
    escaped = re.sub(r'(?<!\\)/', r'\/', pattern)

    # Double-check if there's still any unescaped slash left:
    unescaped_slash = re.search(r'(?<!\\)/', escaped)
    if unescaped_slash:
        # We can raise or just print a warning
        raise ValueError(f"Failed to escape all slashes in pattern: {escaped}")

    return escaped


def validate_python_regex(pat: str) -> bool:
    """
    Attempts to compile 'pat' as a Python regex.
    If valid, return True. If not valid, return False.
    """
    try:
        re.compile(pat)
        return True
    except re.error:
        return False


def main():
    """
    1) Reads final_url_variations.csv with columns:
       [domain, action_tracker_ids, patterns (JSON array)]
    2) Groups domains/patterns by each tracker ID.
    3) Builds a single OR-based pattern:
       ^https?:\/\/(?:(?:[\w.-]+\.)?dom_escaped(?:p1|p2) | ...) (?:\?.*)?$
    4) Escapes slashes for /.../ usage on Regex101, then wraps it in leading+trailing '/'.
    5) Validates in Python's re.compile(...) to catch syntax errors.
    6) Writes tracker_regex.csv with columns: [action_tracker_dim_id, regex_for_regex101].
    """
    if not os.path.exists(INPUT_CSV):
        print(f"ERROR: Could not find input CSV '{INPUT_CSV}'.")
        return

    # aggregator_map[tracker_id] = list of (domain, pattern_list)
    aggregator_map = defaultdict(list)

    # Read in final_url_variations.csv
    with open(INPUT_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            domain_str = row["domain"].strip()
            at_ids_str = row["action_tracker_ids"].strip()  # e.g. "153246,33996"
            patterns_json = row["patterns"].strip()

            try:
                pattern_list = json.loads(patterns_json)  # e.g. ["/billing(?:/.*)?", "/paypal(?:/.*)?"]
            except:
                pattern_list = []

            if at_ids_str:
                splitted = [x.strip() for x in at_ids_str.split(",") if x.strip()]
                for tid in splitted:
                    aggregator_map[tid].append((domain_str, pattern_list))

    results = []

    for tid, domain_info in aggregator_map.items():
        # domain_info is a list of (domain, pattern_list)
        # unify domain->set_of_patterns
        domain_patterns_map = defaultdict(set)
        for (dom, p_list) in domain_info:
            domain_patterns_map[dom].update(p_list)

        # build an OR pattern
        # e.g. ^https?:\/\/(?:
        #   (?:[\w.-]+\.)?domain1(?:p1|p2) |
        #   (?:[\w.-]+\.)?domain2(...)
        # )(?:\?.*)?$

        domain_blocks = []
        for dom, pat_set in domain_patterns_map.items():
            # remove leading "www."
            dom_core = dom
            if dom_core.startswith("www."):
                dom_core = dom_core[4:]
            dom_escaped = re.escape(dom_core)

            # join the patterns in an OR
            # e.g. (?:/billing(?:/.*)?|/paypal(?:/.*)?)
            sorted_pats = sorted(pat_set)
            joined_pats = "|".join(sorted_pats)
            if len(sorted_pats) > 1:
                pattern_block = f"(?:{joined_pats})"
            else:
                pattern_block = joined_pats  # if only one pat, no need for (?: )

            sub_block = rf"(?:[\w.-]+\.)?{dom_escaped}(?:{pattern_block})"
            domain_blocks.append(sub_block)

        if domain_blocks:
            or_clause = "|".join(domain_blocks)
            raw_pattern = rf"^https?:\/\/(?:{or_clause})(?:\?.*)?$"
        else:
            raw_pattern = r"^$"  # fallback if no domain/pattern?

        # let's do a Python re.compile failsafe check:
        # We'll check 'raw_pattern' which is unescaped from the Python perspective.
        if not validate_python_regex(raw_pattern):
            print(f"WARNING: Pattern for tracker {tid} is invalid in Python: {raw_pattern}")
            # we can skip or forcibly fix?
            # We'll just forcibly produce it anyway, but note the warning.

        # escape slashes:
        final_escaped = escape_slashes_for_regex101(raw_pattern)
        # wrap with delimiter
        final_for_regex101 = f"/{final_escaped}/"

        results.append((tid, final_for_regex101))

    # write to tracker_regex.csv
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as out_f:
        writer = csv.writer(out_f)
        writer.writerow(["action_tracker_dim_id", "regex_for_regex101"])
        for tid, pat in sorted(results, key=lambda x: x[0]):
            writer.writerow([tid, pat])

    print(f"Done! Wrote {len(results)} rows to {OUTPUT_CSV}.")


if __name__ == "__main__":
    main()