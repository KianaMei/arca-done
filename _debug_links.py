import sys, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from DrissionPage import ChromiumPage, ChromiumOptions

co = ChromiumOptions()
co.set_argument("--disable-blink-features=AutomationControlled")
profile_dir = Path("C:/mycode/somethingsmall/arca_scraper/.arca_profile_dp")
co.set_user_data_path(str(profile_dir))
page = ChromiumPage(co)
page.get("https://arca.live/e/43153?target=tag&keyword=%EC%82%AC%EB%8F%84%EC%BD%98&p=1")
time.sleep(5)
print("TITLE:", page.title)
print("URL:", page.url)
links = page.run_js("return Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href'))")
print("TOTAL LINKS:", len(links) if links else 0)
if links:
    for l in links:
        print("LINK:", l)

# Also dump some inner HTML to understand structure
snippet = page.run_js("""
    let el = document.querySelector('.article-list, .board-article-list, .vrow, [class*=\"article\"], [class*=\"list\"]');
    return el ? el.outerHTML.slice(0, 3000) : 'NOT FOUND';
""")
print("\n--- PAGE SNIPPET ---")
print(snippet)
page.quit()
