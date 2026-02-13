import requests
from datetime import datetime
from urllib.parse import urlparse

# Paso 2: un “artículo” simple y grande
url = "https://simple.wikipedia.org/wiki/Weather"

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

try:
    response = requests.get(url, headers=headers, timeout=20)

    print("Status:", response.status_code)
    response.raise_for_status()

    html = response.text

    dominio = urlparse(url).netloc.replace("www.", "") or "pagina"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{dominio}_{timestamp}.html"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ HTML guardado en: {filename}")

    print("\n--- PREVIEW (primeros 600 chars) ---")
    print(html[:600])

except requests.exceptions.RequestException as e:
    print("❌ Error al descargar la página:", e)
