# Domain & Pattern Generation + Final Aggregation

This repository (or set of scripts) performs a **two-part** process:

1. **Part 1**: A Selenium-based script that **queries** a data source for each `action_tracker_id` and produces a **domain-to-pattern** file (called `final_url_variations.csv`).  
2. **Part 2**: A **post-processing** script (the aggregator) that **reads** `final_url_variations.csv`, determines relevant keywords, and scans the **raw CSV data** (`query_{action_tracker_id}.csv`) for actual usage counts.

---

## Part 1: Domain & Pattern Generation

### Overview

- We run a **Selenium** script that navigates to a Query Runner page.  
- For each **`action_tracker_id`**, it **submits** a SQL query, **downloads** the resulting CSV (renaming it to `query_{action_tracker_id}.csv`), and **extracts** domain + campaign + path.  
- It **unifies** all paths per domain, building **regex-like** patterns based on a known set of **keywords** (e.g., “order,” “checkout,” etc.).  
- Finally, it writes **`final_url_variations.csv`** with columns:

  - **domain**  
  - **action_tracker_ids** (comma-separated if multiple)  
  - **campaign_ids** (comma-separated if multiple)  
  - **patterns** (a JSON array of the generated path patterns)

### Important Note on Chrome

Because this script is **actively** driving a **Chrome** browser for each query, **keep** that browser **visible** and **undisturbed**.  
- Don’t minimize it or switch windows excessively.  
- Avoid manual interaction or resizing that could block Selenium clicks.  

If Chrome is **moved** off-screen or heavily minimized, Selenium might fail to click the “Submit” or “CSV” radio, causing incomplete downloads or timeouts.

### Usage Steps

1. **Install Requirements**  
   - You need Python 3, plus the `selenium` library.  
   - Ensure you have a compatible Chrome + ChromeDriver.  

2. **Run the Script**  
   ```bash
   python combine_tracker.py