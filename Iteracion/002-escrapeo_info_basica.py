import requests
from datetime import datetime
from urllib.parse import urlparse

# URL simple y estable para pruebas (HTML básico)
url = "https://www.iana.org/domains/reserved"

# Headers básicos para que algunas webs no te bloqueen tan fácil
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

try:
    response = requests.get(url, headers=headers, timeout=20)

    # si quieres ver el código de estado
    print("Status:", response.status_code)
    response.raise_for_status()  # si hay error HTTP (403, 404, 500...), lanza excepción

    # y aquí tienes el HTML completito
    html = response.text

    # nombre de archivo simple: dominio + timestamp
    dominio = urlparse(url).netloc.replace("www.", "") or "pagina"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{dominio}_{timestamp}.html"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML guardado en: {filename}")

    # Preview (para no spamear toda la consola)
    print("\n--- PREVIEW (primeros 600 chars) ---")
    print(html[:600])

except requests.exceptions.RequestException as e:
    print("Error al descargar la página:", e)
