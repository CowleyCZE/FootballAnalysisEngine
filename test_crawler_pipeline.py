import asyncio
from app.crawler.crawler import EngineCrawler

async def main():
    crawler = EngineCrawler()
    
    # Test na reálné stránce
    test_url = "https://www.sparta.cz"
    print(f"=== TEST CRAWLER PIPELINE ===")
    print(f"Stahuji: {test_url}\n")

    result, doc = await crawler.crawl_and_parse(test_url)

    if result.success and doc:
        print(f"[OK] Staženo úspěšně!")
        print(f"Status kód: {result.status_code}")
        print(f"Použit Playwright: {result.used_playwright}")
        print(f"Titulost: {doc.title}")
        print(f"Počet slov: {doc.word_count}")
        print(f"Content Hash: {doc.content_hash}")
        print(f"Uloženo do: data/raw/{doc.content_hash}.html a .json")
    else:
        print(f"[CHYBA] Stažení selhalo: {result.error}")

if __name__ == "__main__":
    asyncio.run(main())
