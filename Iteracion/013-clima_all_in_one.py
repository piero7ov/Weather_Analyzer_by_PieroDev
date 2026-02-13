#!/usr/bin/env python3
# ============================================================
# 013-clima_all_in_one.py
# ------------------------------------------------------------
# TODO-EN-UNO (sin depender de otros scripts):
#   1) Geocoding (ciudad -> lat/lon)
#   2) Forecast hourly (por defecto 48h) desde Open-Meteo
#   3) Guarda JSON
#   4) Genera gráficas:
#       - Paso 8: temperatura (línea) + precipitación (barras)
#       - Paso 9: pprob, viento, temp vs sensación, precip acumulada, dir viento
#
# Requisitos:
#   pip install requests matplotlib
#
# Uso:
#   py 013-clima_all_in_one.py
#   py 013-clima_all_in_one.py --city "Valencia" --countryCode ES
#   py 013-clima_all_in_one.py --city "Lima" --countryCode PE
# ============================================================

import os
import re
import json
import argparse
from datetime import datetime
from typing import Optional, List, Any, Dict

import requests


# ----------------------------
# CONFIG
# ----------------------------
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

HOURLY_VARS = [
    "temperature_2m",
    "apparent_temperature",
    "precipitation",
    "precipitation_probability",
    "wind_speed_10m",
    "wind_direction_10m",
    "weather_code",
]


# ============================================================
# Helpers generales
# ============================================================
def slugify(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9_-]+", "_", text)
    return text.strip("_") or "ciudad"


def safe_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def parse_times(times: List[str]) -> List[Optional[datetime]]:
    """
    Open-Meteo suele devolver: 'YYYY-MM-DDTHH:MM'
    """
    out = []
    for t in times:
        try:
            out.append(datetime.fromisoformat(t))
        except Exception:
            out.append(None)
    return out


def filter_none_times(times_dt: List[Optional[datetime]], series: List[List[Any]]):
    """
    Quita posiciones donde time es None (para que matplotlib no se rompa).
    """
    idx_ok = [i for i, dt in enumerate(times_dt) if dt is not None]
    times_ok = [times_dt[i] for i in idx_ok]
    series_ok = []
    for arr in series:
        series_ok.append([arr[i] if i < len(arr) else None for i in idx_ok])
    return times_ok, series_ok


