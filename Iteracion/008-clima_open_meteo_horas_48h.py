import os
import re
import json
import requests
from datetime import datetime

# ============================================================
# 008-clima_open_meteo_horas_48h.py
# ------------------------------------------------------------
# Qué hace:
#   1) Geocoding (ciudad -> lat/lon)
#   2) Pide predicción por horas (48 horas) a Open-Meteo
#   3) Guarda JSON crudo + Markdown con tabla por día
#
# Requisitos:
#   pip install requests
#
# Nota:
#   Open-Meteo permite controlar rango horario con forecast_hours.
#   Doc: /v1/forecast + hourly + forecast_hours. :contentReference[oaicite:2]{index=2}
# ============================================================

# ✅ Por ahora fijo (Paso 9 será hacerlo configurable)
CIUDAD = "Madrid"
TIMEZONE = "Europe/Madrid"
FORECAST_HOURS = 48  # 24–48h: aquí lo dejamos en 48

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

# Mini-mapa WMO (puedes ampliarlo luego)
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


def wmo_desc(code) -> str:
    try:
        c = int(code)
        return WMO.get(c, f"Código {c}")
    except Exception:
        return "—"


def safe_num(x):
    try:
        return float(x)
    except Exception:
        return None


def get_json(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    print("GET", r.url)
    print("Status:", r.status_code)
    r.raise_for_status()
    return r.json()


def geocoding(ciudad: str) -> dict:
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


def forecast_hourly_48h(lat: float, lon: float, timezone: str) -> dict:
    # Doc: /v1/forecast + hourly + forecast_hours :contentReference[oaicite:3]{index=3}
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": timezone,
        "forecast_hours": FORECAST_HOURS,

        # Variables por hora (hourly=...) :contentReference[oaicite:4]{index=4}
        "hourly": ",".join([
            "temperature_2m",
            "apparent_temperature",
            "precipitation",
            "precipitation_probability",
            "wind_speed_10m",
            "wind_direction_10m",
            "weather_code",
        ]),
    }
    return get_json(url, params)


def build_markdown(loc: dict, data: dict) -> str:
    now = datetime.now().isoformat(timespec="seconds")

    name = loc.get("name", CIUDAD)
    admin1 = loc.get("admin1", "")
    country = loc.get("country", "")
    lat = loc.get("latitude")
    lon = loc.get("longitude")

    hourly = data.get("hourly", {}) or {}
    units = data.get("hourly_units", {}) or {}

    times = hourly.get("time", []) or []

    # Arrays
    temp = hourly.get("temperature_2m", []) or []
    feel = hourly.get("apparent_temperature", []) or []
    prec = hourly.get("precipitation", []) or []
    pprob = hourly.get("precipitation_probability", []) or []
    wspd = hourly.get("wind_speed_10m", []) or []
    wdir = hourly.get("wind_direction_10m", []) or []
    wcode = hourly.get("weather_code", []) or []

    # Units (fallbacks)
    u_temp = units.get("temperature_2m", "°C")
    u_feel = units.get("apparent_temperature", "°C")
    u_prec = units.get("precipitation", "mm")
    u_pprob = units.get("precipitation_probability", "%")
    u_wspd = units.get("wind_speed_10m", "km/h")

    # Mini resumen 48h
    temp_nums = [safe_num(x) for x in temp]
    pprob_nums = [safe_num(x) for x in pprob]
    prec_nums = [safe_num(x) for x in prec]

    tmin = min([v for v in temp_nums if v is not None], default=None)
    tmax = max([v for v in temp_nums if v is not None], default=None)
    pmax = max([v for v in pprob_nums if v is not None], default=None)
    psum = sum([v for v in prec_nums if v is not None])

    # Agrupar por fecha YYYY-MM-DD
    por_dia = {}
    for i, t in enumerate(times):
        # formato típico: 2026-02-13T14:00
        if "T" in t:
            fecha, hora = t.split("T", 1)
        else:
            fecha, hora = t, ""
        por_dia.setdefault(fecha, []).append((i, hora))

    lines = []
    lines.append(f"# Predicción por horas (48h) — {name}{(' · ' + admin1) if admin1 else ''}{(' · ' + country) if country else ''}")
    lines.append("")
    lines.append("- Fuente: Open-Meteo (hourly)")
    lines.append(f"- Coordenadas: {lat}, {lon}")
    lines.append(f"- Zona horaria: {TIMEZONE}")
    lines.append(f"- Generado: {now}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Resumen (48 horas)")
    lines.append("")
    lines.append(f"- Temperatura mínima: {tmin:.1f}{u_temp}" if tmin is not None else "- Temperatura mínima: —")
    lines.append(f"- Temperatura máxima: {tmax:.1f}{u_temp}" if tmax is not None else "- Temperatura máxima: —")
    lines.append(f"- Prob. precipitación máxima: {pmax:.0f}{u_pprob}" if pmax is not None else "- Prob. precipitación máxima: —")
    lines.append(f"- Precipitación acumulada (sumatoria horaria): {psum:.1f}{u_prec}")
    lines.append("")
    lines.append("## Detalle por horas")
    lines.append("")

    # Tabla por cada día
    for fecha in sorted(por_dia.keys()):
        lines.append(f"### {fecha}")
        lines.append("")
        lines.append("| Hora | Temp | Sensación | Precip | Prob | Viento | Dir | Código | Descripción |")
        lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---|")

        for (i, hora) in por_dia[fecha]:
            v_temp = temp[i] if i < len(temp) else "—"
            v_feel = feel[i] if i < len(feel) else "—"
            v_prec = prec[i] if i < len(prec) else "—"
            v_pp = pprob[i] if i < len(pprob) else "—"
            v_ws = wspd[i] if i < len(wspd) else "—"
            v_wd = wdir[i] if i < len(wdir) else "—"
            v_wc = wcode[i] if i < len(wcode) else "—"

            desc = wmo_desc(v_wc)

            lines.append(
                f"| {hora} | {v_temp}{u_temp} | {v_feel}{u_feel} | {v_prec}{u_prec} | {v_pp}{u_pprob} | {v_ws}{u_wspd} | {v_wd}° | {v_wc} | {desc} |"
            )

        lines.append("")

    return "\n".join(lines).strip() + "\n"


def main():
    try:
        print(f"📍 Geocoding: {CIUDAD}")
        loc = geocoding(CIUDAD)

        print(f"🕒 Pidiendo predicción por horas ({FORECAST_HOURS}h)...")
        data = forecast_hourly_48h(loc["latitude"], loc["longitude"], TIMEZONE)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_city = re.sub(r"[^a-zA-Z0-9_-]+", "_", CIUDAD).strip("_").lower()

        json_path = os.path.join(OUT_DIR, f"{safe_city}_{ts}__hourly_{FORECAST_HOURS}h.json")
        md_path = os.path.join(OUT_DIR, f"{safe_city}_{ts}__hourly_{FORECAST_HOURS}h.md")

        # JSON crudo
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # Markdown
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
