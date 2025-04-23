###############################################################################
# impact_column_inventory.py
###############################################################################
import os, csv, pathlib, time
from glob import glob
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

###############################################################################
# CONFIG
###############################################################################
OPERATOR_QUERY_URL = (
    "https://operator.impactradius.net/secure/operator/report/"
    "queryrunner/res/index.html"
)
CHROME_PROFILE_DIR = pathlib.Path("my_chrome_profile").resolve()
DOWNLOAD_DIR       = pathlib.Path("tmp_csv_dl").resolve()      # temp holder
MASTER_CSV         = pathlib.Path("impact_column_inventory.csv")

SQL_CATALOG = """
SELECT table_schema,
       table_name,
       column_name,
       data_type
FROM   information_schema.columns
WHERE  table_schema NOT IN ('pg_catalog','information_schema')
ORDER  BY table_schema, table_name, ordinal_position;
""".strip()

###############################################################################
# SELENIUM SET-UP
###############################################################################
opts = Options()
opts.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
opts.add_experimental_option(
    "prefs",
    {
        "download.default_directory": str(DOWNLOAD_DIR),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
    },
)
driver = webdriver.Chrome(options=opts)
wait   = WebDriverWait(driver, 20)

###############################################################################
def clear_and_type(sql: str) -> None:
    cm = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".CodeMirror")))
    cm.click()
    cm.send_keys(Keys.CONTROL, "a")
    cm.send_keys(sql)

def run_and_dl(shard: str) -> str | None:
    """Run query for current shard, flip to CSV, grab freshest file path."""
    # press run
    driver.find_element(By.XPATH, "//input[@type='submit' or @value='Run Query']").click()
    wait.until(EC.presence_of_element_located((By.ID, "resultTable")))
    driver.find_element(By.ID, "view_csv").click()
    time.sleep(2)

    before = set(DOWNLOAD_DIR.glob("*.csv"))
    time.sleep(1)
    after  = set(DOWNLOAD_DIR.glob("*.csv"))
    new_files = list(after - before)
    return max(new_files, key=lambda p: p.stat().st_mtime) if new_files else None

###############################################################################
# MAIN
###############################################################################
def main():
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    if MASTER_CSV.exists():
        MASTER_CSV.unlink()  # fresh run

    print("➡️  Opening Query Runner …")
    driver.get(OPERATOR_QUERY_URL)
    input("\nLog in if prompted, then press <Enter>…")

    ds_select = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "select#dataSourceSelect")))
    shards = [o.get_attribute("value") for o in ds_select.find_elements(By.TAG_NAME, "option")]
    print(f"📦  {len(shards)} data sources detected.")

    with MASTER_CSV.open("w", newline="", encoding="utf-8") as f_out:
        writer = csv.writer(f_out)
        writer.writerow(["shard", "table_schema", "table_name", "column_name", "data_type"])

        for shard in shards:
            print(f"\n🔍  {shard}")
            Select(wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "select#dataSourceSelect")))).select_by_value(shard)

            try: driver.find_element(By.ID, "maxRecords").clear()
            except: pass  # not critical

            clear_and_type(SQL_CATALOG)
            tmp_csv = run_and_dl(shard)
            if not tmp_csv:
                print(f"   🚫  CSV missing for {shard} — skipping")
                continue

            with tmp_csv.open("r", encoding="utf-8") as src:
                rdr = csv.reader(src)
                header = next(rdr, None)  # toss header
                for row in rdr:
                    writer.writerow([shard] + row)

            tmp_csv.unlink()  # clean up
            print(f"   ✅  added {shard} rows")

    print(f"\n🎉  Master inventory saved → {MASTER_CSV.resolve()}")
    input("\nDone!  Press <Enter> to close…")
    driver.quit()

if __name__ == "__main__":
    main()
