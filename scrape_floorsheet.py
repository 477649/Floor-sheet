import os
import time
import traceback
from datetime import datetime

import pandas as pd
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


URL = "https://chukul.com/floorsheet"

# ✅ Can be YYYY-MM-DD or YYYY/MM/DD
START_DATE_RAW = os.getenv("START_DATE", datetime.today().strftime("%Y-%m-%d"))
END_DATE_RAW = os.getenv("END_DATE", datetime.today().strftime("%Y-%m-%d"))

HEADER = ["Transact No.", "Symbol", "Buyer", "Seller", "Quantity", "Rate", "Amount"]

# ✅ "As of: YYYY/MM/DD" text on page
ASOF_XPATH = "//*[contains(normalize-space(.),'As of:')]"

# ✅ Main date input: class-based (ID changes every refresh)
DATE_INPUT_XPATH = "//input[contains(@class,'q-field__native') and @type='text']"


def normalize_date_str(s: str) -> str:
    """Accepts YYYY-MM-DD or YYYY/MM/DD. Returns YYYY-MM-DD."""
    s = s.strip()
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 3:
            y, m, d = parts
            return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    # assume YYYY-MM-DD
    parts = s.split("-")
    if len(parts) == 3:
        y, m, d = parts
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    raise ValueError(f"Invalid date format: {s}. Use YYYY-MM-DD or YYYY/MM/DD.")


def ymd_to_ui(ymd: str) -> str:
    """YYYY-MM-DD -> YYYY/MM/DD"""
    return ymd.replace("-", "/")


def parse_numeric(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    clean = "".join(c for c in s if c.isdigit() or c == ".")
    try:
        return float(clean) if clean else None
    except ValueError:
        return None


def scrape_current_page(driver):
    soup = BeautifulSoup(driver.page_source, "html.parser")
    table = soup.find("table")
    if not table:
        return []

    rows = table.find_all("tr")
    data = []
    for row in rows:
        cols = row.find_all("td")
        cols_data = [c.get_text(strip=True) for c in cols]
        if cols_data:
            data.append(cols_data)
    return data


def first_row_key(driver):
    """Used to confirm page actually changed after clicking next."""
    try:
        el = driver.find_element(By.CSS_SELECTOR, "table tbody tr td")
        return el.text.strip()
    except Exception:
        return None


def go_to_next_page(driver, wait, current_page):
    """
    ✅ Improved last-page capture logic:
    - Click next page by VISIBLE TEXT
    - Wait until first row changes so we don't re-scrape same page
    """
    target = str(current_page + 1)

    buttons = driver.find_elements(
        By.XPATH,
        f"//div[contains(@class,'q-pagination')]//button[normalize-space()='{target}']"
    )
    if not buttons:
        return False

    before = first_row_key(driver)
    driver.execute_script("arguments[0].click();", buttons[0])

    if before is not None:
        wait.until(lambda d: first_row_key(d) != before)
    else:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table")))

    return True


def read_asof_date(driver):
    """Returns 'YYYY/MM/DD' from 'As of: YYYY/MM/DD', or None."""
    try:
        el = driver.find_element(By.XPATH, ASOF_XPATH)
        txt = el.text.strip()
        if "As of:" in txt:
            part = txt.split("As of:")[1].strip().split()[0]
            if "/" in part:
                return part
    except Exception:
        pass
    return None


def set_floorsheet_date_text(driver, wait, date_ymd):
    """
    ✅ GitHub Actions SAFE method:
    - Focus date input
    - Clear
    - Type YYYY/MM/DD
    - Press ENTER
    - Blur + body click
    - Verify 'As of:' updated
    """
    date_ui = ymd_to_ui(date_ymd)
    before_asof = read_asof_date(driver)

    # Find the date input (ID changes, so use class)
    input_el = wait.until(EC.presence_of_element_located((By.XPATH, DATE_INPUT_XPATH)))

    # Scroll and focus
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", input_el)
    time.sleep(0.2)
    driver.execute_script("arguments[0].click();", input_el)
    time.sleep(0.1)

    # Clear: Ctrl+A then Backspace (more reliable than .clear() on Quasar)
    input_el.send_keys(Keys.CONTROL, "a")
    input_el.send_keys(Keys.BACKSPACE)
    time.sleep(0.05)

    # Type date + Enter
    input_el.send_keys(date_ui)
    input_el.send_keys(Keys.ENTER)

    # Force commit
    driver.execute_script("arguments[0].blur();", input_el)
    driver.execute_script("document.body.click();")

    # Wait for table (page usually refreshes)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table")))

    # Verify the date actually applied
    for _ in range(30):
        now = read_asof_date(driver)
        if now == date_ui:
            return
        time.sleep(0.25)

    raise RuntimeError(
        f"Date did not apply via text input. Expected As of {date_ui}, got {read_asof_date(driver)} (before was {before_asof})"
    )


def scrape_one_date(driver, wait, date_ymd):
    driver.get(URL)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table")))

    # ✅ Apply date reliably (no popup calendar)
    set_floorsheet_date_text(driver, wait, date_ymd)

    all_data = []
    current_page = 1

    while True:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table")))
        all_data.extend(scrape_current_page(driver))
        print(f"Scraped page: {current_page}")

        if not go_to_next_page(driver, wait, current_page):
            print("Reached last page.")
            break

        current_page += 1

    if not all_data:
        return pd.DataFrame(columns=HEADER)

    df = pd.DataFrame(all_data)
    if df.shape[1] != len(HEADER):
        raise ValueError(f"Column mismatch: got {df.shape[1]} cols, expected {len(HEADER)}")

    df.columns = HEADER
    df["Quantity"] = df["Quantity"].apply(parse_numeric)
    df["Rate"] = df["Rate"].apply(parse_numeric)
    df["Amount"] = df["Amount"].apply(parse_numeric)

    return df


def main():
    os.makedirs("outputs", exist_ok=True)

    start_date = normalize_date_str(START_DATE_RAW)
    end_date = normalize_date_str(END_DATE_RAW)

    dates = pd.date_range(start_date, end_date, freq="D").strftime("%Y-%m-%d").tolist()
    print(f"Scraping from {start_date} to {end_date} ({len(dates)} day(s))")

    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(options=chrome_options)
    wait = WebDriverWait(driver, 45)  # a bit longer for GitHub runners

    try:
        for d in dates:
            print(f"\n=== Scraping date: {d} ===")
            try:
                df = scrape_one_date(driver, wait, d)

                total_amount = df["Amount"].dropna().sum() if not df.empty else 0
                print(f"Rows: {len(df)} | Total Amount: {total_amount:,.2f}")

                out_xlsx = f"outputs/floorsheet_{d}.xlsx"
                print("Saving file:", out_xlsx)
                df.to_excel(out_xlsx, index=False)
                print(f"Saved: {out_xlsx}")

            except Exception as e:
                print(f"❌ Failed for date {d}: {repr(e)}")
                traceback.print_exc()
                continue

        print("Files in outputs:", os.listdir("outputs"))

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
