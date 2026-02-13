#!/usr/bin/env python3
# ============================================================
# 015-clima_dashboard_flask.py
# ------------------------------------------------------------
# Dashboard de clima tipo "data analyzer" (Flask) + updater
#
# ✅ Front web:
#    - Ver gráficas por ciudad (máx 4)
#    - Ver texto: current, stats, 7 días, hourly 48h
#    - Ver/descargar reporte Markdown
#    - Añadir ciudad con countryCode (ES/PE...) y eliminar
#
# ✅ Updater en segundo plano (mientras el script está encendido):
#    - Cada X segundos (default 300 = 5 min) descarga Open-Meteo
#    - Guarda latest.json (sobrescribe)
#    - Guarda snapshots con retención (borra lo viejo)
#    - Genera gráficas PNG (sobrescribe; NO se acumulan)
#
# Requisitos:
#   pip install flask requests matplotlib
#
# Ejecutar:
#   py 015-clima_dashboard_flask.py
# Abrir:
#   http://127.0.0.1:5000
# ============================================================

import os
import re
import json
import time
import glob
import shutil
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

import requests
from flask import Flask, request, redirect, url_for, send_from_directory, render_template_string, make_response

# Matplotlib headless (para servidor)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ============================================================
# CONFIG
# ============================================================

MAX_CITIES = 4

DATA_DIR = "clima_live"                    # carpeta base (config + datos)
CONFIG_PATH = os.path.join(DATA_DIR, "cities.json")

DEFAULT_INTERVAL_SECONDS = 300             # 5 min recomendado
DEFAULT_FORECAST_HOURS = 48                # 48h por defecto
DEFAULT_SNAPSHOT_RETENTION = 24            # 24 snapshots (ej: 2h si interval=5min)
DEFAULT_TIMEZONE = "auto"                  # auto recomendado

# Refresh del navegador (solo UI): 60s está bien
UI_AUTOREFRESH_SECONDS = 60

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

DAILY_VARS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "weather_code",
]

CURRENT_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "precipitation",
    "weather_code",
    "wind_speed_10m",
    "wind_direction_10m",
]

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

CONFIG_LOCK = threading.Lock()
STOP_EVENT = threading.Event()


# ============================================================
# Helpers generales
# ============================================================

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def slugify(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9_-]+", "_", text)
    return text.strip("_") or "city"


def wmo_desc(code) -> str:
    try:
        c = int(code)
        return WMO.get(c, f"Código {c}")
    except Exception:
        return "—"


def safe_float(x, default=None):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def parse_times(times: List[str]) -> List[Optional[datetime]]:
    out = []
    for t in times:
        try:
            out.append(datetime.fromisoformat(t))
        except Exception:
            out.append(None)
    return out


def filter_none_times(times_dt: List[Optional[datetime]], series: List[List[Any]]):
    idx_ok = [i for i, dt in enumerate(times_dt) if dt is not None]
    times_ok = [times_dt[i] for i in idx_ok]
    series_ok = []
    for arr in series:
        series_ok.append([arr[i] if i < len(arr) else None for i in idx_ok])
    return times_ok, series_ok


def atomic_write_json(path: str, data: dict):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ============================================================
# Estructura de carpetas por ciudad
# ============================================================

def cities_root() -> str:
    return os.path.join(DATA_DIR, "cities")


def city_folder(city_id: str) -> str:
    return os.path.join(cities_root(), city_id)


def city_latest_path(city_id: str) -> str:
    return os.path.join(city_folder(city_id), "latest.json")


def city_status_path(city_id: str) -> str:
    return os.path.join(city_folder(city_id), "status.json")


def city_snapshots_dir(city_id: str) -> str:
    return os.path.join(city_folder(city_id), "snapshots")


def city_graphs_dir(city_id: str) -> str:
    return os.path.join(city_folder(city_id), "graphs")


# ============================================================
# Config (cities.json)
# ============================================================

def default_config() -> Dict[str, Any]:
    return {
        "settings": {
            "interval_seconds": DEFAULT_INTERVAL_SECONDS,
            "forecast_hours": DEFAULT_FORECAST_HOURS,
            "timezone": DEFAULT_TIMEZONE,
            "snapshot_retention": DEFAULT_SNAPSHOT_RETENTION,
        },
        "cities": []
    }


def load_config() -> Dict[str, Any]:
    ensure_dir(DATA_DIR)
    if not os.path.exists(CONFIG_PATH):
        cfg = default_config()
        atomic_write_json(CONFIG_PATH, cfg)
        return cfg

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    if "settings" not in cfg:
        cfg["settings"] = default_config()["settings"]
    if "cities" not in cfg:
        cfg["cities"] = []

    return cfg


def save_config(cfg: Dict[str, Any]):
    ensure_dir(DATA_DIR)
    atomic_write_json(CONFIG_PATH, cfg)


def get_cities(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    return cfg.get("cities", []) or []


# ============================================================
# Open-Meteo
# ============================================================

def get_json(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()


def geocoding(query: str, country_code: Optional[str], count: int = 5) -> List[Dict[str, Any]]:
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {
        "name": query,
        "count": count,
        "language": "es",
        "format": "json",
    }
    if country_code:
        params["countryCode"] = country_code.upper()

    data = get_json(url, params)
    results = data.get("results") or []
    if not results:
        msg = f"No se encontraron resultados para: {query}"
        if country_code:
            msg += f" (countryCode={country_code.upper()})"
        raise RuntimeError(msg)
    return results


def fetch_forecast(lat: float, lon: float, hours: int, tz: str) -> dict:
    # Pedimos HOURLY 48h + CURRENT + DAILY 7 días
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": tz,
        "forecast_hours": hours,

        "hourly": ",".join(HOURLY_VARS),

        "forecast_days": 7,
        "daily": ",".join(DAILY_VARS),

        "current": ",".join(CURRENT_VARS),
    }
    return get_json(url, params)


# ============================================================
# Guardado + retención + status
# ============================================================

def write_status(city_id: str, ok: bool, message: str):
    ensure_dir(city_folder(city_id))
    payload = {
        "ok": ok,
        "message": message,
        "updated_at": iso_now(),
    }
    atomic_write_json(city_status_path(city_id), payload)


def read_status(city_id: str) -> Dict[str, Any]:
    path = city_status_path(city_id)
    if not os.path.exists(path):
        return {"ok": False, "message": "Sin actualizar aún", "updated_at": ""}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"ok": False, "message": "Status corrupto", "updated_at": ""}


