import os
import time
import csv
import re
import json
from collections import defaultdict, Counter
from urllib.parse import urlparse

from selenium import webdriver
from selenium.common.exceptions import ElementClickInterceptedException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

###############################################################################
# CONFIG
###############################################################################

MAX_RECORDS = 20000

# If "order" is in this set, "orderConfirmation" or "preOrder" should also match
KEYWORDS = {
    "billing", "paypal", "account", "checkout", "login", "shipping", "confirmation",
    "subscribe", "purchase", "payment", "blocked", "order", "thank-you",
    "thanks", "cart", "subscription", "success", "check-out"
}

problematic_ids = []

ACTION_TRACKER_IDS = [
    40284, 22753, 10920, 16655, 8776, 29199, 40912, 21290, 33770,
    # ... (rest of your IDs) ...
    38225
]

SQL_TEMPLATE = """
SELECT
    campaign_dim_id,
    campaign_id,
    action_tracker_id,
    oid,
    LENGTH(oid) AS oid_length,
    CASE
        WHEN (method like '%XHR%' OR method like '%BEACON%' OR (method like '%PIXEL%' AND json like '%jsver%')) THEN 'utt'
        WHEN method like '%API%' THEN 'conv_api'
        WHEN method like '%BATCH%' THEN 'ftp'
        ELSE 'other'
    END AS sub_method,
    method,
    CASE
        WHEN oid REGEXP '^[0-9]+$' THEN 'Numeric'
        WHEN oid REGEXP '^[A-Za-z]+$' THEN 'Alphabetic'
        WHEN oid REGEXP '^[A-Za-z0-9]+$' THEN 'Alphanumeric'
        ELSE 'Special Characters Present'
    END AS oid_type,
    LEFT(oid, 3) AS prefix,
    JSON_EXTRACT_STRING(json, 'pageUrl') AS pageUrl
FROM conversion_fact
WHERE event_datetime >= NOW() - INTERVAL 2 DAY
  AND network_id = 1
  AND action_tracker_id = {ACTION_TRACKER_ID}
  AND oid != '' AND oid IS NOT NULL
"""

OPERATOR_QUERY_URL = "https://operator.impactradius.net/secure/operator/report/queryrunner/res/index.html"

DOWNLOAD_DIR = os.path.abspath("downloaded_csv")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

CHROME_PROFILE_DIR = os.path.abspath("my_chrome_profile")

FINAL_CSV_PATH = "final_url_variations.csv"

###############################################################################
# SELENIUM SETUP
###############################################################################

chrome_options = Options()
chrome_options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
chrome_options.add_experimental_option("prefs", {
    "download.default_directory": DOWNLOAD_DIR,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "plugins.always_open_pdf_externally": True
})

driver = webdriver.Chrome(options=chrome_options)

###############################################################################
# HELPER FUNCTIONS
###############################################################################

def find_submit_button():
    """
    Try multiple locators for the 'Submit' or 'Run Query' button.
    """
    locators = [
        (By.XPATH, "//input[@value='Submit']"),
        (By.XPATH, "//button[contains(text(),'Submit')]"),
        (By.ID, "submitBtn"),
        (By.XPATH, "//input[@value='Run Query']"),
        (By.XPATH, "//button[contains(text(),'Run Query')]"),
    ]
    for how, what in locators:
        try:
            return driver.find_element(how, what)
        except:
            pass
    return None

def is_alpha_hyphen(segment):
    """
    Return True if the segment is purely letters or hyphens (e.g. 'account-blocked').
    """
    return bool(re.match(r'^[A-Za-z-]+$', segment))

def build_path_pattern_with_suffix(path, freq_counter):
    """
    Produce a regex-like pattern for 'path', appending '(?:/.*)?' to allow anything after.
    If a segment is alpha/hyphen and repeated or it contains a KEYWORD substring, keep it literal.
    Otherwise, classify as [0-9]+, [A-Za-z]+, [A-Za-z0-9]+, or [^/]+.
    """
    segs = path.strip("/").split("/") if path.strip("/") else []
    if not segs:
        return "/(?:/.*)?"

    pattern_parts = []
    for seg in segs:
        seg_lower = seg.lower()

        literal_flag = False
        if is_alpha_hyphen(seg):
            # If freq>=1 or any KEYWORD is a substring
            if freq_counter[seg] >= 1:
                literal_flag = True
            else:
                for kw in KEYWORDS:
                    if kw.lower() in seg_lower:
                        literal_flag = True
                        break

        if literal_flag:
            pattern_parts.append(re.escape(seg))
            continue

        # else classify
        if re.match(r'^[0-9]+$', seg):
            pattern_parts.append("[0-9]+")
        elif re.match(r'^[A-Za-z]+$', seg):
            pattern_parts.append("[A-Za-z]+")
        elif re.match(r'^[A-Za-z0-9]+$', seg):
            pattern_parts.append("[A-Za-z0-9]+")
        else:
            pattern_parts.append("[^/]+")

    core = "/".join(pattern_parts)
    return f"/{core}(?:/.*)?"

###############################################################################
# MAIN SCRIPT
###############################################################################

