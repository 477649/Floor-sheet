import os
import time
import traceback
from datetime import datetime

import pandas as pd
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


URL = "https://chukul.com/floorsheet"

# ✅ GitHub Actions env (set in workflow.yml)
START_DATE = os.getenv("START_DATE", datetime.today().strftime("%Y-%m-%d"))
END_DATE = os.getenv("END_DATE", datetime.today().strftime("%Y-%m-%d"))

HEADER = ["Transact No.", "Symbol", "Buyer", "Seller", "Quantity", "Rate", "Amount"]

# ✅ Date field container having calendar icon text 'event'
DATE_FIELD_XPATH = (
    "//div[contains(@class,'q-field__control-container') "
    "and .//i[contains(@class,'q-icon') and normalize-space()='event']]"
)

# ✅ Calendar popup root
CALENDAR_ROOT_CSS = "div.q-date"

# ✅ "As of: YYYY/MM/DD" text on page (used to verify date really changed)
ASOF_XPATH = "//*[contains(normalize-space(.),'As of:')]"

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]


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
    - Click next page by VISIBLE TEXT (e.g., '139')
    - Wait until first row changes so we don't re-scrape the same page
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
    """
    Reads 'As of: YYYY/MM/DD' from page header.
    Returns 'YYYY/MM/DD' or None.
    """
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


def open_calendar(driver, wait):
    """
    ✅ Headless-safe: scroll + JS click + wait for q-date popup.
    """
    field = wait.until(EC.presence_of_element_located((By.XPATH, DATE_FIELD_XPATH)))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", field)
    time.sleep(0.3)
    driver.execute_script("arguments[0].click();", field)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, CALENDAR_ROOT_CSS)))


def get_calendar_nav_text(driver):
    """Gets navigation text containing month and year (e.g. 'January 2026')."""
    nav = driver.find_element(By.CSS_SELECTOR, "div.q-date__navigation")
    return nav.text.replace("\n", " ").strip()


def click_nav_next_prev(driver, direction):
    """
    Clicks next/prev arrow inside calendar navigation.
    direction: 'next' or 'prev'
    """
    btns = driver.find_elements(By.CSS_SELECTOR, "div.q-date__navigation button")
    if not btns:
        raise RuntimeError("Calendar navigation buttons not found")

    if direction == "prev":
        driver.execute_script("arguments[0].click();", btns[0])
    else:
        driver.execute_script("arguments[0].click();", btns[-1])


def ensure_month_year(driver, wait, target_year, target_month):
    """
    Navigate the calendar popup to target month/year by using next/prev arrows.
    target_month: 1-12
    """
    target_month_name = MONTH_NAMES[target_month - 1]
    target_year_str = str(target_year)

    for _ in range(60):  # safety limit
        nav_txt = get_calendar_nav_text(driver)

        if (target_month_name in nav_txt) and (target_year_str in nav_txt):
            return

        # Determine current month/year
        current_month = None
        for mn in MONTH_NAMES:
            if mn in nav_txt:
                current_month = mn
                break

        current_year = None
        for token in nav_txt.split():
            if token.isdigit() and len(token) == 4:
                current_year = int(token)
                break

        if current_month is None or current_year is None:
            click_nav_next_prev(driver, "next")
            time.sleep(0.2)
            continue

        cur_month_num = MONTH_NAMES.index(current_month) + 1

        if (current_year, cur_month_num) < (target_year, target_month):
            click_nav_next_prev(driver, "next")
        else:
            click_nav_next_prev(driver, "prev")

        time.sleep(0.2)

    raise RuntimeError("Could not reach target month/year in calendar.")


def click_day(driver, wait, day_int):
    """
    ✅ Headless-safe day click.
    Click only in-month days (not out-of-month), scroll into view, JS click.
    """
    day_xpath = (
        f"//div[contains(@class,'q-date__calendar-item') "
        f"and not(contains(@class,'q-date__calendar-item--out'))]"
        f"//*[normalize-space()='{day_int}']"
    )

    el = wait.until(EC.presence_of_element_located((By.XPATH, day_xpath)))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(0.2)
    driver.execute_script("arguments[0].click();", el)


def set_floorsheet_date_by_calendar(driver, wait, date_ymd):
    """
    ✅ Reliable: open calendar popup and click the day.
    Verifies 'As of' changes to the requested date.
    """
    y, m, d = date_ymd.split("-")
    y = int(y)
    m = int(m)
    d_int = int(d)

    target_asof = date_ymd.replace("-", "/")
    before_asof = read_asof_date(driver)

    open_calendar(driver, wait)
    ensure_month_year(driver, wait, y, m)
    click_day(driver, wait, d_int)

    # Wait for table + asof update
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table")))

    for _ in range(30):
        now_asof = read_asof_date(driver)
        if now_asof == target_asof:
            return
        time.sleep(0.2)

    raise RuntimeError(
        f"Date did not apply. Expected As of {target_asof}, got {read_asof_date(driver)} (before was {before_asof})"
    )


def scrape_one_date(driver, wait, date_ymd):
    driver.get(URL)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table")))

    # ✅ Apply date via calendar
    set_floorsheet_date_by_calendar(driver, wait, date_ymd)

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

    dates = pd.date_range(START_DATE, END_DATE, freq="D").strftime("%Y-%m-%d").tolist()
    print(f"Scraping from {START_DATE} to {END_DATE} ({len(dates)} day(s))")

    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")

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
                print("Saving file:", out_xlsx)
                df.to_excel(out_xlsx, index=False)
                print(f"Saved: {out_xlsx}")

            except Exception as e:
                print(f"❌ Failed for date {d}: {repr(e)}")
                traceback.print_exc()
                continue

        # Debug: list files created (helps confirm outputs exists on runner)
        try:
            print("Files in outputs:", os.listdir("outputs"))
        except Exception:
            pass

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
