import os
import re
import time
from datetime import datetime, timezone, timedelta

import pandas as pd
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


URL = "https://chukul.com/floorsheet"

# ----------------------------
# DATE PICKER (ADDED PART ONLY)
# ----------------------------
QDATE_ROOT_CSS = "div.q-menu.q-position-engine div.q-date"
MONTH_VIEW_CSS = "div.q-date__view.q-date__months.flex.flex-center"
DAY_VIEW_CSS = ".q-date__calendar-days-container"
YEAR_HEADER_CSS = ".q-date__header-subtitle.q-date__header-link"
YEAR_VIEW_CSS = ".q-date__years-content"

NAV_MONTH_BTN_XPATH = (
    "//div[contains(@class,'q-date__navigation')]"
    "//button[.//span[@class='block' and translate(normalize-space(.),'0123456789','')!='']]"
)

NAV_YEAR_BTN_XPATH = (
    "//div[contains(@class,'q-date__navigation')]"
    "//button[.//span[@class='block' and string-length(normalize-space(.))=4 "
    "and translate(normalize-space(.),'0123456789','')='']]"
)

MONTH_ABBR = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR",
    5: "MAY", 6: "JUN", 7: "JUL", 8: "AUG",
    9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC"
}


def wait_qdate(driver, timeout=20):
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, QDATE_ROOT_CSS))
    )


def find_date_input(driver):
    """
    Finds the date input on the page (value like YYYY/MM/DD).
    """
    inputs = driver.find_elements(By.XPATH, "//input[(@type='text' or not(@type))]")
    for el in inputs:
        try:
            if not (el.is_displayed() and el.is_enabled()):
                continue
            val = (el.get_attribute("value") or "").strip()
            if re.fullmatch(r"\d{4}/\d{2}/\d{2}", val) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", val):
                return el
        except Exception:
            pass
    return None


def open_calendar(driver, timeout=20):
    """
    Opens the date picker by clicking the date input.
    """
    el = find_date_input(driver)
    if not el:
        raise RuntimeError("Date input not found")
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    driver.execute_script("arguments[0].click();", el)
    wait_qdate(driver, timeout)
    time.sleep(0.1)


def get_current_year(driver, timeout=20) -> int:
    root = wait_qdate(driver, timeout)
    return int(root.find_element(By.CSS_SELECTOR, YEAR_HEADER_CSS).text.strip())


def set_year(driver, year: int, timeout=20):
    wait = WebDriverWait(driver, timeout)

    ybtn = wait.until(EC.element_to_be_clickable((By.XPATH, NAV_YEAR_BTN_XPATH)))
    driver.execute_script("arguments[0].click();", ybtn)

    root = wait_qdate(driver, timeout)
    wait.until(lambda d: root.find_element(By.CSS_SELECTOR, YEAR_VIEW_CSS))
    time.sleep(0.1)

    year_xpath = (
        "//div[contains(@class,'q-date__years-content')]"
        f"//button[.//span[normalize-space(text())='{year}']]"
    )

    prev_arrow = ".//div[contains(@class,'q-date__years-content')]//button[.//i[normalize-space(.)='chevron_left']]"
    next_arrow = ".//div[contains(@class,'q-date__years-content')]//button[.//i[normalize-space(.)='chevron_right']]"

    for _ in range(35):
        root = wait_qdate(driver, timeout)
        found = root.find_elements(By.XPATH, year_xpath)
        if found:
            driver.execute_script("arguments[0].click();", found[0])
            time.sleep(0.12)
            return

        years = []
        for sp in root.find_elements(By.XPATH, ".//div[contains(@class,'q-date__years-content')]//span"):
            t = (sp.text or "").strip()
            if t.isdigit() and len(t) == 4:
                years.append(int(t))

        if years and year < min(years):
            driver.execute_script("arguments[0].click();", root.find_element(By.XPATH, prev_arrow))
        else:
            driver.execute_script("arguments[0].click();", root.find_element(By.XPATH, next_arrow))

        time.sleep(0.10)

    raise RuntimeError(f"Year {year} not found in grid.")


def set_month(driver, month: int, timeout=20):
    """
    Month grid click (case-insensitive: works for Jan vs JAN).
    """
    abbr = MONTH_ABBR[month]
    wait = WebDriverWait(driver, timeout)

    root = wait_qdate(driver, timeout)

    # Open month grid only if not already open
    if not root.find_elements(By.CSS_SELECTOR, MONTH_VIEW_CSS):
        mbtn = wait.until(EC.element_to_be_clickable((By.XPATH, NAV_MONTH_BTN_XPATH)))
        driver.execute_script("arguments[0].click();", mbtn)
        root = wait_qdate(driver, timeout)

    month_view = WebDriverWait(root, timeout).until(
        lambda r: r.find_element(By.CSS_SELECTOR, MONTH_VIEW_CSS)
    )

    month_btn_xpath = (
        ".//button[.//span["
        "translate(normalize-space(.),"
        "'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ')"
        f"='{abbr}'"
        "]]"
    )

    btn = WebDriverWait(month_view, timeout).until(
        EC.element_to_be_clickable((By.XPATH, month_btn_xpath))
    )
    driver.execute_script("arguments[0].click();", btn)
    time.sleep(0.10)


