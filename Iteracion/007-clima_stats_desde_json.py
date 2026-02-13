import os
import json
import glob
import argparse
from datetime import datetime


# ============================================================
# 007-clima_stats_desde_json.py
# ------------------------------------------------------------
# Qué hace:
#   - Busca el JSON más reciente en ./salidas_clima (o usa uno indicado)
#   - Calcula estadísticas de la predicción diaria (7 días)
#   - Genera un Markdown con:
#       * max/min semanal y qué día fue
#       * promedios
#       * precipitación total semanal
#       * día con mayor probabilidad de precipitación
#       * tabla resumen por día
#
# Requisitos:
#   (solo estándar) -> no necesitas instalar nada extra
#
# Uso:
#   py 007-clima_stats_desde_json.py
#   py 007-clima_stats_desde_json.py --input salidas_clima/madrid_20260213_120000.json
# ============================================================

OUT_DIR = "salidas_clima"


# ----------------------------
# Helpers
# ----------------------------
def cargar_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def encontrar_ultimo_json(out_dir: str) -> str | None:
    patron = os.path.join(out_dir, "*.json")
    archivos = glob.glob(patron)
    if not archivos:
        return None
    # el más reciente por fecha de modificación
    archivos.sort(key=os.path.getmtime, reverse=True)
    return archivos[0]


def safe_num(x, default=None):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def argmax(values):
    """Devuelve (idx, val) del mayor; ignora None."""
    best_i = None
    best_v = None
    for i, v in enumerate(values):
        if v is None:
            continue
        if best_v is None or v > best_v:
            best_v = v
            best_i = i
    return best_i, best_v


def argmin(values):
    """Devuelve (idx, val) del menor; ignora None."""
    best_i = None
    best_v = None
    for i, v in enumerate(values):
        if v is None:
            continue
        if best_v is None or v < best_v:
            best_v = v
            best_i = i
    return best_i, best_v


