import re
import os
import json
import requests
from datetime import datetime

# ============================================================
# 030-clima_open_meteo_basico.py
# ------------------------------------------------------------
# Qué hace:
#   1) Convierte una ciudad a coordenadas (geocoding)
#   2) Pide predicción a Open-Meteo (current + daily)
#   3) Guarda un JSON "crudo" + un resumen en Markdown
#
# Requisitos:
#   pip install requests
# ============================================================

# ✅ Cambia esto cuando quieras
CIUDAD = "Madrid"
TIMEZONE = "Europe/Madrid"

OUT_DIR = "salidas_clima"
os.makedirs(OUT_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

# Mapa básico de weather_code (WMO) usado por Open-Meteo (los más comunes)
# Fuente: tabla de códigos en la doc de Open-Meteo. :contentReference[oaicite:6]{index=6}
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
    56: "Llovizna helada ligera",
    57: "Llovizna helada intensa",
    61: "Lluvia ligera",
    63: "Lluvia moderada",
    65: "Lluvia intensa",
    66: "Lluvia helada ligera",
    67: "Lluvia helada intensa",
    71: "Nieve ligera",
    73: "Nieve moderada",
    75: "Nieve intensa",
    77: "Granos de nieve",
    80: "Chubascos ligeros",
    81: "Chubascos moderados",
    82: "Chubascos fuertes",
    85: "Chubascos de nieve ligeros",
    86: "Chubascos de nieve fuertes",
    95: "Tormenta",
    96: "Tormenta con granizo (ligero)",
    99: "Tormenta con granizo (fuerte)",
}


def get_json(url: str, params: dict) -> dict:
    """GET + parse JSON con control de errores básico."""
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    print("GET", r.url)
    print("Status:", r.status_code)
    r.raise_for_status()
    return r.json()


def geocoding(ciudad: str) -> dict:
    """
    Busca ciudad -> devuelve el primer resultado (el más relevante).
    Doc: Open-Meteo Geocoding API. :contentReference[oaicite:7]{index=7}
    """
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {
        "name": ciudad,
        "count": 1,
        "language": "es",
        "format": "json",
    }
    data = get_json(url, params)

    results = data.get("results") or []
    if not results:
        raise RuntimeError(f"No se encontraron resultados para: {ciudad}")

    return results[0]


def forecast(lat: float, lon: float, timezone: str) -> dict:
    """
    Pide predicción a /v1/forecast (current + daily).
    Doc: Weather Forecast API. :contentReference[oaicite:8]{index=8}
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": timezone,
        "forecast_days": 7,

        # Datos "actuales"
        "current": ",".join([
            "temperature_2m",
            "relative_humidity_2m",
            "apparent_temperature",
            "precipitation",
            "weather_code",
            "wind_speed_10m",
            "wind_direction_10m",
        ]),

        # Resumen diario 7 días
        "daily": ",".join([
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "precipitation_probability_max",
            "weather_code",
        ]),
    }
    return get_json(url, params)


def wmo_desc(code) -> str:
    try:
        code_int = int(code)
    except Exception:
        return "—"
    return WMO.get(code_int, f"Código {code_int}")


def build_markdown(loc: dict, data: dict) -> str:
    """Construye un MD simple: actual + tabla 7 días."""
    now = datetime.now().isoformat(timespec="seconds")

    name = loc.get("name", CIUDAD)
    country = loc.get("country", "")
    admin1 = loc.get("admin1", "")

    lat = loc.get("latitude")
    lon = loc.get("longitude")

    cur = data.get("current", {}) or {}
    cur_units = data.get("current_units", {}) or {}

    # Daily arrays
    daily = data.get("daily", {}) or {}
    daily_units = data.get("daily_units", {}) or {}

    days = daily.get("time", []) or []

    lines = []
    lines.append(f"# Clima — {name}{(' · ' + admin1) if admin1 else ''}{(' · ' + country) if country else ''}")
    lines.append("")
    lines.append(f"- Fuente: Open-Meteo")
    lines.append(f"- Coordenadas: {lat}, {lon}")
    lines.append(f"- Zona horaria: {TIMEZONE}")
    lines.append(f"- Generado: {now}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Ahora")
    lines.append("")
    # Mostramos con unidades si existen
    lines.append(f"- Temperatura: {cur.get('temperature_2m', '—')} {cur_units.get('temperature_2m', '')}".strip())
    lines.append(f"- Sensación térmica: {cur.get('apparent_temperature', '—')} {cur_units.get('apparent_temperature', '')}".strip())
    lines.append(f"- Humedad: {cur.get('relative_humidity_2m', '—')} {cur_units.get('relative_humidity_2m', '')}".strip())
    lines.append(f"- Precipitación: {cur.get('precipitation', '—')} {cur_units.get('precipitation', '')}".strip())
    wc = cur.get("weather_code", None)
    lines.append(f"- Estado (weather_code): {wc} · {wmo_desc(wc)}")
    lines.append(f"- Viento: {cur.get('wind_speed_10m', '—')} {cur_units.get('wind_speed_10m', '')} · Dir: {cur.get('wind_direction_10m', '—')}°".strip())
    lines.append("")
    lines.append("## Próximos 7 días")
    lines.append("")
    lines.append("| Fecha | Tmin | Tmax | Prob. precip (max) | Precip total | Código | Descripción |")
    lines.append("|---|---:|---:|---:|---:|---:|---|")

    tmin = daily.get("temperature_2m_min", []) or []
    tmax = daily.get("temperature_2m_max", []) or []
    pprob = daily.get("precipitation_probability_max", []) or []
    psum = daily.get("precipitation_sum", []) or []
    dcode = daily.get("weather_code", []) or []

    u_t = daily_units.get("temperature_2m_min", "°C")
    u_p = daily_units.get("precipitation_sum", "mm")
    u_pp = daily_units.get("precipitation_probability_max", "%")

    for i, day in enumerate(days):
        vmin = tmin[i] if i < len(tmin) else "—"
        vmax = tmax[i] if i < len(tmax) else "—"
        vpp = pprob[i] if i < len(pprob) else "—"
        vps = psum[i] if i < len(psum) else "—"
        vc = dcode[i] if i < len(dcode) else "—"
        desc = wmo_desc(vc)

        lines.append(f"| {day} | {vmin}{u_t} | {vmax}{u_t} | {vpp}{u_pp} | {vps}{u_p} | {vc} | {desc} |")

    lines.append("")
    return "\n".join(lines).strip() + "\n"


def main():
    try:
        print(f"📍 Geocoding: {CIUDAD}")
        loc = geocoding(CIUDAD)

        print("🌦️ Pidiendo predicción...")
        data = forecast(loc["latitude"], loc["longitude"], TIMEZONE)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_city = re.sub(r"[^a-zA-Z0-9_-]+", "_", CIUDAD).strip("_").lower()

        json_path = os.path.join(OUT_DIR, f"{safe_city}_{ts}.json")
        md_path = os.path.join(OUT_DIR, f"{safe_city}_{ts}.md")

        # Guardar JSON crudo (sirve para stats/graficas luego)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # Guardar Markdown resumen
        md = build_markdown(loc, data)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md)

        print(f"✅ JSON guardado en: {json_path}")
        print(f"✅ MD guardado en: {md_path}")

    except requests.RequestException as e:
        print("❌ Error de red/HTTP:", e)
    except Exception as e:
        print("❌ Error:", e)


if __name__ == "__main__":
    main()
