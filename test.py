from playwright.sync_api import sync_playwright

URLS = [
    "https://www.molcup.cz",
    "https://www.molcup.cz/zapasy-vysledky",
    "https://www.molcup.cz/vysledky",
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    for url in URLS:
        print(f"\nZkouším URL: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(2000)

        # Hledáme přímo na stránce
        count_main = page.locator("div.item").count()
        print(f"  -> Nalezeno div.item na hlavní stránce: {count_main}")

        # Hledáme uvnitř případných iframů
        for i, frame in enumerate(page.frames):
            if frame != page.main_frame:
                count_frame = frame.locator("div.item").count()
                if count_frame > 0:
                    print(f"  -> Nalezeno div.item v iframe #{i} ({frame.url}): {count_frame}")

    browser.close()