def save_latest_and_snapshot(city_id: str, data: dict, retention: int):
    ensure_dir(city_folder(city_id))
    ensure_dir(city_snapshots_dir(city_id))

    # latest.json (sobrescribe)
    atomic_write_json(city_latest_path(city_id), data)

    # snapshot
    snap_path = os.path.join(city_snapshots_dir(city_id), f"{now_ts()}.json")
    atomic_write_json(snap_path, data)

    # retención
    snaps = glob.glob(os.path.join(city_snapshots_dir(city_id), "*.json"))
    snaps.sort(key=os.path.getmtime, reverse=True)
    for old in snaps[retention:]:
        try:
            os.remove(old)
        except Exception:
            pass


def read_latest(city_id: str) -> Optional[dict]:
    path = city_latest_path(city_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ============================================================
# Gráficas (sobrescriben)
# ============================================================

def save_fig(path: str):
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()


def plot_line(times, y, title: str, xlabel: str, ylabel: str, out_path: str):
    plt.figure()
    plt.plot(times, y)
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.grid(True)
    plt.xticks(rotation=45, ha="right")
    save_fig(out_path)


def plot_bar(times, y, title: str, xlabel: str, ylabel: str, out_path: str):
    plt.figure()
    plt.bar(times, y)
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.grid(True)
    plt.xticks(rotation=45, ha="right")
    save_fig(out_path)


def plot_two_lines(times, y1, y2, label1: str, label2: str, title: str, xlabel: str, ylabel: str, out_path: str):
    plt.figure()
    plt.plot(times, y1, label=label1)
    plt.plot(times, y2, label=label2)
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.grid(True)
    plt.legend()
    plt.xticks(rotation=45, ha="right")
    save_fig(out_path)


def generate_graphs(city_id: str, city_label: str, data: dict):
    gdir = city_graphs_dir(city_id)
    ensure_dir(gdir)

    hourly = data.get("hourly", {}) or {}
    units = data.get("hourly_units", {}) or {}
    tz = data.get("timezone", "auto")

    times = hourly.get("time", []) or []
    if not times:
        raise RuntimeError("Sin hourly.time")

    temp = hourly.get("temperature_2m", []) or []
    feel = hourly.get("apparent_temperature", []) or []
    prec = hourly.get("precipitation", []) or []
    pprob = hourly.get("precipitation_probability", []) or []
    wspd = hourly.get("wind_speed_10m", []) or []
    wdir = hourly.get("wind_direction_10m", []) or []

    u_temp = units.get("temperature_2m", "°C")
    u_prec = units.get("precipitation", "mm")
    u_pp = units.get("precipitation_probability", "%")
    u_ws = units.get("wind_speed_10m", "km/h")

    times_dt = parse_times(times)
    times_ok, series_ok = filter_none_times(times_dt, [temp, feel, prec, pprob, wspd, wdir])
    temp_ok, feel_ok, prec_ok, pprob_ok, wspd_ok, wdir_ok = series_ok

    # Paso 8
    plot_line(
        times_ok, temp_ok,
        title=f"Temperatura (48h) — {city_label} — {tz}",
        xlabel="Hora",
        ylabel=f"Temperatura ({u_temp})",
        out_path=os.path.join(gdir, "temp.png"),
    )

    plot_bar(
        times_ok, prec_ok,
        title=f"Precipitación por hora (48h) — {city_label} — {tz}",
        xlabel="Hora",
        ylabel=f"Precipitación ({u_prec})",
        out_path=os.path.join(gdir, "precip.png"),
    )

    # Paso 9
    if pprob_ok:
        plot_line(
            times_ok, pprob_ok,
            title=f"Prob. precipitación (48h) — {city_label} — {tz}",
            xlabel="Hora",
            ylabel=f"Probabilidad ({u_pp})",
            out_path=os.path.join(gdir, "pprob.png"),
        )

    if wspd_ok:
        plot_line(
            times_ok, wspd_ok,
            title=f"Viento (48h) — {city_label} — {tz}",
            xlabel="Hora",
            ylabel=f"Velocidad ({u_ws})",
            out_path=os.path.join(gdir, "wind_speed.png"),
        )

    if temp_ok and feel_ok:
        plot_two_lines(
            times_ok, temp_ok, feel_ok,
            label1="Temperatura",
            label2="Sensación",
            title=f"Temp vs Sensación (48h) — {city_label} — {tz}",
            xlabel="Hora",
            ylabel=f"Temperatura ({u_temp})",
            out_path=os.path.join(gdir, "temp_vs_feel.png"),
        )

    # precip acumulada
    acumulada = []
    total = 0.0
    for v in prec_ok:
        total += safe_float(v, 0.0) or 0.0
        acumulada.append(total)

    plot_line(
        times_ok, acumulada,
        title=f"Precipitación acumulada (48h) — {city_label} — {tz}",
        xlabel="Hora",
        ylabel=f"Acumulada ({u_prec})",
        out_path=os.path.join(gdir, "precip_acum.png"),
    )

    # dirección del viento
    if wdir_ok:
        plt.figure()
        plt.plot(times_ok, wdir_ok)
        plt.title(f"Dirección del viento (48h) — {city_label} — {tz}")
        plt.xlabel("Hora")
        plt.ylabel("Dirección (°)")
        plt.ylim(0, 360)
        plt.grid(True)
        plt.xticks(rotation=45, ha="right")
        save_fig(os.path.join(gdir, "wind_dir_deg.png"))


# ============================================================
# Texto: current + daily + hourly + stats + markdown
# ============================================================

def compute_weekly_stats(daily: dict) -> Dict[str, Any]:
    days = daily.get("time", []) or []
    tmax = [safe_float(x) for x in (daily.get("temperature_2m_max", []) or [])]
    tmin = [safe_float(x) for x in (daily.get("temperature_2m_min", []) or [])]
    psum = [safe_float(x, 0.0) for x in (daily.get("precipitation_sum", []) or [])]
    pprob = [safe_float(x) for x in (daily.get("precipitation_probability_max", []) or [])]

    def argmax(vals):
        bi, bv = None, None
        for i, v in enumerate(vals):
            if v is None:
                continue
            if bv is None or v > bv:
                bv, bi = v, i
        return bi, bv

    def argmin(vals):
        bi, bv = None, None
        for i, v in enumerate(vals):
            if v is None:
                continue
            if bv is None or v < bv:
                bv, bi = v, i
        return bi, bv

    i_max, v_max = argmax(tmax)
    i_min, v_min = argmin(tmin)
    i_pp, v_pp = argmax(pprob)

    avg_max = (sum([v for v in tmax if v is not None]) / max(1, len([v for v in tmax if v is not None]))) if tmax else None
    avg_min = (sum([v for v in tmin if v is not None]) / max(1, len([v for v in tmin if v is not None]))) if tmin else None

    return {
        "tmax": v_max, "tmax_day": days[i_max] if i_max is not None and i_max < len(days) else None,
        "tmin": v_min, "tmin_day": days[i_min] if i_min is not None and i_min < len(days) else None,
        "avg_tmax": avg_max,
        "avg_tmin": avg_min,
        "precip_total": sum(psum) if psum else 0.0,
        "pprob_max": v_pp, "pprob_day": days[i_pp] if i_pp is not None and i_pp < len(days) else None,
    }


def build_markdown_report(city_label: str, data: dict) -> str:
    tz = data.get("timezone", "auto")
    current = data.get("current", {}) or {}
    daily = data.get("daily", {}) or {}
    daily_units = data.get("daily_units", {}) or {}
    hourly = data.get("hourly", {}) or {}
    hourly_units = data.get("hourly_units", {}) or {}

    stats = compute_weekly_stats(daily) if daily else {}

    lines = []
    lines.append(f"# Reporte del clima — {city_label}")
    lines.append("")
    lines.append(f"- Zona horaria: {tz}")
    lines.append(f"- Generado: {iso_now()}")
    lines.append("")
    lines.append("## Clima actual (current)")
    lines.append("")
    if current:
        t = current.get("temperature_2m")
        feel = current.get("apparent_temperature")
        rh = current.get("relative_humidity_2m")
        pr = current.get("precipitation")
        wc = current.get("weather_code")
        ws = current.get("wind_speed_10m")
        wd = current.get("wind_direction_10m")
        lines.append(f"- Temperatura: {t}{data.get('current_units',{}).get('temperature_2m','')}")
        lines.append(f"- Sensación: {feel}{data.get('current_units',{}).get('apparent_temperature','')}")
        lines.append(f"- Humedad: {rh}{data.get('current_units',{}).get('relative_humidity_2m','')}")
        lines.append(f"- Precipitación: {pr}{data.get('current_units',{}).get('precipitation','')}")
        lines.append(f"- Estado: {wc} — {wmo_desc(wc)}")
        lines.append(f"- Viento: {ws}{data.get('current_units',{}).get('wind_speed_10m','')} · Dir {wd}°")
    else:
        lines.append("- (sin datos current)")

    lines.append("")
    lines.append("## Resumen semanal (stats)")
    lines.append("")
    if stats:
        lines.append(f"- Tmax semanal: {stats.get('tmax')} {daily_units.get('temperature_2m_max','')} ({stats.get('tmax_day')})")
        lines.append(f"- Tmin semanal: {stats.get('tmin')} {daily_units.get('temperature_2m_min','')} ({stats.get('tmin_day')})")
        lines.append(f"- Promedio Tmax: {stats.get('avg_tmax'):.1f}{daily_units.get('temperature_2m_max','')}" if stats.get("avg_tmax") is not None else "- Promedio Tmax: —")
        lines.append(f"- Promedio Tmin: {stats.get('avg_tmin'):.1f}{daily_units.get('temperature_2m_min','')}" if stats.get("avg_tmin") is not None else "- Promedio Tmin: —")
        lines.append(f"- Precipitación total 7 días: {stats.get('precip_total'):.1f}{daily_units.get('precipitation_sum','')}")
        if stats.get("pprob_max") is not None:
            lines.append(f"- Día con mayor prob. precip: {stats.get('pprob_day')} ({stats.get('pprob_max'):.0f}{daily_units.get('precipitation_probability_max','')})")
    else:
        lines.append("- (sin datos daily)")

    lines.append("")
    lines.append("## Próximos 7 días (daily)")
    lines.append("")
    days = daily.get("time", []) or []
    if days:
        lines.append("| Fecha | Tmin | Tmax | Prob | Precip | Estado |")
        lines.append("|---|---:|---:|---:|---:|---|")
        tmax = daily.get("temperature_2m_max", []) or []
        tmin = daily.get("temperature_2m_min", []) or []
        psum = daily.get("precipitation_sum", []) or []
        pprob = daily.get("precipitation_probability_max", []) or []
        wcode = daily.get("weather_code", []) or []
        for i, d in enumerate(days):
            lines.append(
                f"| {d} | {tmin[i]}{daily_units.get('temperature_2m_min','')} | "
                f"{tmax[i]}{daily_units.get('temperature_2m_max','')} | "
                f"{pprob[i]}{daily_units.get('precipitation_probability_max','')} | "
                f"{psum[i]}{daily_units.get('precipitation_sum','')} | "
                f"{wcode[i]} — {wmo_desc(wcode[i])} |"
            )
    else:
        lines.append("- (sin datos daily)")

    lines.append("")
    lines.append("## Hourly 48h (preview)")
    lines.append("")
    ht = hourly.get("time", []) or []
    if ht:
        lines.append("| Hora | Temp | Sensación | Precip | Prob | Viento | Dir | Estado |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---|")
        temp = hourly.get("temperature_2m", []) or []
        feel = hourly.get("apparent_temperature", []) or []
        prec = hourly.get("precipitation", []) or []
        pprob = hourly.get("precipitation_probability", []) or []
        wspd = hourly.get("wind_speed_10m", []) or []
        wdir = hourly.get("wind_direction_10m", []) or []
        wcode = hourly.get("weather_code", []) or []
        # Para que no sea eterno en MD, mostramos 48 filas igual (son manejables)
        for i in range(min(48, len(ht))):
            lines.append(
                f"| {ht[i]} | {temp[i]}{hourly_units.get('temperature_2m','')} | "
                f"{feel[i]}{hourly_units.get('apparent_temperature','')} | "
                f"{prec[i]}{hourly_units.get('precipitation','')} | "
                f"{pprob[i]}{hourly_units.get('precipitation_probability','')} | "
                f"{wspd[i]}{hourly_units.get('wind_speed_10m','')} | "
                f"{wdir[i]}° | {wcode[i]} — {wmo_desc(wcode[i])} |"
            )
    else:
        lines.append("- (sin hourly)")

    lines.append("")
    return "\n".join(lines)


def build_hourly_rows(data: dict) -> List[Dict[str, Any]]:
    hourly = data.get("hourly", {}) or {}
    units = data.get("hourly_units", {}) or {}
    times = hourly.get("time", []) or []
    temp = hourly.get("temperature_2m", []) or []
    feel = hourly.get("apparent_temperature", []) or []
    prec = hourly.get("precipitation", []) or []
    pprob = hourly.get("precipitation_probability", []) or []
    wspd = hourly.get("wind_speed_10m", []) or []
    wdir = hourly.get("wind_direction_10m", []) or []
    wcode = hourly.get("weather_code", []) or []

    rows = []
    for i in range(min(48, len(times))):
        rows.append({
            "time": times[i],
            "temp": temp[i], "u_temp": units.get("temperature_2m", "°C"),
            "feel": feel[i], "u_feel": units.get("apparent_temperature", "°C"),
            "prec": prec[i], "u_prec": units.get("precipitation", "mm"),
            "pprob": pprob[i], "u_pprob": units.get("precipitation_probability", "%"),
            "wspd": wspd[i], "u_wspd": units.get("wind_speed_10m", "km/h"),
            "wdir": wdir[i],
            "wcode": wcode[i],
            "desc": wmo_desc(wcode[i]),
        })
    return rows


def build_daily_rows(data: dict) -> List[Dict[str, Any]]:
    daily = data.get("daily", {}) or {}
    units = data.get("daily_units", {}) or {}

    days = daily.get("time", []) or []
    tmax = daily.get("temperature_2m_max", []) or []
    tmin = daily.get("temperature_2m_min", []) or []
    psum = daily.get("precipitation_sum", []) or []
    pprob = daily.get("precipitation_probability_max", []) or []
    wcode = daily.get("weather_code", []) or []

    rows = []
    for i in range(min(7, len(days))):
        rows.append({
            "day": days[i],
            "tmin": tmin[i], "u_tmin": units.get("temperature_2m_min", "°C"),
            "tmax": tmax[i], "u_tmax": units.get("temperature_2m_max", "°C"),
            "psum": psum[i], "u_psum": units.get("precipitation_sum", "mm"),
            "pprob": pprob[i], "u_pprob": units.get("precipitation_probability_max", "%"),
            "wcode": wcode[i],
            "desc": wmo_desc(wcode[i]),
        })
    return rows


def build_current_summary(data: dict) -> Dict[str, Any]:
    cur = data.get("current", {}) or {}
    u = data.get("current_units", {}) or {}
    if not cur:
        return {}

    wc = cur.get("weather_code")
    return {
        "temp": cur.get("temperature_2m"), "u_temp": u.get("temperature_2m", "°C"),
        "feel": cur.get("apparent_temperature"), "u_feel": u.get("apparent_temperature", "°C"),
        "rh": cur.get("relative_humidity_2m"), "u_rh": u.get("relative_humidity_2m", "%"),
        "prec": cur.get("precipitation"), "u_prec": u.get("precipitation", "mm"),
        "wspd": cur.get("wind_speed_10m"), "u_wspd": u.get("wind_speed_10m", "km/h"),
        "wdir": cur.get("wind_direction_10m"),
        "wcode": wc, "desc": wmo_desc(wc),
    }


# ============================================================
# Updater (thread)
# ============================================================

def update_one_city(settings: Dict[str, Any], city: Dict[str, Any]):
    city_id = city["id"]
    label = city["label"]
    hours = int(settings.get("forecast_hours", DEFAULT_FORECAST_HOURS))
    tz = city.get("timezone") or settings.get("timezone", DEFAULT_TIMEZONE)
    retention = int(settings.get("snapshot_retention", DEFAULT_SNAPSHOT_RETENTION))

    try:
        data = fetch_forecast(city["lat"], city["lon"], hours, tz)
        save_latest_and_snapshot(city_id, data, retention)
        generate_graphs(city_id, label, data)
        write_status(city_id, ok=True, message="OK")
        print(f"✅ {label} actualizado ({iso_now()})")
    except Exception as e:
        write_status(city_id, ok=False, message=str(e))
        print(f"❌ {label} falló: {e}")


def updater_loop():
    while not STOP_EVENT.is_set():
        with CONFIG_LOCK:
            cfg = load_config()
        settings = cfg.get("settings", {}) or {}
        cities = get_cities(cfg)

        if cities:
            for c in cities:
                if STOP_EVENT.is_set():
                    break
                update_one_city(settings, c)
        else:
            print("📭 No hay ciudades (aún). Agrega desde el dashboard.")

        interval = int(settings.get("interval_seconds", DEFAULT_INTERVAL_SECONDS))
        # Dormimos pero permitimos salir rápido si STOP_EVENT se activa
        for _ in range(interval):
            if STOP_EVENT.is_set():
                break
            time.sleep(1)


# ============================================================
# Flask app
# ============================================================

app = Flask(__name__)


TEMPLATE_DASH = r"""
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>Clima Analyzer (Flask)</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="{{ ui_refresh }}">
  <style>
    :root{
      --bg:#0b1220;
      --card:#0f1a2e;
      --muted:#9fb0cc;
      --text:#eaf0ff;
      --line:#1e2b45;
      --ok:#22c55e;
      --bad:#ef4444;
      --warn:#f59e0b;
      --btn:#2563eb;
      --btn2:#0ea5e9;
    }
    *{ box-sizing:border-box; }
    body{
      margin:0; font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;
      background:linear-gradient(135deg,#071022,#0b1220);
      color:var(--text);
      padding:18px;
    }
    h1{ margin:0 0 10px; font-size:22px; }
    .muted{ color:var(--muted); font-size:13px; }
    .wrap{ display:grid; gap:14px; grid-template-columns: 360px 1fr; align-items:start; }
    @media (max-width: 1100px){ .wrap{ grid-template-columns:1fr; } }

    .card{
      background:rgba(15,26,46,.88);
      border:1px solid var(--line);
      border-radius:16px;
      padding:14px;
      box-shadow:0 18px 40px rgba(0,0,0,.35);
    }
    .row{ display:flex; gap:10px; flex-wrap:wrap; }
    label{ font-size:13px; color:var(--muted); display:block; margin:6px 0 4px; }
    input, select{
      width:100%;
      padding:10px 10px;
      border-radius:12px;
      border:1px solid var(--line);
      background:#0b1326;
      color:var(--text);
      outline:none;
    }
    button{
      padding:10px 12px;
      border-radius:12px;
      border:1px solid var(--line);
      background:var(--btn);
      color:white;
      cursor:pointer;
      font-weight:600;
    }
    button.secondary{ background:#0b1326; color:var(--text); }
    .pill{
      display:inline-flex; align-items:center; gap:8px;
      padding:6px 10px; border-radius:999px; font-size:12px;
      border:1px solid var(--line); background:#0b1326;
    }
    .dot{ width:8px; height:8px; border-radius:999px; background:var(--warn); }
    .dot.ok{ background:var(--ok); }
    .dot.bad{ background:var(--bad); }

    .cities{
      display:grid; gap:14px;
      grid-template-columns: repeat(2, minmax(280px, 1fr));
    }
    @media (max-width: 900px){ .cities{ grid-template-columns:1fr; } }

    .city-head{
      display:flex; justify-content:space-between; gap:10px; align-items:flex-start;
    }
    .city-title{ font-size:16px; margin:0; line-height:1.2; }
    .city-actions form{ margin:0; }

    details{ border:1px solid var(--line); border-radius:14px; padding:10px; background:#0b1326; }
    summary{ cursor:pointer; font-weight:700; }
    .grid-graphs{
      display:grid; gap:10px;
      grid-template-columns: repeat(2, minmax(220px, 1fr));
      margin-top:10px;
    }
    @media (max-width: 520px){ .grid-graphs{ grid-template-columns:1fr; } }
    img{
      width:100%;
      border-radius:14px;
      border:1px solid var(--line);
      background:#071022;
    }

    table{ width:100%; border-collapse:collapse; margin-top:10px; font-size:13px; }
    th, td{ border-bottom:1px solid var(--line); padding:8px 6px; text-align:left; vertical-align:top; }
    th{ color:var(--muted); font-weight:700; }
    .pre{
      background:#071022;
      border:1px solid var(--line);
      border-radius:14px;
      padding:12px;
      overflow:auto;
      white-space:pre;
      max-height:380px;
      font-size:12px;
      color:#dbe7ff;
      margin-top:10px;
    }
    a{ color:#93c5fd; text-decoration:none; }
    a:hover{ text-decoration:underline; }
  </style>
</head>
<body>
  <h1>🌦️ Clima Analyzer (máx {{ max_cities }} ciudades)</h1>
  <div class="muted">
    Update worker: cada <b>{{ interval }}</b> segundos · UI auto-refresh: {{ ui_refresh }}s ·
    JSON snapshots retención: {{ retention }} · Horas: {{ hours }} · Timezone: {{ tz }}
  </div>

  <div class="wrap" style="margin-top:12px;">
    <!-- Panel izquierdo: gestión -->
    <div class="card">
      <h2 style="margin:0 0 10px; font-size:16px;">⚙️ Gestión</h2>

      <form method="post" action="{{ url_for('add_city') }}">
        <label>Ciudad</label>
        <input name="query" placeholder='Ej: Valencia o Lima' required>

        <label>countryCode (ISO2) (opcional)</label>
        <input name="countryCode" placeholder="Ej: ES / PE">

        <button type="submit" style="margin-top:10px; width:100%;">➕ Añadir ciudad</button>
      </form>

      <hr style="border:none; border-top:1px solid var(--line); margin:14px 0;">

      <form method="post" action="{{ url_for('update_settings') }}">
        <label>Intervalo actualización (segundos)</label>
        <input name="interval_seconds" value="{{ interval }}">

        <label>Retención snapshots JSON</label>
        <input name="snapshot_retention" value="{{ retention }}">

        <button class="secondary" type="submit" style="margin-top:10px; width:100%;">💾 Guardar settings</button>
      </form>

      {% if msg %}
        <div style="margin-top:12px;" class="pill">
          <span class="dot"></span>
          <span>{{ msg }}</span>
        </div>
      {% endif %}
    </div>

    <!-- Panel derecho: ciudades -->
    <div class="card">
      <h2 style="margin:0 0 10px; font-size:16px;">📌 Ciudades</h2>

      {% if not cities %}
        <div class="muted">No hay ciudades aún. Añade una a la izquierda.</div>
      {% else %}
      <div class="cities">
        {% for c in cities %}
          <div class="card" style="padding:12px;">
            <div class="city-head">
              <div>
                <p class="city-title"><b>{{ c.label }}</b></p>

                <div class="pill">
                  {% if c.status.ok %}
                    <span class="dot ok"></span>
                  {% else %}
                    <span class="dot bad"></span>
                  {% endif %}
                  <span>
                    {{ c.status.message }} · <span class="muted">{{ c.status.updated_at }}</span>
                  </span>
                </div>

                {% if c.current %}
                <div style="margin-top:10px;">
                  <div class="muted">Ahora</div>
                  <div style="margin-top:4px;">
                    <b>{{ c.current.temp }}{{ c.current.u_temp }}</b>
                    · Sensación {{ c.current.feel }}{{ c.current.u_feel }}
                    · Humedad {{ c.current.rh }}{{ c.current.u_rh }}
                    · {{ c.current.desc }}
                    · Viento {{ c.current.wspd }}{{ c.current.u_wspd }} ({{ c.current.wdir }}°)
                  </div>
                </div>
                {% endif %}
              </div>

              <div class="city-actions">
                <form method="post" action="{{ url_for('remove_city', city_id=c.id) }}">
                  <button type="submit" style="background:#ef4444;">🗑️</button>
                </form>
              </div>
            </div>

            <details style="margin-top:12px;" open>
              <summary>📊 Gráficas</summary>
              <div class="grid-graphs">
                {% for g in c.graphs %}
                  <div>
                    <div class="muted" style="margin:6px 0;">{{ g.label }}</div>
                    <img src="{{ g.url }}" alt="{{ g.label }}">
                  </div>
                {% endfor %}
              </div>
            </details>

            <details style="margin-top:12px;">
              <summary>🧾 Texto (stats + 7 días + hourly 48h)</summary>

              {% if c.stats %}
                <div style="margin-top:10px;">
                  <div class="muted">Resumen semanal</div>
                  <ul style="margin:6px 0 0 18px;">
                    <li><b>Tmax semanal:</b> {{ c.stats.tmax }} ({{ c.stats.tmax_day }})</li>
                    <li><b>Tmin semanal:</b> {{ c.stats.tmin }} ({{ c.stats.tmin_day }})</li>
                    <li><b>Promedio Tmax:</b> {{ c.stats.avg_tmax }}</li>
                    <li><b>Promedio Tmin:</b> {{ c.stats.avg_tmin }}</li>
                    <li><b>Precip total 7 días:</b> {{ c.stats.precip_total }}</li>
                    <li><b>Mayor prob. precip:</b> {{ c.stats.pprob_day }} ({{ c.stats.pprob_max }})</li>
                  </ul>
                </div>
              {% endif %}

              {% if c.daily_rows %}
                <div style="margin-top:12px;">
                  <div class="muted">Próximos 7 días</div>
                  <table>
                    <thead>
                      <tr>
                        <th>Fecha</th><th>Tmin</th><th>Tmax</th><th>Prob</th><th>Precip</th><th>Estado</th>
                      </tr>
                    </thead>
                    <tbody>
                      {% for r in c.daily_rows %}
                        <tr>
                          <td>{{ r.day }}</td>
                          <td>{{ r.tmin }}{{ r.u_tmin }}</td>
                          <td>{{ r.tmax }}{{ r.u_tmax }}</td>
                          <td>{{ r.pprob }}{{ r.u_pprob }}</td>
                          <td>{{ r.psum }}{{ r.u_psum }}</td>
                          <td>{{ r.wcode }} — {{ r.desc }}</td>
                        </tr>
                      {% endfor %}
                    </tbody>
                  </table>
                </div>
              {% endif %}

              {% if c.hourly_rows %}
                <div style="margin-top:12px;">
                  <div class="muted">Hourly 48h (48 filas)</div>
                  <table>
                    <thead>
                      <tr>
                        <th>Hora</th><th>Temp</th><th>Sens</th><th>Precip</th><th>Prob</th><th>Viento</th><th>Dir</th><th>Estado</th>
                      </tr>
                    </thead>
                    <tbody>
                      {% for r in c.hourly_rows %}
                        <tr>
                          <td>{{ r.time }}</td>
                          <td>{{ r.temp }}{{ r.u_temp }}</td>
                          <td>{{ r.feel }}{{ r.u_feel }}</td>
                          <td>{{ r.prec }}{{ r.u_prec }}</td>
                          <td>{{ r.pprob }}{{ r.u_pprob }}</td>
                          <td>{{ r.wspd }}{{ r.u_wspd }}</td>
                          <td>{{ r.wdir }}°</td>
                          <td>{{ r.wcode }} — {{ r.desc }}</td>
                        </tr>
                      {% endfor %}
                    </tbody>
                  </table>
                </div>
              {% endif %}

              <div style="margin-top:12px;">
                <div class="row" style="justify-content:space-between; align-items:center;">
                  <div class="muted">Reporte Markdown</div>
                  <div>
                    <a href="{{ url_for('city_report_md', city_id=c.id) }}">Descargar .md</a>
                  </div>
                </div>
                <div class="pre">{{ c.md }}</div>
              </div>
            </details>

          </div>
        {% endfor %}
      </div>
      {% endif %}
    </div>
  </div>
</body>
</html>
"""


TEMPLATE_PICK = r"""
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>Elegir ciudad</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body{ font-family:system-ui,Segoe UI,Roboto,Arial; margin:0; padding:18px; background:#0b1220; color:#eaf0ff; }
    .card{ background:#0f1a2e; border:1px solid #1e2b45; border-radius:16px; padding:14px; max-width:860px; margin:auto; }
    label{ display:block; margin:10px 0; padding:10px; border:1px solid #1e2b45; border-radius:14px; cursor:pointer; }
    input[type=radio]{ transform:scale(1.1); margin-right:10px; }
    button{ padding:10px 12px; border-radius:12px; border:1px solid #1e2b45; background:#2563eb; color:#fff; cursor:pointer; font-weight:700; }
    .muted{ color:#9fb0cc; font-size:13px; }
  </style>
</head>
<body>
  <div class="card">
    <h2 style="margin:0 0 8px;">Selecciona el resultado correcto</h2>
    <div class="muted">Esto pasa cuando el geocoding devuelve varias coincidencias.</div>

    <form method="post" action="{{ url_for('confirm_add_city') }}">
      <input type="hidden" name="query" value="{{ query }}">
      <input type="hidden" name="countryCode" value="{{ countryCode }}">

      {% for r in results %}
        <label>
          <input type="radio" name="pick" value="{{ loop.index0 }}" {% if loop.index0==0 %}checked{% endif %}>
          <b>{{ r.name }}</b> · {{ r.admin1 }} · {{ r.country }}
          <span class="muted"> | {{ r.latitude }}, {{ r.longitude }} | tz={{ r.timezone }}</span>
        </label>
      {% endfor %}

      <button type="submit">✅ Confirmar</button>
      <a class="muted" style="margin-left:12px;" href="{{ url_for('dashboard') }}">Cancelar</a>
    </form>
  </div>
</body>
</html>
"""


@app.route("/")
def dashboard():
    msg = request.args.get("msg", "")

    with CONFIG_LOCK:
        cfg = load_config()

    settings = cfg.get("settings", {}) or {}
    interval = int(settings.get("interval_seconds", DEFAULT_INTERVAL_SECONDS))
    hours = int(settings.get("forecast_hours", DEFAULT_FORECAST_HOURS))
    retention = int(settings.get("snapshot_retention", DEFAULT_SNAPSHOT_RETENTION))
    tz = settings.get("timezone", DEFAULT_TIMEZONE)

    cities = []
    for c in get_cities(cfg):
        cid = c["id"]
        status = read_status(cid)
        latest = read_latest(cid)

        current = build_current_summary(latest) if latest else {}
        daily_rows = build_daily_rows(latest) if latest else []
        hourly_rows = build_hourly_rows(latest) if latest else []

        stats_obj = {}
        if latest and latest.get("daily"):
            st = compute_weekly_stats(latest.get("daily", {}))
            # formateamos bonito para UI
            du = (latest.get("daily_units", {}) or {})
            stats_obj = {
                "tmax": f"{st.get('tmax')}{du.get('temperature_2m_max','')}",
                "tmax_day": st.get("tmax_day") or "—",
                "tmin": f"{st.get('tmin')}{du.get('temperature_2m_min','')}",
                "tmin_day": st.get("tmin_day") or "—",
                "avg_tmax": f"{st.get('avg_tmax'):.1f}{du.get('temperature_2m_max','')}" if st.get("avg_tmax") is not None else "—",
                "avg_tmin": f"{st.get('avg_tmin'):.1f}{du.get('temperature_2m_min','')}" if st.get("avg_tmin") is not None else "—",
                "precip_total": f"{st.get('precip_total'):.1f}{du.get('precipitation_sum','')}",
                "pprob_max": f"{st.get('pprob_max'):.0f}{du.get('precipitation_probability_max','')}" if st.get("pprob_max") is not None else "—",
                "pprob_day": st.get("pprob_day") or "—",
            }

        # graphs con cache-buster usando updated_at
        updated = status.get("updated_at", "")
        cache_ts = re.sub(r"[^0-9]", "", updated) or now_ts()

        graphs = []
        for fname, label in [
            ("temp.png", "Temperatura"),
            ("precip.png", "Precipitación/h"),
            ("pprob.png", "Prob. precipitación"),
            ("wind_speed.png", "Viento"),
            ("temp_vs_feel.png", "Temp vs Sensación"),
            ("precip_acum.png", "Precip acumulada"),
            ("wind_dir_deg.png", "Dirección viento"),
        ]:
            url = url_for("city_graph", city_id=cid, filename=fname) + f"?v={cache_ts}"
            graphs.append({"url": url, "label": label})

        md = build_markdown_report(c["label"], latest) if latest else f"# Reporte — {c['label']}\n\n(Aún sin datos. Espera a que el updater corra.)\n"

        cities.append({
            "id": cid,
            "label": c["label"],
            "status": status,
            "graphs": graphs,
            "current": current,
            "daily_rows": daily_rows,
            "hourly_rows": hourly_rows,
            "stats": stats_obj,
            "md": md,
        })

    return render_template_string(
        TEMPLATE_DASH,
        cities=cities,
        msg=msg,
        max_cities=MAX_CITIES,
        interval=interval,
        hours=hours,
        retention=retention,
        tz=tz,
        ui_refresh=UI_AUTOREFRESH_SECONDS,
    )


@app.route("/add", methods=["POST"])
def add_city():
    query = (request.form.get("query") or "").strip()
    country_code = (request.form.get("countryCode") or "").strip().upper() or None

    if not query:
        return redirect(url_for("dashboard", msg="Escribe una ciudad."))

    with CONFIG_LOCK:
        cfg = load_config()
        cities = get_cities(cfg)

        if len(cities) >= MAX_CITIES:
            return redirect(url_for("dashboard", msg=f"Máximo {MAX_CITIES} ciudades. Elimina una primero."))

    try:
        results = geocoding(query, country_code, count=5)
    except Exception as e:
        return redirect(url_for("dashboard", msg=f"Geocoding falló: {e}"))

    # Si hay más de 1, dejamos elegir. Si hay 1, igual mostramos selección (es rápido).
    # (Así evitas meter la ciudad equivocada sin querer.)
    # Convertimos a dict “simple” para template
    clean = []
    for r in results:
        clean.append({
            "name": r.get("name",""),
            "admin1": r.get("admin1",""),
            "country": r.get("country",""),
            "latitude": r.get("latitude",""),
            "longitude": r.get("longitude",""),
            "timezone": r.get("timezone",""),
        })

    return render_template_string(TEMPLATE_PICK, query=query, countryCode=(country_code or ""), results=clean)


@app.route("/confirm_add", methods=["POST"])
def confirm_add_city():
    query = (request.form.get("query") or "").strip()
    country_code = (request.form.get("countryCode") or "").strip().upper() or None
    pick_str = (request.form.get("pick") or "0").strip()

    if not query:
        return redirect(url_for("dashboard", msg="Falta query."))

    try:
        pick = int(pick_str)
    except ValueError:
        pick = 0

    with CONFIG_LOCK:
        cfg = load_config()
        cities = get_cities(cfg)

        if len(cities) >= MAX_CITIES:
            return redirect(url_for("dashboard", msg=f"Máximo {MAX_CITIES} ciudades. Elimina una primero."))

    try:
        results = geocoding(query, country_code, count=5)
        if pick < 0 or pick >= len(results):
            return redirect(url_for("dashboard", msg="Pick fuera de rango."))
        loc = results[pick]
    except Exception as e:
        return redirect(url_for("dashboard", msg=f"Geocoding falló: {e}"))

    label = f"{loc.get('name','')} · {loc.get('admin1','')} · {loc.get('country','')}".strip(" ·")
    cid = slugify(f"{loc.get('name','')}_{loc.get('admin1','')}_{loc.get('country','')}")

    with CONFIG_LOCK:
        cfg = load_config()
        cities = get_cities(cfg)

        # evitar duplicado
        if any(c.get("id") == cid for c in cities):
            return redirect(url_for("dashboard", msg="Esa ciudad ya estaba agregada."))

        cities.append({
            "id": cid,
            "query": query,
            "countryCode": country_code,
            "pick": pick,
            "lat": loc["latitude"],
            "lon": loc["longitude"],
            "label": label,
            "timezone": "auto",  # guardamos auto por defecto
        })
        cfg["cities"] = cities
        save_config(cfg)

    # creamos carpeta ciudad
    ensure_dir(city_folder(cid))
    ensure_dir(city_graphs_dir(cid))
    ensure_dir(city_snapshots_dir(cid))
    write_status(cid, ok=False, message="Añadida. Esperando primera actualización...")

    return redirect(url_for("dashboard", msg=f"Agregada: {label}"))


@app.route("/remove/<city_id>", methods=["POST"])
def remove_city(city_id: str):
    with CONFIG_LOCK:
        cfg = load_config()
        cities = get_cities(cfg)
        new_cities = [c for c in cities if c.get("id") != city_id]
        if len(new_cities) == len(cities):
            return redirect(url_for("dashboard", msg="No encontré esa ciudad."))

        cfg["cities"] = new_cities
        save_config(cfg)

    # borrar datos de esa ciudad (para no acumular basura)
    try:
        folder = city_folder(city_id)
        if os.path.isdir(folder):
            shutil.rmtree(folder, ignore_errors=True)
    except Exception:
        pass

    return redirect(url_for("dashboard", msg="Ciudad eliminada (ya puedes añadir otra)."))


@app.route("/settings", methods=["POST"])
def update_settings():
    interval = (request.form.get("interval_seconds") or "").strip()
    retention = (request.form.get("snapshot_retention") or "").strip()

    with CONFIG_LOCK:
        cfg = load_config()
        settings = cfg.get("settings", {}) or {}

        try:
            interval_i = int(interval)
            settings["interval_seconds"] = max(30, interval_i)  # mínimo 30s para evitar locuras
        except Exception:
            pass

        try:
            retention_i = int(retention)
            settings["snapshot_retention"] = max(1, retention_i)
        except Exception:
            pass

        cfg["settings"] = settings
        save_config(cfg)

    return redirect(url_for("dashboard", msg="Settings guardados."))


@app.route("/graphs/<city_id>/<filename>")
def city_graph(city_id: str, filename: str):
    gdir = city_graphs_dir(city_id)
    # si no existe, devolvemos 404 normal
    resp = send_from_directory(gdir, filename)
    # evitar cache fuerte del navegador
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@app.route("/report/<city_id>.md")
def city_report_md(city_id: str):
    # descargar markdown del reporte
    with CONFIG_LOCK:
        cfg = load_config()
    city = next((c for c in get_cities(cfg) if c.get("id") == city_id), None)
    if not city:
        return ("Ciudad no encontrada", 404)

    latest = read_latest(city_id)
    if not latest:
        md = f"# Reporte — {city.get('label')}\n\n(Aún sin datos)\n"
    else:
        md = build_markdown_report(city.get("label",""), latest)

    resp = make_response(md)
    resp.headers["Content-Type"] = "text/markdown; charset=utf-8"
    resp.headers["Content-Disposition"] = f'attachment; filename="{city_id}_reporte.md"'
    return resp


# ============================================================
# Main
# ============================================================

def main():
    ensure_dir(DATA_DIR)
    ensure_dir(cities_root())

    # arrancar updater thread
    t = threading.Thread(target=updater_loop, daemon=True)
    t.start()

    # arrancar flask
    print("🌐 Dashboard listo en: http://127.0.0.1:5000")
    print("🛑 Para parar: Ctrl+C")
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        STOP_EVENT.set()
        print("\n🛑 Cerrando...")
