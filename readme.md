# Two-Part Data Processing: Domain/Pattern Generation & Usage Aggregation

This project uses **two separate scripts** to build a **final** usage report:

1. **Part 1**: A Selenium-based script that **queries** for each `action_tracker_id` and produces a **domains-to-patterns** dataset.  
2. **Part 2**: An **aggregator** that **reads** those domain/pattern mappings, discovers **which keywords** apply, and checks the **raw CSV** data for actual usage counts.

---

## Part 1: Domain & Pattern Generation

### Purpose

- This script **logs into** a Query Runner page (via Selenium),  
- **Submits** a SQL query for each `action_tracker_id`,  
- **Renames** each downloaded CSV to `query_{id}.csv`,  
- **Parses** each row’s `pageUrl`, extracting **domain**, **campaign_id**, and **path** segments,  
- **Builds** a set of **regex-like path patterns** influenced by a known list of **keywords** (to decide literal vs. generic path segments).

### Output

- The script **writes** a file (e.g., `final_url_variations.csv`) with columns:
  - **domain**  
  - **action_tracker_ids** (comma-separated if multiple)  
  - **campaign_ids** (comma-separated if multiple)  
  - **patterns** (a JSON array of the final regex-like path definitions)  
- **Note**: It **does not** store row counts or percentages. Those are **ignored** in this updated version.

### Requirements

- **Python 3** and `selenium`.  
- A working **Chrome** + **ChromeDriver** environment.

### Usage

1. **Run** the script (e.g., `python part1_pattern_script.py`).  
2. A **Chrome** window appears at the Query Runner page.  
   - If needed, **log in** (SSO or credentials).  
   - Keep this browser **visible** and **undisturbed** (avoid minimizing or covering it). Selenium must be able to click “Submit” or “CSV” radio.  
3. **After** queries finish, the script merges domain + path data into `final_url_variations.csv` for you to use in Part 2.

---

## Part 2: Usage Aggregation & Keyword Discovery

### Purpose

- **Reads** the `final_url_variations.csv` from Part 1.  
- **Groups** or “explodes” the data so each row is a single `(tracker, campaign)` pair, merging or flattening **domains** and **patterns**.  
- **Scans** those patterns to find **which keywords** appear (partial substring, ignoring case).  
- **Opens** the **raw** CSV (`query_{tracker_id}.csv`) for each tracker to see how many lines actually contain those discovered keywords in their `pageUrl`.

### Process

1. **Parse** the `action_tracker_ids`, `campaign_ids`, and `patterns` from `final_url_variations.csv`.  
2. **Unify** or **explode** multiple trackers/campaigns if a single row has them.  
3. **Flatten** domains and patterns into a single set for each `(tracker_id, campaign_id)`.  
4. **Check** partial substring matches in the pattern text to find relevant keywords.  
   - e.g., if “order” is a keyword, and the pattern is “/orderConfirmation(?:/.*)?”, we note “order” as discovered.  
5. **For** each `(tracker_id, campaign_id)`, open the raw CSV file `query_{tracker_id}.csv`:  
   - For every row’s `pageUrl`, see if **any** discovered keyword is present, ignoring capitals.  
   - Count how many URLs matched (`used_count`) vs. total lines (`total_count`).  
   - Compute `used_percent = (used_count / total_count) * 100`.  

6. **Write** a new aggregator CSV with columns such as:  
   - **tracker_id**  
   - **campaign_id**  
   - **domain** (unified)  
   - **patterns** (unified or flattened)  
   - **found_keywords** (joined by `|`)  
   - **used_count**, **total_count**, **used_percent**

### Why Two Scripts?

- We **separate** domain/path building (Part 1) from usage stats (Part 2).  
- It’s easier to tweak the path pattern logic or the usage checks independently.  
- We ensure usage is calculated **directly** from each raw `query_{tracker_id}.csv`, giving accurate final stats.

---

## Additional Considerations

1. **Keywords**  
   - You can adjust the `KEYWORDS` set in both scripts if your relevant terms change.  
   - In Part 1, keywords help decide if a path segment should be literal.  
   - In Part 2, the same or extended set can help you detect actual usage.

2. **Chrome Visibility**  
   - During Part 1, **do not** minimize or obscure Chrome too much—Selenium might fail to click certain elements if the browser is invisible.  
   - If your environment can’t keep it visible, consider running with a headless Chrome setup (but that sometimes introduces additional complexities with interactions).

3. **Performance**  
   - If `ACTION_TRACKER_IDS` is large, you might break it into multiple runs.  
   - `MAX_RECORDS` determines how many lines per query. If that’s too large, the Query Runner might take a long time.

4. **Post-Processing**  
   - After Part 2 writes its final aggregator, you have one CSV row per `(tracker, campaign)` with the domain/pattern info **and** the usage stats. That’s typically your end deliverable.

---

## Summary

- **Part 1** builds the fundamental domain/pattern dataset without row counts or percentages.  
- **Part 2** uses that data to find relevant keywords and measure how often they appear in the **raw** logs, giving you accurate usage metrics.  
- Keeping the Chrome window **visible** is crucial for Selenium’s UI-driven approach.  