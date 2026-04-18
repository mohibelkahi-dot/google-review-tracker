import csv
import os
import re
from datetime import datetime
from playwright.sync_api import sync_playwright

SHORT_URL = "https://maps.app.goo.gl/ytnEwmrLqhEGg4BYA"
OUTPUT_FILE = "weekly_stats.csv"

# On Replit (NixOS) the system Chromium is at a fixed path.
# On GitHub Actions (Ubuntu) Playwright installs its own Chromium — leave as None.
_NIX_CHROMIUM = (
    "/nix/store/qa9cnw4v5xkxyip6mb9kxqfq1z4x2dx1-chromium-138.0.7204.100/bin/chromium"
)
CHROMIUM_PATH = _NIX_CHROMIUM if os.path.isfile(_NIX_CHROMIUM) else None


def build_full_url(page, short_url):
    """Follow the short URL redirect to get the canonical Google Maps URL."""
    page.goto(short_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)
    final_url = page.url

    # Make sure reviews tab is shown by appending the review-sort parameter
    # Google Maps shows the rating histogram when !9m1!1b1 is in the data param
    if "/data=" in final_url and "!9m1!1b1" not in final_url:
        final_url = re.sub(
            r"(/data=)([^?]*)",
            lambda m: m.group(1) + m.group(2).rstrip("/") + "!9m1!1b1",
            final_url,
        )
    elif "/data=" not in final_url:
        final_url = final_url.rstrip("/") + "/data=!9m1!1b1"

    return final_url


def scrape_review_summary():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROMIUM_PATH,
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        print(f"Resolving short URL: {SHORT_URL} ...")
        full_url = build_full_url(page, SHORT_URL)
        print(f"Navigating to full URL: {full_url[:100]}...")

        page.goto(full_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
        print("Page title:", page.title())

        counts = {}

        # Primary strategy: extract from aria-labels like "5 stars, 1,002 reviews"
        elements = page.locator("[aria-label]").all()
        for el in elements:
            lbl = el.get_attribute("aria-label") or ""
            # Matches: "5 stars, 1,002 reviews" or "1 star, 27 reviews"
            m = re.match(r"(\d)\s+stars?,\s*([\d,]+)\s+review", lbl, re.IGNORECASE)
            if m:
                star_num = int(m.group(1))
                count_val = int(m.group(2).replace(",", ""))
                counts[star_num] = count_val
                print(f"  Extracted: {star_num} stars = {count_val}")

        # Fallback: try table rows with "X stars" structure
        if not counts or all(v == 0 for v in counts.values()):
            print("Primary extraction failed, trying table row fallback...")
            try:
                rows = page.locator("table tr").all()
                for row in rows:
                    row_aria = row.get_attribute("aria-label") or ""
                    m = re.match(
                        r"(\d)\s+stars?,\s*([\d,]+)\s+review", row_aria, re.IGNORECASE
                    )
                    if m:
                        counts[int(m.group(1))] = int(m.group(2).replace(",", ""))
            except Exception as e:
                print(f"  Table row fallback error: {e}")

        browser.close()

    # Ensure all star levels are present
    for s in [1, 2, 3, 4, 5]:
        counts.setdefault(s, 0)

    return counts


def calculate_average(counts):
    total = sum(counts.values())
    if total == 0:
        return 0.0
    weighted_sum = sum(star * count for star, count in counts.items())
    return round(weighted_sum / total, 2)


def print_summary(counts, average, timestamp):
    total = sum(counts.values())
    print("\n" + "=" * 49)
    print("  Google Maps Review Summary")
    print(f"  Scraped at: {timestamp}")
    print("=" * 49)
    print(f"  {'Stars':<16} {'Count':>10}  {'Share':>9}")
    print("-" * 49)
    for star in [5, 4, 3, 2, 1]:
        count = counts.get(star, 0)
        pct = (count / total * 100) if total else 0
        bar = "★" * star + "☆" * (5 - star)
        print(f"  {bar}   {count:>10,}  {pct:>8.1f}%")
    print("-" * 49)
    print(f"  {'Total reviews':<22} {total:>10,}")
    print(f"  {'Average rating':<22} {average:>10.2f} / 5.00")
    print("=" * 49 + "\n")


def save_to_csv(counts, average, timestamp):
    total = sum(counts.values())
    file_exists = os.path.isfile(OUTPUT_FILE)

    with open(OUTPUT_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(
                [
                    "timestamp",
                    "5_stars",
                    "4_stars",
                    "3_stars",
                    "2_stars",
                    "1_stars",
                    "total_reviews",
                    "average_rating",
                ]
            )
        writer.writerow(
            [
                timestamp,
                counts.get(5, 0),
                counts.get(4, 0),
                counts.get(3, 0),
                counts.get(2, 0),
                counts.get(1, 0),
                total,
                average,
            ]
        )

    print(f"Results appended to '{OUTPUT_FILE}'")


def main():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    counts = scrape_review_summary()

    star_counts = [counts.get(s, 0) for s in [5, 4, 3, 2, 1]]
    print(f"\nExtracted star counts [5, 4, 3, 2, 1]: {star_counts}")

    average = calculate_average(counts)
    print_summary(counts, average, timestamp)
    save_to_csv(counts, average, timestamp)


if __name__ == "__main__":
    main()