def click_day(driver, day: int, timeout=20):
    root = wait_qdate(driver, timeout)
    day_view = WebDriverWait(root, timeout).until(
        lambda r: r.find_element(By.CSS_SELECTOR, DAY_VIEW_CSS)
    )

    day_btn_xpath = (
        ".//div[contains(@class,'q-date__calendar-item--in')]"
        f"//button[.//span[normalize-space(text())='{day}']]"
    )

    btn = WebDriverWait(day_view, timeout).until(
        EC.element_to_be_clickable((By.XPATH, day_btn_xpath))
    )
    driver.execute_script("arguments[0].click();", btn)
    time.sleep(0.10)

    # Helps some UIs apply the selected day
    try:
        driver.switch_to.active_element.send_keys(Keys.ENTER)
    except Exception:
        pass


def wait_date_applied(driver, target_ymd: str, timeout=30):
    """
    Wait until the page date input shows the target date (YYYY/MM/DD or YYYY-MM-DD).
    """
    wait = WebDriverWait(driver, timeout)

    # input value on site is usually YYYY/MM/DD
    target_slash = target_ymd.replace("-", "/")

    def _ok(d):
        el = find_date_input(d)
        if not el:
            return False
        v = (el.get_attribute("value") or "").strip()
        return (v == target_slash) or (v == target_ymd)

    wait.until(_ok)


def pick_date(driver, date_str: str, timeout=30):
    """
    date_str: 'YYYY-MM-DD'
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")

    open_calendar(driver, timeout=timeout)

    if get_current_year(driver, timeout=timeout) != dt.year:
        set_year(driver, dt.year, timeout=timeout)

    set_month(driver, dt.month, timeout=timeout)
    click_day(driver, dt.day, timeout=timeout)

    # Wait for UI to apply the selected date
    wait_date_applied(driver, date_str, timeout=timeout)

    # After date change, table may reload (ensure present)
    WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, "table")))


# ----------------------------
# YOUR EXISTING SCRAPE CODE (UNCHANGED)
# ----------------------------
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
    try:
        return driver.find_element(By.CSS_SELECTOR, "table tbody tr td").text.strip()
    except Exception:
        return None


def go_to_next_page(driver, wait, current_page):
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


def daterange_inclusive(start_date: str, end_date: str):
    """
    start_date/end_date format: YYYY-MM-DD
    """
    s = datetime.strptime(start_date, "%Y-%m-%d").date()
    e = datetime.strptime(end_date, "%Y-%m-%d").date()
    d = s
    while d <= e:
        yield d.strftime("%Y-%m-%d")
        d = d.fromordinal(d.toordinal() + 1)


def main():
    # ✅ Repo root (IMPORTANT)
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    # Nepal time
    npt = timezone(timedelta(hours=5, minutes=45))

    # ----------------------------
    # DATE RANGE INPUT (ADDED)
    # - For GitHub Actions: set env START_DATE and END_DATE
    # - Fallback: today only
    # ----------------------------
    start_date = os.getenv("START_DATE")
    end_date = os.getenv("END_DATE")

    if not start_date or not end_date:
        # fallback: run only today (Nepal date)
        today_npt = datetime.now(npt).strftime("%Y-%m-%d")
        start_date = today_npt
        end_date = today_npt

    # ✅ EXACT location: outputs/Floor Sheet
    out_dir = os.path.join(BASE_DIR, "outputs", "Floor Sheet")
    os.makedirs(out_dir, exist_ok=True)

    IS_GITHUB = os.getenv("GITHUB_ACTIONS") == "true"

    chrome_options = webdriver.ChromeOptions()
    if IS_GITHUB:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
    else:
        chrome_options.add_argument("--start-maximized")

    driver = webdriver.Chrome(options=chrome_options)
    wait = WebDriverWait(driver, 30)

    try:
        driver.get(URL)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table")))

        # ----------------------------
        # LOOP EACH DATE (ADDED)
        # ----------------------------
        for run_date in daterange_inclusive(start_date, end_date):
            print(f"\n=== Processing date: {run_date} ===")

            # pick date in UI (new)
            pick_date(driver, run_date, timeout=30)

            out_csv = os.path.join(out_dir, f"floorsheet_{run_date}.csv")

            all_data = []
            current_page = 1

            while True:
                all_data.extend(scrape_current_page(driver))
                print(f"Scraped page: {current_page} (date {run_date})")

                if not go_to_next_page(driver, wait, current_page):
                    break

                current_page += 1

            df = pd.DataFrame(all_data)
            header = ["Transact No.", "Symbol", "Buyer", "Seller", "Quantity", "Rate", "Amount"]

            if df.empty:
                # still save empty file (useful for closed days)
                df = pd.DataFrame(columns=header)

            if df.shape[1] == len(header):
                df.columns = header
                df["Quantity"] = df["Quantity"].apply(parse_numeric)
                df["Rate"] = df["Rate"].apply(parse_numeric)
                df["Amount"] = df["Amount"].apply(parse_numeric)
            else:
                # Keep your original strictness, but show what happened
                raise ValueError(f"Column mismatch on {run_date}. Got {df.shape[1]} columns.")

            df.to_csv(out_csv, index=False, encoding="utf-8-sig")
            print(f"Saved successfully: {out_csv}")

            # Important: after finishing last page, next date will repick and refresh the table.
            # No extra navigation needed.

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