def promedio(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def total(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return sum(vals)


def wmo_desc(code) -> str:
    """
    Mini-mapa (igual que en tu 006). Puedes ampliarlo luego.
    """
    WMO = {
        0: "Cielo despejado",
        1: "Mayormente despejado",
        2: "Parcialmente nublado",
        3: "Cubierto",
        45: "Niebla",
        48: "Niebla con escarcha",
        51: "Llovizna ligera",
        53: "Llovizna moderada",
        55: "Llovizna intensa",
        61: "Lluvia ligera",
        63: "Lluvia moderada",
        65: "Lluvia intensa",
        71: "Nieve ligera",
        73: "Nieve moderada",
        75: "Nieve intensa",
        80: "Chubascos ligeros",
        81: "Chubascos moderados",
        82: "Chubascos fuertes",
        95: "Tormenta",
        99: "Tormenta con granizo",
    }
    try:
        c = int(code)
        return WMO.get(c, f"Código {c}")
    except Exception:
        return "—"


# ----------------------------
# Generación de Markdown
# ----------------------------
def build_stats_markdown(json_path: str, data: dict) -> str:
    now = datetime.now().isoformat(timespec="seconds")

    timezone = data.get("timezone", "—")

    daily = data.get("daily", {}) or {}
    daily_units = data.get("daily_units", {}) or {}

    days = daily.get("time", []) or []

    # Arrays (pueden venir como ints/floats/None)
    tmax = [safe_num(x) for x in (daily.get("temperature_2m_max", []) or [])]
    tmin = [safe_num(x) for x in (daily.get("temperature_2m_min", []) or [])]
    psum = [safe_num(x) for x in (daily.get("precipitation_sum", []) or [])]
    pprob = [safe_num(x) for x in (daily.get("precipitation_probability_max", []) or [])]
    wcode = daily.get("weather_code", []) or []

    # Unidades
    u_tmax = daily_units.get("temperature_2m_max", "°C")
    u_tmin = daily_units.get("temperature_2m_min", "°C")
    u_psum = daily_units.get("precipitation_sum", "mm")
    u_pp = daily_units.get("precipitation_probability_max", "%")

    # Estadísticas
    i_max, v_max = argmax(tmax)
    i_min, v_min = argmin(tmin)

    avg_max = promedio(tmax)
    avg_min = promedio(tmin)

    total_rain = total(psum)

    i_pp, v_pp = argmax(pprob)

    # Para título, usamos el nombre del archivo si viene estilo madrid_YYYY...
    base_name = os.path.basename(json_path)
    ciudad_guess = base_name.split("_")[0] if "_" in base_name else "ciudad"

    lines = []
    lines.append(f"# Reporte de estadísticas del clima — {ciudad_guess}")
    lines.append("")
    lines.append(f"- Archivo fuente (JSON): `{base_name}`")
    lines.append(f"- Zona horaria (JSON): {timezone}")
    lines.append(f"- Generado: {now}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Resumen semanal")
    lines.append("")

    if i_max is not None:
        lines.append(f"- **Tª máxima semanal:** {v_max:.1f}{u_tmax} (día {days[i_max]})")
    else:
        lines.append("- **Tª máxima semanal:** —")

    if i_min is not None:
        lines.append(f"- **Tª mínima semanal:** {v_min:.1f}{u_tmin} (día {days[i_min]})")
    else:
        lines.append("- **Tª mínima semanal:** —")

    if avg_max is not None:
        lines.append(f"- **Promedio Tmax:** {avg_max:.1f}{u_tmax}")
    else:
        lines.append("- **Promedio Tmax:** —")

    if avg_min is not None:
        lines.append(f"- **Promedio Tmin:** {avg_min:.1f}{u_tmin}")
    else:
        lines.append("- **Promedio Tmin:** —")

    if total_rain is not None:
        lines.append(f"- **Precipitación total (7 días):** {total_rain:.1f}{u_psum}")
    else:
        lines.append("- **Precipitación total (7 días):** —")

    if i_pp is not None:
        lines.append(f"- **Día con mayor prob. precipitación:** {days[i_pp]} ({v_pp:.0f}{u_pp})")
    else:
        lines.append("- **Día con mayor prob. precipitación:** —")

    lines.append("")
    lines.append("## Tabla diaria (7 días)")
    lines.append("")
    lines.append("| Fecha | Tmin | Tmax | Prob. precip | Precip total | Código | Descripción |")
    lines.append("|---|---:|---:|---:|---:|---:|---|")

    # Si por algún motivo no hay 7 días, igual arma lo que haya
    n = len(days)
    for i in range(n):
        d = days[i]
        vmin = tmin[i] if i < len(tmin) else None
        vmax = tmax[i] if i < len(tmax) else None
        vpr = pprob[i] if i < len(pprob) else None
        vps = psum[i] if i < len(psum) else None
        vc = wcode[i] if i < len(wcode) else "—"

        smin = f"{vmin:.1f}{u_tmin}" if vmin is not None else "—"
        smax = f"{vmax:.1f}{u_tmax}" if vmax is not None else "—"
        spr = f"{vpr:.0f}{u_pp}" if vpr is not None else "—"
        sps = f"{vps:.1f}{u_psum}" if vps is not None else "—"

        desc = wmo_desc(vc)

        lines.append(f"| {d} | {smin} | {smax} | {spr} | {sps} | {vc} | {desc} |")

    lines.append("")
    return "\n".join(lines).strip() + "\n"


# ----------------------------
# Main
# ----------------------------
def main():
    parser = argparse.ArgumentParser(description="Genera estadísticas en Markdown desde el JSON de Open-Meteo.")
    parser.add_argument("--input", help="Ruta a un .json específico. Si no, usa el último en salidas_clima.")
    parser.add_argument("--outdir", default=OUT_DIR, help="Carpeta donde buscar JSON y guardar el MD (default: salidas_clima)")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    json_path = args.input
    if not json_path:
        json_path = encontrar_ultimo_json(args.outdir)

    if not json_path or not os.path.exists(json_path):
        print("❌ No encontré ningún JSON. Ejecuta primero tu 006 para generar uno en ./salidas_clima")
        return

    data = cargar_json(json_path)
    md = build_stats_markdown(json_path, data)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.basename(json_path).replace(".json", "")
    md_path = os.path.join(args.outdir, f"{base}__stats__{ts}.md")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"✅ Reporte de stats guardado en: {md_path}")


if __name__ == "__main__":
    main()
