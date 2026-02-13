import os
import re
import argparse
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag


# ============================================================
# CONFIG
# ============================================================

# URL fija (AEMET)
URL_FIJA = "https://aemetblog.es/2026/02/12/engelamiento-la-invencion-de-una-palabra-aeronautica/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

DEFAULT_TIMEOUT = 20


# ============================================================
# HELPERS
# ============================================================
def slugify(texto: str, max_len: int = 80) -> str:
    texto = (texto or "").strip().lower()
    texto = re.sub(r"\s+", " ", texto)
    texto = re.sub(r"[^a-z0-9áéíóúüñ\s-]", "", texto, flags=re.IGNORECASE)
    texto = texto.replace(" ", "-")
    texto = re.sub(r"-{2,}", "-", texto).strip("-")
    return (texto[:max_len].strip("-")) or "articulo"


def limpiar_texto(t: str) -> str:
    t = (t or "").replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


def fetch_html(url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    print("Status:", r.status_code)
    r.raise_for_status()
    if not r.encoding:
        r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def limpiar_basura(soup: BeautifulSoup) -> None:
    for tag_name in ["script", "style", "noscript", "svg", "canvas", "iframe"]:
        for t in soup.find_all(tag_name):
            t.decompose()

    for tag_name in ["header", "footer", "nav", "aside", "form"]:
        for t in soup.find_all(tag_name):
            t.decompose()


def detectar_titulo(soup: BeautifulSoup) -> str:
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return limpiar_texto(og["content"])

    h1 = soup.find("h1")
    if h1:
        t = limpiar_texto(h1.get_text(" ", strip=True))
        if t:
            return t

    if soup.title and soup.title.string:
        return limpiar_texto(soup.title.string)

    return "Artículo"


def detectar_fecha(soup: BeautifulSoup) -> str:
    meta = soup.find("meta", attrs={"property": "article:published_time"})
    if meta and meta.get("content"):
        return limpiar_texto(meta["content"])

    for name in ["date", "pubdate", "publish-date", "publication_date", "published_time"]:
        meta = soup.find("meta", attrs={"name": name})
        if meta and meta.get("content"):
            return limpiar_texto(meta["content"])

    time_tag = soup.find("time")
    if time_tag:
        if time_tag.get("datetime"):
            return limpiar_texto(time_tag["datetime"])
        txt = limpiar_texto(time_tag.get_text(" ", strip=True))
        if txt:
            return txt

    return ""


def elegir_contenedor_principal(soup: BeautifulSoup) -> Tag:
    article = soup.find("article")
    if article:
        return article

    main = soup.find("main")
    if main:
        return main

    candidatos = soup.find_all(["div", "section"])
    mejor = None
    mejor_score = 0

    for c in candidatos:
        texto = c.get_text(" ", strip=True)
        if not texto:
            continue
        num_p = len(c.find_all("p"))
        score = len(texto) + (num_p * 200)
        if score > mejor_score:
            mejor_score = score
            mejor = c

    return mejor if mejor else (soup.body if soup.body else soup)


def extraer_parrafos_y_bloques(contenedor: Tag) -> str:
    md_lines = []

    for el in contenedor.find_all(["h2", "h3", "p", "ul", "ol", "blockquote"], recursive=True):
        name = el.name.lower()

        if name == "h2":
            txt = limpiar_texto(el.get_text(" ", strip=True))
            if txt:
                md_lines.append(f"## {txt}\n")
            continue

        if name == "h3":
            txt = limpiar_texto(el.get_text(" ", strip=True))
            if txt:
                md_lines.append(f"### {txt}\n")
            continue

        if name == "p":
            txt = limpiar_texto(el.get_text(" ", strip=True))
            if len(txt) >= 60:
                md_lines.append(txt + "\n")
            continue

        if name in ("ul", "ol"):
            items = []
            for li in el.find_all("li", recursive=False):
                t = limpiar_texto(li.get_text(" ", strip=True))
                if t:
                    items.append(t)
            if items:
                for i, it in enumerate(items, start=1):
                    pref = "-" if name == "ul" else f"{i}."
                    md_lines.append(f"{pref} {it}")
                md_lines.append("")
            continue

        if name == "blockquote":
            txt = limpiar_texto(el.get_text(" ", strip=True))
            if txt:
                for line in txt.splitlines():
                    line = limpiar_texto(line)
                    if line:
                        md_lines.append(f"> {line}")
                md_lines.append("")
            continue

    return "\n".join(md_lines).strip()


def extraer_imagenes(contenedor: Tag, base_url: str):
    imgs = []
    vistos = set()

    for img in contenedor.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
        if not src:
            continue

        abs_url = urljoin(base_url, src.strip())

        if abs_url.startswith("data:"):
            continue
        if abs_url in vistos:
            continue

        vistos.add(abs_url)
        alt = limpiar_texto(img.get("alt") or "")
        imgs.append({"url": abs_url, "alt": alt})

    return imgs


def descargar_imagen(session: requests.Session, img_url: str, dest_path: str) -> bool:
    try:
        r = session.get(img_url, timeout=20)
        r.raise_for_status()

        content_type = r.headers.get("content-type", "")
        if content_type and not content_type.startswith("image/"):
            return False

        with open(dest_path, "wb") as f:
            f.write(r.content)

        return os.path.getsize(dest_path) > 1024
    except Exception:
        return False


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Extrae título + texto + imágenes de AEMET y genera Markdown.")
    parser.add_argument("--out", default="salidas_md", help="Carpeta de salida para el .md")
    parser.add_argument("--assets", default="assets", help="Carpeta donde guardar imágenes (si activas --download-images)")
    parser.add_argument("--download-images", action="store_true", help="Descarga las imágenes y enlaza local en el MD")
    args = parser.parse_args()

    url = URL_FIJA

    os.makedirs(args.out, exist_ok=True)
    if args.download_images:
        os.makedirs(args.assets, exist_ok=True)

    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")
    limpiar_basura(soup)

    title = detectar_titulo(soup)
    fecha = detectar_fecha(soup)

    contenedor = elegir_contenedor_principal(soup)

    cuerpo_md = extraer_parrafos_y_bloques(contenedor)
    imagenes = extraer_imagenes(contenedor, url)

    dominio = urlparse(url).netloc.replace("www.", "") or "pagina"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = slugify(title)

    md_filename = f"{dominio}__{slug}__{timestamp}.md"
    md_path = os.path.join(args.out, md_filename)

    local_img_lines = []
    if args.download_images and imagenes:
        folder = os.path.join(args.assets, f"{dominio}__{slug}__{timestamp}")
        os.makedirs(folder, exist_ok=True)

        with requests.Session() as s:
            s.headers.update(HEADERS)

            for idx, img in enumerate(imagenes, start=1):
                parsed = urlparse(img["url"])
                ext = os.path.splitext(parsed.path)[1].lower()
                if ext not in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
                    ext = ".jpg"

                local_name = f"img_{idx:03d}{ext}"
                local_path = os.path.join(folder, local_name)

                ok = descargar_imagen(s, img["url"], local_path)
                alt = img["alt"] or f"imagen {idx}"

                if ok:
                    rel_path = os.path.relpath(local_path, start=args.out).replace("\\", "/")
                    local_img_lines.append(f"![{alt}]({rel_path})")
                else:
                    local_img_lines.append(f"![{alt}]({img['url']})")

    md = []
    md.append(f"# {title}")
    md.append("")
    md.append(f"- Fuente: {url}")
    if fecha:
        md.append(f"- Fecha detectada: {fecha}")
    md.append(f"- Extraído: {datetime.now().isoformat(timespec='seconds')}")
    if imagenes:
        md.append(f"- Imágenes detectadas: {len(imagenes)}")
    md.append("")
    md.append("---")
    md.append("")
    md.append(cuerpo_md if cuerpo_md else "_No se pudo extraer cuerpo con la heurística actual._")

    if imagenes:
        md.append("")
        md.append("---")
        md.append("")
        md.append("## Imágenes")
        md.append("")
        if args.download_images and local_img_lines:
            md.extend(local_img_lines)
        else:
            for idx, img in enumerate(imagenes, start=1):
                alt = img["alt"] or f"imagen {idx}"
                md.append(f"- [{alt}]({img['url']})")

    contenido_md = "\n".join(md).strip() + "\n"

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(contenido_md)

    print(f"✅ Markdown guardado en: {md_path}")
    if imagenes:
        print(f"🖼️ Imágenes detectadas: {len(imagenes)}")
        print("📦 Descarga imágenes:", "ACTIVADA" if args.download_images else "desactivada (solo links)")


if __name__ == "__main__":
    main()