def main():
    try:
        print("\nNavigating to Operator Query Runner page...")
        driver.get(OPERATOR_QUERY_URL)

        input("\nIf needed, log in with Google. Press Enter once loaded...")

        # Attempt to set data source once
        try:
            wait = WebDriverWait(driver, 10)
            ds_elem = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "select#dataSourceSelect")))
            Select(ds_elem).select_by_value("r_ds_singlestore")
            print("Data source changed to r_ds_singlestore initially.")
        except Exception as e:
            print(f"Couldn't change data source initially: {e}")

        # We'll store domain -> {tracker_ids,set, campaign_ids:set, paths:set}
        domain_data = defaultdict(lambda: {"tracker_ids": set(), "campaign_ids": set(), "paths": set()})

        for atid in ACTION_TRACKER_IDS:
            print(f"\n--- Processing action_tracker_id = {atid} ---")
            driver.refresh()
            time.sleep(2)

            # re-select data source
            try:
                ds_elem = driver.find_element(By.CSS_SELECTOR, "select#dataSourceSelect")
                Select(ds_elem).select_by_value("r_ds_singlestore")
                print("  Data source re-selected to r_ds_singlestore.")
            except Exception as e:
                print(f"  Could not set data source: {e}")

            # set maxRecords
            try:
                wait = WebDriverWait(driver, 10)
                max_records_input = wait.until(
                    EC.presence_of_element_located((By.ID, "maxRecords"))
                )
            except:
                # fallback
                try:
                    max_records_input = driver.find_element(By.XPATH, "//input[@name='maxRecords']")
                except:
                    max_records_input = None

            if max_records_input:
                max_records_input.clear()
                max_records_input.send_keys(str(MAX_RECORDS))
                print(f"  Set Max Records to {MAX_RECORDS}.")
            else:
                print("  #maxRecords field not found. Skipping this ID.")
                problematic_ids.append(atid)
                continue

            # Build SQL
            sql_query = SQL_TEMPLATE.format(ACTION_TRACKER_ID=atid).strip()

            # Clear + type in CodeMirror
            code_mirror_area = None
            try:
                code_mirror_area = driver.find_element(By.CSS_SELECTOR, ".CodeMirror-code")
            except:
                code_mirror_area = driver.find_element(By.CSS_SELECTOR, ".CodeMirror")

            code_mirror_area.click()
            time.sleep(0.5)
            actions = ActionChains(driver)
            actions.key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL)
            actions.send_keys(Keys.DELETE)
            actions.send_keys(sql_query)
            actions.perform()
            print("  Entered SQL command.")

            # submit
            submit_btn = find_submit_button()
            if not submit_btn:
                print("  ERROR: No submit button. Skipping.")
                problematic_ids.append(atid)
                continue

            time.sleep(1)
            try:
                submit_btn.click()
            except ElementClickInterceptedException:
                print("  Submit intercepted, waiting then retrying.")
                time.sleep(5)
                try:
                    submit_btn.click()
                except ElementClickInterceptedException:
                    print("  Still failing, skipping ID.")
                    problematic_ids.append(atid)
                    continue

            print("  Wait 20s for query to run...")
            time.sleep(20)

            # CSV radio
            try:
                csv_radio = driver.find_element(By.ID, "view_csv")
                csv_radio.click()
                print("  Selected 'CSV' radio.")
            except:
                print("  Could not select CSV radio... skipping")
                problematic_ids.append(atid)
                continue

            time.sleep(3)
            csv_path = os.path.join(DOWNLOAD_DIR, "query.csv")
            renamed_path = os.path.join(DOWNLOAD_DIR, f"query_{atid}.csv")

            time.sleep(2)
            if os.path.exists(csv_path):
                os.rename(csv_path, renamed_path)
                print(f"  Renamed {csv_path} -> {renamed_path}")

                # parse
                row_count = 0
                with open(renamed_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        row_count += 1
                        full_url = row.get("pageUrl", "").strip()
                        if not full_url:
                            continue

                        parsed = urlparse(full_url)
                        domain = parsed.netloc.lower().split(':')[0]
                        path_str = parsed.path or "/"
                        c_id = row.get("campaign_id", "").strip()

                        domain_data[domain]["tracker_ids"].add(atid)
                        domain_data[domain]["campaign_ids"].add(c_id)
                        domain_data[domain]["paths"].add(path_str)

                print(f"  Parsed {row_count} rows from query_{atid}.csv")
            else:
                print(f"  {csv_path} not found. Skipping {atid}.")
                problematic_ids.append(atid)
                continue

        # finalize
        results = []
        for dom, info in domain_data.items():
            if not info["paths"]:
                continue

            t_list = sorted(info["tracker_ids"])
            t_str = ",".join(str(x) for x in t_list)

            c_list = sorted(info["campaign_ids"])
            c_str = ",".join(c_list)

            # Build freq_counter for path segments
            freq_counter = Counter()
            for p in info["paths"]:
                segs = p.strip("/").split("/") if p.strip("/") else []
                for seg in segs:
                    freq_counter[seg] += 1

            # Transform each path -> pattern
            path_patterns = []
            for p in sorted(info["paths"]):
                pat = build_path_pattern_with_suffix(p, freq_counter)
                path_patterns.append(pat)

            unique_patterns = sorted(set(path_patterns))
            patterns_json = json.dumps(unique_patterns)

            # We'll only store domain, trackers, campaigns, patterns
            results.append((dom, t_str, c_str, patterns_json))

        results.sort(key=lambda x: x[0])

        # Write final CSV
        with open(FINAL_CSV_PATH, "w", newline="", encoding="utf-8") as out_f:
            writer = csv.writer(out_f)
            writer.writerow(["domain", "action_tracker_ids", "campaign_ids", "patterns"])
            for row_data in results:
                writer.writerow(row_data)

        print(f"\nWrote {len(results)} domain entries to {FINAL_CSV_PATH}.")
        print("Problematic IDs:", problematic_ids)

        input("\nAll queries done. Press Enter to close...")

    finally:
        print("Closing browser.")
        driver.quit()

if __name__ == "__main__":
    main()