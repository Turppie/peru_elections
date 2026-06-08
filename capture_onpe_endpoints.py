from playwright.sync_api import sync_playwright
import json
from pathlib import Path
from datetime import datetime

OUT_DIR = Path("onpe_responses")
OUT_DIR.mkdir(exist_ok=True)

URL = "https://resultadosegundavuelta.onpe.gob.pe/main/resumen"

def save_response(response):
    try:
        content_type = response.headers.get("content-type", "")
        url = response.url

        if "application/json" not in content_type.lower():
            return

        data = response.json()

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = (
            url.replace("https://", "")
               .replace("http://", "")
               .replace("/", "_")
               .replace("?", "_")
               .replace("&", "_")
               .replace("=", "_")
        )[:180]

        path = OUT_DIR / f"{ts}_{safe_name}.json"

        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "url": url,
                    "captured_at": ts,
                    "data": data
                },
                f,
                ensure_ascii=False,
                indent=2
            )

        print(f"Saved JSON: {url}")

    except Exception as e:
        pass


with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.on("response", save_response)

    page.goto(URL, wait_until="networkidle")

    print("Navega manualmente por resumen, regiones, actas, distritos.")
    print("Presiona ENTER cuando termines...")
    input()

    browser.close()