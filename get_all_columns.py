import os
import time
import csv
import re
import json
from collections import defaultdict
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

MAX_RECORDS = 5000  # Not super relevant for 'SHOW TABLES', but set a limit anyway

DATA_SOURCES = [
    "r_ds_singlestore",
    "r_ds_ods",
    "r_ds_iraction_sharded",
    # Add as many as you like...
]

# Query templates
SHOW_TABLES_SQL = "SHOW TABLES"
DESCRIBE_TABLE_SQL = "DESCRIBE {TABLE_NAME}"  # or "SHOW COLUMNS FROM {TABLE_NAME}"

OPERATOR_QUERY_URL = "https://operator.impactradius.net/secure/operator/report/queryrunner/res/index.html"

DOWNLOAD_DIR = os.path.abspath("downloaded_csv")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

CHROME_PROFILE_DIR = os.path.abspath("my_chrome_profile")

FINAL_CSV_PATH = "all_tables_all_columns.csv"

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

def clear_and_type_sql(sql_query):
    """
    Clear the CodeMirror area and type in the given SQL query.
    """
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

def run_query_and_download_csv(sql_query, datasource, filename_prefix):
    """
    Select the given datasource, enter sql_query, run it, and download the CSV file.
    Returns the path to the downloaded CSV or None if something failed.
    """
    # Re-select data source
    try:
        ds_elem = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "select#dataSourceSelect"))
        )
        Select(ds_elem).select_by_value(datasource)
    except Exception as e:
        print(f"  Could not set data source to {datasource}: {e}")
        return None

    # Set maxRecords
    try:
        max_records_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "maxRecords"))
        )
        max_records_input.clear()
        max_records_input.send_keys(str(MAX_RECORDS))
    except:
        print("  #maxRecords field not found.")
        return None

    # Enter the SQL
    clear_and_type_sql(sql_query)

    # Submit the query
    submit_btn = find_submit_button()
    if not submit_btn:
        print("  ERROR: No submit button.")
        return None

    # Click 'Submit'
    try:
        submit_btn.click()
    except ElementClickInterceptedException:
        print("  Submit intercepted, waiting then retrying.")
        time.sleep(5)
        try:
            submit_btn.click()
        except ElementClickInterceptedException:
            print("  Still failing, skipping.")
            return None

    # Wait for query to run
    print("  Waiting for query to run (10-20s)...")
    time.sleep(10)

    # Select CSV radio
    try:
        csv_radio = driver.find_element(By.ID, "view_csv")
        csv_radio.click()
    except:
        print("  Could not select CSV radio.")
        return None

    time.sleep(3)
    csv_path = os.path.join(DOWNLOAD_DIR, "query.csv")
    final_path = os.path.join(DOWNLOAD_DIR, f"{filename_prefix}.csv")

    time.sleep(2)
    if os.path.exists(csv_path):
        os.rename(csv_path, final_path)
        return final_path
    else:
        print(f"  CSV not found at {csv_path}")
        return None

###############################################################################
# MAIN SCRIPT
###############################################################################

def main():
    try:
        # 1) Go to Query Runner
        print(f"Navigating to {OPERATOR_QUERY_URL} ...")
        driver.get(OPERATOR_QUERY_URL)

        # 2) Wait for manual login if needed
        input("\nLog in if needed. Press Enter once fully loaded...")

        # Data structure to hold [ (datasource, table_name, column_name, column_type, etc.)... ]
        all_columns_data = []

        # 3) For each data source
        for ds in DATA_SOURCES:
            print(f"\n=== Data Source: {ds} ===")
            driver.refresh()
            time.sleep(2)

            # 3.1) "SHOW TABLES"
            show_tables_csv = run_query_and_download_csv(
                SHOW_TABLES_SQL, ds, filename_prefix=f"show_tables_{ds}"
            )
            if not show_tables_csv:
                print(f"Skipping data source {ds} due to error.")
                continue

            # 3.2) Parse the list of tables
            tables_list = []
            with open(show_tables_csv, "r", encoding="utf-8") as f:
                # Some data sources return columns named e.g. "Tables_in_database"
                reader = csv.reader(f)
                header = next(reader, None)
                if not header:
                    print(f"  No header found in {show_tables_csv}, skipping.")
                    continue
                # We'll assume there's only 1 column with table names, but adapt as needed
                table_column_index = 0  # Usually index 0
                for row in reader:
                    if len(row) > table_column_index:
                        table_name = row[table_column_index]
                        table_name = table_name.strip()
                        if table_name:
                            tables_list.append(table_name)

            if not tables_list:
                print(f"  No tables found for {ds}.")
                continue

            print(f"  Found {len(tables_list)} tables in {ds}.")

            # 3.3) For each table: DESCRIBE or SHOW COLUMNS FROM
            for table_name in tables_list:
                describe_sql = DESCRIBE_TABLE_SQL.format(TABLE_NAME=table_name)
                describe_csv = run_query_and_download_csv(
                    describe_sql,
                    ds,
                    filename_prefix=f"describe_{ds}_{table_name.replace('/', '_')}"
                )
                if not describe_csv:
                    print(f"    Skipping table {table_name} due to error.")
                    continue

                # 3.4) Parse the DESCRIBE results
                # Example columns from DESCRIBE table_name:
                # Field, Type, Null, Key, Default, Extra
                with open(describe_csv, "r", encoding="utf-8") as f:
                    desc_reader = csv.DictReader(f)
                    for desc_row in desc_reader:
                        # Grab columns you care about
                        field = desc_row.get("Field", "")
                        col_type = desc_row.get("Type", "")
                        is_null = desc_row.get("Null", "")
                        key_info = desc_row.get("Key", "")
                        default_val = desc_row.get("Default", "")
                        extra = desc_row.get("Extra", "")

                        # Store in the big list
                        all_columns_data.append((
                            ds,
                            table_name,
                            field,
                            col_type,
                            is_null,
                            key_info,
                            default_val,
                            extra
                        ))

        # 4) Write final CSV
        with open(FINAL_CSV_PATH, "w", newline="", encoding="utf-8") as out_f:
            writer = csv.writer(out_f)
            writer.writerow([
                "data_source", "table_name", "column_name", "type",
                "null", "key", "default", "extra"
            ])
            for row_data in all_columns_data:
                writer.writerow(row_data)

        print(f"\nAll done. Wrote {len(all_columns_data)} column definitions to {FINAL_CSV_PATH}.")

        input("\nPress Enter to close...")
    finally:
        print("Closing browser.")
        driver.quit()

if __name__ == "__main__":
    main()
