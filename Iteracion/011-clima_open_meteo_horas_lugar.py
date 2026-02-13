import os
import re
import json
import argparse
import requests
from datetime import datetime

# ============================================================
# 011-clima_open_meteo_horas_lugar.py
# ------------------------------------------------------------
# Predicción por horas (por defecto 48h), pero ahora:
#   ✅ puedes cambiar ciudad por argumento --city
#   ✅ puedes filtrar por país con --countryCode (ES, PE, etc.)
#   ✅ timezone por defecto "auto" (se resuelve por coordenadas)
#
# Docs:
# - Geocoding: parámetro countryCode :contentReference[oaicite:3]{index=3}
# - Forecast: forecast_hours y timezone=auto :contentReference[oaicite:4]{index=4}
#
# Requisitos:
#   pip install requests
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

OUT_DIR_DEFAULT = "salidas_clima"

# Variables hourly que necesitamos para tu pipeline de tablas + gráficas
HOURLY_VARS = [
    "temperature_2m",
    "apparent_temperature",
    "precipitation",
    "precipitation_probability",
    "wind_speed_10m",
    "wind_direction_10m",
    "weather_code",
]


def get_json(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    print("GET", r.url)
    print("Status:", r.status_code)
    r.raise_for_status()
    return r.json()


def geocoding(ciudad: str, country_code: str | None, count: int = 5) -> dict:
    """
    Devuelve una lista de resultados (hasta `count`), para que puedas elegir.
    Geocoding API: admite filtro por countryCode. :contentReference[oaicite:5]{index=5}
    """
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {
        "name": ciudad,
        "count": count,
        "language": "es",
        "format": "json",
    }
    if country_code:
        params["countryCode"] = country_code.upper()

    data = get_json(url, params)
    results = data.get("results") or []
    if not results:
        msg = f"No se encontraron resultados para: {ciudad}"
        if country_code:
            msg += f" (countryCode={country_code.upper()})"
        raise RuntimeError(msg)
    return results


def forecast_hourly(lat: float, lon: float, timezone: str, hours: int) -> dict:
    """
    Forecast API: hourly + forecast_hours + timezone (incluye 'auto'). :contentReference[oaicite:6]{index=6}
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": timezone,
        "forecast_hours": hours,
        "hourly": ",".join(HOURLY_VARS),
    }
    return get_json(url, params)


def slugify(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9_-]+", "_", text)
    return text.strip("_") or "ciudad"


def main():
    parser = argparse.ArgumentParser(description="Predicción por horas (Open-Meteo) con ciudad configurable.")
    parser.add_argument("--city", default="Madrid", help="Ciudad (ej: Madrid, Valencia, Lima)")
    parser.add_argument("--countryCode", default=None, help="Filtro país ISO2 (ej: ES, PE). Opcional.")
    parser.add_argument("--hours", type=int, default=48, help="Horas de predicción (ej: 24 o 48).")
    parser.add_argument("--timezone", default="auto", help="Timezone (por defecto: auto).")
    parser.add_argument("--pick", type=int, default=0, help="Qué resultado elegir del geocoding (0 = primero).")
    parser.add_argument("--out", default=OUT_DIR_DEFAULT, help="Carpeta de salida (default: salidas_clima).")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    try:
        print(f"📍 Geocoding: {args.city}")
        results = geocoding(args.city, args.countryCode, count=5)

        # Mostrar candidatos (útil si 'Valencia' te devuelve varias)
        print("\nCandidatos encontrados:")
        for i, r in enumerate(results):
            name = r.get("name", "")
            admin1 = r.get("admin1", "")
            country = r.get("country", "")
            tz = r.get("timezone", "")
            lat = r.get("latitude", "")
            lon = r.get("longitude", "")
            print(f"  [{i}] {name} · {admin1} · {country} | {lat},{lon} | tz={tz}")

        pick = args.pick
        if pick < 0 or pick >= len(results):
            raise RuntimeError(f"--pick fuera de rango. Debe ser 0..{len(results)-1}")

        loc = results[pick]
        lat = loc["latitude"]
        lon = loc["longitude"]

        print(f"\n✅ Usando: [{pick}] {loc.get('name')} · {loc.get('admin1','')} · {loc.get('country','')}")
        print(f"🕒 Pidiendo predicción hourly ({args.hours}h) con timezone={args.timezone} ...")
        data = forecast_hourly(lat, lon, args.timezone, args.hours)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_city = slugify(args.city)
        suffix = f"__hourly_{args.hours}h"

        json_path = os.path.join(args.out, f"{safe_city}_{ts}{suffix}.json")

        # Guardar JSON crudo (lo usan tus scripts de gráficas 009/010)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"\n✅ JSON guardado en: {json_path}")
        print("➡️ Ahora puedes correr tus gráficas con:")
        print("   py .\\009-clima_graficas_48h.py")
        print("   py .\\010-clima_graficas_extra_48h.py")

    except requests.RequestException as e:
        print("❌ Error de red/HTTP:", e)
    except Exception as e:
        print("❌ Error:", e)


if __name__ == "__main__":
    main()
