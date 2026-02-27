from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import time
import json
import pandas as pd
import re
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# -------------------- Constants --------------------
URL = "https://divar.ir/s/tehran/buy-apartment/punak"
LINK_LIMIT = 300
SCROLL_INCREMENT = 800
WAIT_TIME = 3
CSV_FILE = "../data/raw/divar_punak_properties_raw.csv"
CSV_ENCODING = "utf-8-sig"

NEW_KEYWORDS = ["نوساز", "کلیدنخورده", "کلید نخورده", "صفر", "نو ساز" , "تازه ساخت"]
RENOVATED_KEYWORDS = ["بازسازی", "بازسازی شده", "نوسازی شده", "نوساز", ]
BALCONY_KEYWORDS = ["بالکن", "تراس"]
LIGHT_KEYWORDS = ["نورگیر", "پرنور", "نور عالی", "پرده خور", "پرده" , "آکواریوم", "پنجره", "نور گیر"]
LUXURY_KEYWORDS = ["vip", "وی آی پی", "لاکچری", "لوکس", "luxury" ]
DOC_KEYWORDS = ["سند دارد", "دارای سند", "سند تک برگ", "سند"]

# -------------------- Chrome Setup --------------------
chrome_options = Options()
chrome_options.add_argument("--start-maximized")

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=chrome_options
)

# -------------------- Helper Functions --------------------
def convert_persian_numbers(text):
    """Convert Persian digits to English digits and remove non-digit characters."""
    if text is None:
        return None
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"
    english_digits = "0123456789"
    for p, e in zip(persian_digits, english_digits):
        text = text.replace(p, e)
    text = re.sub(r"[^\d]", "", text)
    return text if text != "" else None

def extract_binary_features_from_html(soup, description=""):
    """
    Extract binary features from the HTML content and description.
    Returns a dictionary of features.
    """
    features = {
        "has_elevator": 0,
        "has_parking": 0,
        "has_storage": 0,
        "is_new": 0,
        "is_renovated": 0,
        "has_balcony": 0,
        "good_light": 0,
        "luxury_keywords": 0,
        "has_doc": 0
    }

    # Check HTML table values
    html_features = soup.find_all("td", class_="kt-group-row-item kt-group-row-item__value kt-body kt-body--stable")
    html_texts = [el.get_text(strip=True) for el in html_features]

    if any("آسانسور" in t for t in html_texts):
        features["has_elevator"] = 1
    if any("پارکینگ" in t for t in html_texts):
        features["has_parking"] = 1
    if any("انباری" in t for t in html_texts):
        features["has_storage"] = 1

    # Fallback: check description text
    description = description.lower()
    if features["has_elevator"] == 0 and "آسانسور" in description:
        features["has_elevator"] = 1
    if features["has_parking"] == 0 and "پارکینگ" in description:
        features["has_parking"] = 1
    if features["has_storage"] == 0 and "انباری" in description:
        features["has_storage"] = 1

    # Extract other binary features from description keywords
    features["is_new"] = 1 if any(word in description for word in NEW_KEYWORDS) else 0
    features["is_renovated"] = 1 if any(word in description for word in RENOVATED_KEYWORDS) else 0
    features["has_balcony"] = 1 if any(word in description for word in BALCONY_KEYWORDS) else 0
    features["good_light"] = 1 if any(word in description for word in LIGHT_KEYWORDS) else 0
    features["luxury_keywords"] = 1 if any(word in description for word in LUXURY_KEYWORDS) else 0
    features["has_doc"] = 1 if any(word in description for word in DOC_KEYWORDS) else 0

    return features

def scrape_links(url, limit=LINK_LIMIT):
    """
    Scrape property links from the main page with scrolling.
    Returns a list of links up to the specified limit.
    """
    driver.get(url)
    wait = WebDriverWait(driver, 20)
    wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(@href,'/v/')]")))
    time.sleep(WAIT_TIME)
    first_link = driver.find_element(By.XPATH, "//a[contains(@href,'/v/')]")

    # Find scrollable container
    scroll_container = driver.execute_script("""
        let el = arguments[0];
        while (el.parentElement) {
            el = el.parentElement;
            if (el.scrollHeight > el.clientHeight) {
                return el;
            }
        }
        return document.body;
    """, first_link)

    links = set()
    last_count = 0
    same_rounds = 0

    while len(links) < limit and same_rounds < 5:
        elements = driver.find_elements(By.XPATH, "//a[contains(@href,'/v/')]")
        for el in elements:
            href = el.get_attribute("href")
            if href:
                links.add(href)
        print(f"Collected: {len(links)}")
        driver.execute_script("arguments[0].scrollTop += arguments[1];", scroll_container, SCROLL_INCREMENT)
        time.sleep(WAIT_TIME)
        if len(links) == last_count:
            same_rounds += 1
        else:
            same_rounds = 0
        last_count = len(links)

    return list(links)[:limit]

# -------------------- Scraping --------------------
links = scrape_links(URL)
print(f"Total links found: {len(links)}")

properties = []

for link in links:
    print(f"Scraping: {link}")
    time.sleep(2)
    driver.get(link)
    soup = BeautifulSoup(driver.page_source, "html.parser")

    # Extract main property details
    elements = soup.find_all("td", class_="kt-group-row-item kt-group-row-item__value kt-group-row-item--info-row")
    area = elements[0].get_text(strip=True) if len(elements) >= 1 else None
    year_built = elements[1].get_text(strip=True) if len(elements) >= 2 else None
    rooms = elements[2].get_text(strip=True) if len(elements) >= 3 else None

    # Extract price and floor
    total_price = None
    price_per_m2 = None
    floor = None
    price_rows = soup.find_all("div", class_="kt-base-row")
    for row in price_rows:
        text = row.get_text(strip=True)
        if "قیمت کل" in text:
            total_price = text.replace("قیمت کل", "").strip()
        if "قیمت هر متر" in text:
            price_per_m2 = text.replace("قیمت هر متر", "").strip()
        if "طبقه" in text:
            floor = text.replace("طبقه", "").strip()

    # Extract region and description from JSON-LD
    region = None
    description = ""
    script_tags = soup.find_all("script", type="application/ld+json")
    try:
        json_data = json.loads(script_tags[1].string)
        region = json_data[0]["web_info"]["district_persian"]
        description = json_data[0].get("description", "")
    except:
        pass

    # Convert Persian numbers to English
    area = convert_persian_numbers(area)
    year_built = convert_persian_numbers(year_built)
    rooms = convert_persian_numbers(rooms)
    floor = convert_persian_numbers(floor)
    total_price = convert_persian_numbers(total_price)
    price_per_m2 = convert_persian_numbers(price_per_m2)

    # Extract binary features from description
    binary_features = extract_binary_features_from_html(soup, description)

    property_ = {
        "link": link,
        "area": area,
        "year_built": year_built,
        "rooms": rooms,
        "floor": floor,
        "region": region,
        "total_price": total_price,
        "price_per_m2": price_per_m2,
        **binary_features
    }
    properties.append(property_)

driver.quit()

# Save data to CSV
df = pd.DataFrame(properties)
df.to_csv(CSV_FILE, index=False, encoding=CSV_ENCODING)
print(f"\nTotal properties scraped: {len(properties)}")
print(f"Data saved to {CSV_FILE}")