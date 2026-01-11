import os
import time
from datetime import datetime

import pandas as pd
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


URL = "https://chukul.com/floorsheet"

# ✅ GitHub Actions passes these via workflow env (START_DATE / END_DATE)
# If not passed, it scrapes only today's date.
START_DATE = os.getenv("START_DATE", datetime.today().strftime("%Y-%m-%d"))
END_DATE = os.getenv("END_DATE", datetime.today().strftime("%Y-%m-%d"))

HEADER = ["Transact No.", "Symbol", "Buyer", "Seller", "Quantity", "Rate", "Amount"]

# ✅ Stable date input selector:
# Find the q-field container that has the calendar icon <i ...>event</i>, then pick its input.
DATE_INPUT_XPATH = (
    "//div[contains(@class,'q-field__control-container') and .//i[contains(@class,'q-icon') and normalize-space()='event']]"
    "//input[contains(@class,'q-field__native') and @type='text']"
)


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


def go_to_next_page(driver, current_page):
    """
    Click numeric page button for next page.
    If the site hides page numbers (sliding window) and this stops early,
    tell me and I'll switch to "Next arrow until disabled" logic.
    """
    buttons = driver.find_elements(By.CSS_SELECTOR, "div.q-pagination__middle button")
    target = str(current_page + 1)
    for b in buttons:
        if b.get_attribute("aria-label") == target:
            driver.execute_script("arguments[0].click();", b)
            return True
    return False


def set_floorsheet_date(driver, wait, date_ui):
    """
    ✅ Headless/GitHub-safe:
    - Scroll to date input
    - Set value using JS
    - Dispatch input/change events (Quasar/Vue)
    - Blur + body click to force apply
    date_ui format: 'YYYY/MM/DD'
    """
    date_input = wait.until(EC.presence_of_element_located((By.XPATH, DATE_INPUT_XPATH)))

    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", date_input)

    driver.execute_script(
        """
        const input = arguments[0];
        const val = arguments[1];

        input.focus();
        input.value = val;

        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));

        input.blur();
        document.body.click();
        """,
        date_input,
        date_ui,
    )

    # Wait table to be present, and give a small pause for the data to refresh
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table")))
    time.sleep(1)


def scrape_one_date(driver, wait, date_ymd):
    """
    date_ymd: 'YYYY-MM-DD'
    returns DataFrame for that date
    """
    date_ui = date_ymd.replace("-", "/")

    driver.get(URL)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table")))

    # Set date on the page
    set_floorsheet_date(driver, wait, date_ui)

    all_data = []
    current_page = 1

    while True:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table")))
        all_data.extend(scrape_current_page(driver))

        if not go_to_next_page(driver, current_page):
            break

        current_page += 1
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table")))

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

    dates = pd.date_range(START_DATE, END_DATE, freq="D").strftime("%Y-%m-%d").tolist()
    print(f"Scraping from {START_DATE} to {END_DATE} ({len(dates)} day(s))")

    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=chrome_options)
    wait = WebDriverWait(driver, 30)

    try:
        for d in dates:
            print(f"\n=== Scraping date: {d} ===")
            try:
                df = scrape_one_date(driver, wait, d)

                total_amount = df["Amount"].dropna().sum() if not df.empty else 0
                print(f"Rows: {len(df)} | Total Amount: {total_amount:,.2f}")

                out_xlsx = f"outputs/floorsheet_{d}.xlsx"
                df.to_excel(out_xlsx, index=False)
                print(f"Saved: {out_xlsx}")

            except Exception as e:
                print(f"❌ Failed for date {d}: {e}")
                # Continue to next date even if one date fails
                continue

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