def get_json(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    print("GET", r.url)
    print("Status:", r.status_code)
    r.raise_for_status()
    return r.json()


# ============================================================
# Open-Meteo: geocoding + forecast
# ============================================================
def geocoding(ciudad: str, country_code: Optional[str], count: int = 5) -> List[Dict[str, Any]]:
    """
    Devuelve lista de candidatos para que puedas elegir con --pick.
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
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": timezone,
        "forecast_hours": hours,
        "hourly": ",".join(HOURLY_VARS),
    }
    return get_json(url, params)


# ============================================================
# Gráficas (Paso 8 + Paso 9) - defaults de matplotlib
# ============================================================
def save_fig(path: str, show: bool):
    import matplotlib.pyplot as plt
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    if show:
        plt.show()
    plt.close()


def plot_line(times, y, title: str, xlabel: str, ylabel: str, out_path: str, show: bool):
    import matplotlib.pyplot as plt
    plt.figure()
    plt.plot(times, y)
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.grid(True)
    plt.xticks(rotation=45, ha="right")
    save_fig(out_path, show)


def plot_bar(times, y, title: str, xlabel: str, ylabel: str, out_path: str, show: bool):
    import matplotlib.pyplot as plt
    plt.figure()
    plt.bar(times, y)
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.grid(True)
    plt.xticks(rotation=45, ha="right")
    save_fig(out_path, show)


def plot_two_lines(times, y1, y2, label1: str, label2: str, title: str, xlabel: str, ylabel: str, out_path: str, show: bool):
    import matplotlib.pyplot as plt
    plt.figure()
    plt.plot(times, y1, label=label1)
    plt.plot(times, y2, label=label2)
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.grid(True)
    plt.legend()
    plt.xticks(rotation=45, ha="right")
    save_fig(out_path, show)


def generate_all_graphs(json_data: dict, city_label: str, out_graf_dir: str, base_name: str, show: bool):
    """
    Genera:
      Paso 8:
        - temp (línea)
        - precip (barras)
      Paso 9:
        - pprob (línea)
        - wind_speed (línea)
        - temp_vs_feel (2 líneas)
        - precip_acum (línea)
        - wind_dir_deg (línea)
    """
    hourly = json_data.get("hourly", {}) or {}
    units = json_data.get("hourly_units", {}) or {}
    tz = json_data.get("timezone", "auto")

    times = hourly.get("time", []) or []
    if not times:
        raise RuntimeError("El JSON no trae hourly.time")

    temp = hourly.get("temperature_2m", []) or []
    feel = hourly.get("apparent_temperature", []) or []
    prec = hourly.get("precipitation", []) or []
    pprob = hourly.get("precipitation_probability", []) or []
    wspd = hourly.get("wind_speed_10m", []) or []
    wdir = hourly.get("wind_direction_10m", []) or []

    # Unidades (fallbacks)
    u_temp = units.get("temperature_2m", "°C")
    u_feel = units.get("apparent_temperature", "°C")
    u_prec = units.get("precipitation", "mm")
    u_pp = units.get("precipitation_probability", "%")
    u_ws = units.get("wind_speed_10m", "km/h")

    # Parse & filter times None
    times_dt = parse_times(times)
    times_ok, series_ok = filter_none_times(times_dt, [temp, feel, prec, pprob, wspd, wdir])
    temp_ok, feel_ok, prec_ok, pprob_ok, wspd_ok, wdir_ok = series_ok

    os.makedirs(out_graf_dir, exist_ok=True)

    # ---------- Paso 8 ----------
    plot_line(
        times_ok, temp_ok,
        title=f"Temperatura por hora — {city_label} — {tz}",
        xlabel="Hora",
        ylabel=f"Temperatura ({u_temp})",
        out_path=os.path.join(out_graf_dir, f"{base_name}__temp.png"),
        show=show
    )

    plot_bar(
        times_ok, prec_ok,
        title=f"Precipitación por hora — {city_label} — {tz}",
        xlabel="Hora",
        ylabel=f"Precipitación ({u_prec})",
        out_path=os.path.join(out_graf_dir, f"{base_name}__precip.png"),
        show=show
    )

    # ---------- Paso 9 ----------
    if pprob_ok:
        plot_line(
            times_ok, pprob_ok,
            title=f"Prob. de precipitación — {city_label} — {tz}",
            xlabel="Hora",
            ylabel=f"Probabilidad ({u_pp})",
            out_path=os.path.join(out_graf_dir, f"{base_name}__pprob.png"),
            show=show
        )

    if wspd_ok:
        plot_line(
            times_ok, wspd_ok,
            title=f"Velocidad del viento — {city_label} — {tz}",
            xlabel="Hora",
            ylabel=f"Viento ({u_ws})",
            out_path=os.path.join(out_graf_dir, f"{base_name}__wind_speed.png"),
            show=show
        )

    if temp_ok and feel_ok:
        plot_two_lines(
            times_ok, temp_ok, feel_ok,
            label1="Temperatura",
            label2="Sensación",
            title=f"Temp vs Sensación — {city_label} — {tz}",
            xlabel="Hora",
            ylabel=f"Temperatura ({u_temp})",
            out_path=os.path.join(out_graf_dir, f"{base_name}__temp_vs_feel.png"),
            show=show
        )

    # precip acumulada
    acumulada = []
    total = 0.0
    for v in prec_ok:
        total += safe_float(v, 0.0)
        acumulada.append(total)

    plot_line(
        times_ok, acumulada,
        title=f"Precipitación acumulada — {city_label} — {tz}",
        xlabel="Hora",
        ylabel=f"Acumulada ({u_prec})",
        out_path=os.path.join(out_graf_dir, f"{base_name}__precip_acum.png"),
        show=show
    )

    # dirección viento (0..360)
    if wdir_ok:
        import matplotlib.pyplot as plt
        plt.figure()
        plt.plot(times_ok, wdir_ok)
        plt.title(f"Dirección del viento — {city_label} — {tz}")
        plt.xlabel("Hora")
        plt.ylabel("Dirección (°)")
        plt.ylim(0, 360)
        plt.grid(True)
        plt.xticks(rotation=45, ha="right")
        save_fig(os.path.join(out_graf_dir, f"{base_name}__wind_dir_deg.png"), show=show)


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="TODO-EN-UNO: fetch hourly + gráficas (Paso 8 y 9).")
    parser.add_argument("--city", default="Madrid", help='Ciudad (ej: "Madrid", "Valencia", "Lima")')
    parser.add_argument("--countryCode", default=None, help="Filtro país ISO2 (ej: ES, PE). Opcional.")
    parser.add_argument("--hours", type=int, default=48, help="Horas de predicción (24 o 48).")
    parser.add_argument("--timezone", default="auto", help='Timezone (recomendado: "auto").')
    parser.add_argument("--pick", type=int, default=0, help="Qué candidato usar del geocoding (0 = primero).")
    parser.add_argument("--out", default="salidas_clima", help="Carpeta de salida.")
    parser.add_argument("--show", action="store_true", help="Muestra gráficas en pantalla (además de guardarlas).")
    args = parser.parse_args()

    # Backend matplotlib: si NO quieres mostrar, usamos Agg (sin UI)
    import matplotlib
    if not args.show:
        matplotlib.use("Agg")

    # dirs
    os.makedirs(args.out, exist_ok=True)
    graf_dir = os.path.join(args.out, "graficas")
    os.makedirs(graf_dir, exist_ok=True)

    # 1) geocoding
    print(f"📍 Geocoding: {args.city}")
    results = geocoding(args.city, args.countryCode, count=5)

    print("\nCandidatos encontrados:")
    for i, r in enumerate(results):
        name = r.get("name", "")
        admin1 = r.get("admin1", "")
        country = r.get("country", "")
        tz = r.get("timezone", "")
        lat = r.get("latitude", "")
        lon = r.get("longitude", "")
        print(f"  [{i}] {name} · {admin1} · {country} | {lat},{lon} | tz={tz}")

    if args.pick < 0 or args.pick >= len(results):
        raise RuntimeError(f"--pick fuera de rango. Debe ser 0..{len(results)-1}")

    loc = results[args.pick]
    lat = loc["latitude"]
    lon = loc["longitude"]
    label = f"{loc.get('name','')} · {loc.get('admin1','')} · {loc.get('country','')}".strip(" ·")

    print(f"\n✅ Usando: [{args.pick}] {label}")
    print(f"🕒 Pidiendo hourly {args.hours}h (timezone={args.timezone})...")

    # 2) fetch forecast hourly
    data = forecast_hourly(lat, lon, args.timezone, args.hours)

    # 3) guardar JSON
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_city = slugify(args.city)
    base_name = f"{safe_city}_{ts}__hourly_{args.hours}h"

    json_path = os.path.join(args.out, f"{base_name}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ JSON guardado en: {json_path}")

    # 4) generar gráficas
    print("\n📊 Generando gráficas (Paso 8 + Paso 9)...")
    generate_all_graphs(
        json_data=data,
        city_label=label,
        out_graf_dir=graf_dir,
        base_name=base_name,
        show=args.show
    )

    print("\n✅ Listo.")
    print(f"📁 Gráficas en: {graf_dir}")
    print("   (archivos con prefijo:", base_name + ")")

    if not args.show:
        print("\nTip: si quieres que se abran las ventanas, usa --show")


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        print("❌ Error de red/HTTP:", e)
    except Exception as e:
        print("❌ Error:", e)
