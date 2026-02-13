import requests
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urlparse
import re

# Paso 3: un post real (clima/meteorología) para empezar a “extraer”
url = "https://aemetblog.es/2026/02/12/engelamiento-la-invencion-de-una-palabra-aeronautica/"

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

def limpiar_texto(t: str) -> str:
    t = t.replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()

try:
    response = requests.get(url, headers=headers, timeout=20)
    print("Status:", response.status_code)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # 1) Título (si no existe, fallback)
    title = soup.title.get_text(strip=True) if soup.title else "Artículo"
    title = limpiar_texto(title)

    # 2) Párrafos: tomamos los <p> con texto “suficiente”
    #    (esto es simple; más adelante haremos heurística por <article>)
    parrafos = []
    for p in soup.find_all("p"):
        txt = limpiar_texto(p.get_text(" ", strip=True))
        if len(txt) >= 60:  # filtro anti “párrafos basura”
            parrafos.append(txt)

    # Limitar a X párrafos para empezar (puedes subirlo luego)
    parrafos = parrafos[:12]

    # 3) Crear markdown
    dominio = urlparse(url).netloc.replace("www.", "") or "pagina"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_filename = f"{dominio}_{timestamp}.md"

    md = []
    md.append(f"# {title}")
    md.append("")
    md.append(f"- Fuente: {url}")
    md.append(f"- Extraído: {datetime.now().isoformat(timespec='seconds')}")
    md.append("")
    md.append("---")
    md.append("")

    if parrafos:
        md.extend(parrafos)
    else:
        md.append("_No se encontraron párrafos suficientemente largos. (Luego mejoramos la extracción)._")

    contenido_md = "\n\n".join(md).strip() + "\n"

    with open(md_filename, "w", encoding="utf-8") as f:
        f.write(contenido_md)

    print(f"✅ Markdown guardado en: {md_filename}")
    print("\n--- PREVIEW MD (primeros 500 chars) ---")
    print(contenido_md[:500])

except requests.exceptions.RequestException as e:
    print("❌ Error al descargar la página:", e)
