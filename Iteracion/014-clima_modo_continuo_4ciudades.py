#!/usr/bin/env python3
# ============================================================
# 014-clima_modo_continuo_4ciudades.py
# ------------------------------------------------------------
# Modo continuo (sin depender de otros scripts):
#   - Máximo 4 ciudades en config (add/remove/list)
#   - Actualiza cada X segundos mientras esté encendido
#   - Descarga hourly (por defecto 48h) con Open-Meteo
#   - Guarda:
#       * latest.json (sobrescribe)
#       * snapshots/*.json (limitado por retención)
#       * graphs/*.png (sobrescribe: no se acumulan)
#
# Requisitos:
#   pip install requests matplotlib
#
# Uso rápido:
#   py 014-clima_modo_continuo_4ciudades.py --add "Madrid" --countryCode ES
#   py 014-clima_modo_continuo_4ciudades.py --add "Valencia" --countryCode ES
#   py 014-clima_modo_continuo_4ciudades.py --add "Lima" --countryCode PE
#   py 014-clima_modo_continuo_4ciudades.py --list
#   py 014-clima_modo_continuo_4ciudades.py --run
#
# Parar:
#   Ctrl + C
# ============================================================

import os
import re
import json
import time
import glob
import argparse
from datetime import datetime
from typing import Optional, List, Dict, Any

import requests

# Matplotlib sin UI (ideal para modo continuo)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ============================================================
# CONFIG
# ============================================================

MAX_CITIES = 4

DEFAULT_DATA_DIR = "clima_live"
DEFAULT_CONFIG_PATH = os.path.join(DEFAULT_DATA_DIR, "cities.json")

DEFAULT_INTERVAL_SECONDS = 300          # 5 min recomendado
DEFAULT_FORECAST_HOURS = 48             # 24 o 48
DEFAULT_TIMEZONE = "auto"               # auto recomendado
DEFAULT_SNAPSHOT_RETENTION = 24         # 24 snapshots (p.ej. 2h si interval=5min)

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

def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def slugify(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9_-]+", "_", text)
    return text.strip("_") or "city"


def safe_float(x, default: float = 0.0) -> float:
    try:
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


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


# ============================================================
# Config file (cities.json)
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


def load_config(path: str) -> Dict[str, Any]:
    ensure_dir(os.path.dirname(path))
    if not os.path.exists(path):
        cfg = default_config()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return cfg

    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    if "settings" not in cfg:
        cfg["settings"] = default_config()["settings"]
    if "cities" not in cfg:
        cfg["cities"] = []

    return cfg


def save_config(path: str, cfg: Dict[str, Any]):
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def list_cities(cfg: Dict[str, Any]):
    cities = cfg.get("cities", []) or []
    if not cities:
        print("📭 No hay ciudades guardadas todavía.")
        return

    print("\n📌 Ciudades guardadas (máx 4):")
    for i, c in enumerate(cities):
        print(f"  [{i}] id={c.get('id')} | {c.get('label')} | {c.get('lat')},{c.get('lon')} | tz={c.get('timezone','auto')}")
    print("")


def remove_city(cfg: Dict[str, Any], target: str) -> bool:
    """
    target puede ser:
      - índice ("0", "1"...)
      - id exacto
    """
    cities = cfg.get("cities", []) or []
    if not cities:
        return False

    # índice
    if target.isdigit():
        idx = int(target)
        if 0 <= idx < len(cities):
            removed = cities.pop(idx)
            cfg["cities"] = cities
            print(f"🗑️ Eliminada: {removed.get('label')} (idx {idx})")
            return True
        return False

    # id
    for i, c in enumerate(cities):
        if c.get("id") == target:
            removed = cities.pop(i)
            cfg["cities"] = cities
            print(f"🗑️ Eliminada: {removed.get('label')} (id {target})")
            return True

    return False


# ============================================================
# Open-Meteo
# ============================================================

def get_json(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()


def geocoding(ciudad: str, country_code: Optional[str], count: int = 5) -> List[Dict[str, Any]]:
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
# Estructura de carpetas por ciudad
# ============================================================

def city_folder(data_dir: str, city_id: str) -> str:
    return os.path.join(data_dir, "cities", city_id)


def city_latest_path(data_dir: str, city_id: str) -> str:
    return os.path.join(city_folder(data_dir, city_id), "latest.json")


def city_snapshots_dir(data_dir: str, city_id: str) -> str:
    return os.path.join(city_folder(data_dir, city_id), "snapshots")


def city_graphs_dir(data_dir: str, city_id: str) -> str:
    return os.path.join(city_folder(data_dir, city_id), "graphs")


def city_status_path(data_dir: str, city_id: str) -> str:
    return os.path.join(city_folder(data_dir, city_id), "status.json")


# ============================================================
# Guardado + retención
# ============================================================

def write_status(data_dir: str, city_id: str, ok: bool, message: str):
    ensure_dir(city_folder(data_dir, city_id))
    payload = {
        "ok": ok,
        "message": message,
        "updated_at": iso_now(),
    }
    with open(city_status_path(data_dir, city_id), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def save_latest_and_snapshot(data_dir: str, city_id: str, data: dict, retention: int):
    ensure_dir(city_folder(data_dir, city_id))
    ensure_dir(city_snapshots_dir(data_dir, city_id))

    # latest.json (sobrescribe)
    with open(city_latest_path(data_dir, city_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # snapshot con timestamp
    snap_path = os.path.join(city_snapshots_dir(data_dir, city_id), f"{now_ts()}.json")
    with open(snap_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # retención: borra lo viejo
    snaps = glob.glob(os.path.join(city_snapshots_dir(data_dir, city_id), "*.json"))
    snaps.sort(key=os.path.getmtime, reverse=True)
    for old in snaps[retention:]:
        try:
            os.remove(old)
        except Exception:
            pass


# ============================================================
# Gráficas (sobrescriben, no se acumulan)
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


def generate_graphs(data_dir: str, city: Dict[str, Any], json_data: dict):
    """
    Genera todas las gráficas importantes (Paso 8 + Paso 9),
    pero con nombres FIJOS => se sobrescriben.
    """
    city_id = city["id"]
    label = city["label"]

    gdir = city_graphs_dir(data_dir, city_id)
    ensure_dir(gdir)

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

    u_temp = units.get("temperature_2m", "°C")
    u_feel = units.get("apparent_temperature", "°C")
    u_prec = units.get("precipitation", "mm")
    u_pp = units.get("precipitation_probability", "%")
    u_ws = units.get("wind_speed_10m", "km/h")

    times_dt = parse_times(times)
    times_ok, series_ok = filter_none_times(times_dt, [temp, feel, prec, pprob, wspd, wdir])
    temp_ok, feel_ok, prec_ok, pprob_ok, wspd_ok, wdir_ok = series_ok

    # Paso 8
    plot_line(
        times_ok, temp_ok,
        title=f"Temperatura (48h) — {label} — {tz}",
        xlabel="Hora",
        ylabel=f"Temperatura ({u_temp})",
        out_path=os.path.join(gdir, "temp.png")
    )

    plot_bar(
        times_ok, prec_ok,
        title=f"Precipitación por hora (48h) — {label} — {tz}",
        xlabel="Hora",
        ylabel=f"Precipitación ({u_prec})",
        out_path=os.path.join(gdir, "precip.png")
    )

    # Paso 9 extra
    if pprob_ok:
        plot_line(
            times_ok, pprob_ok,
            title=f"Prob. precipitación (48h) — {label} — {tz}",
            xlabel="Hora",
            ylabel=f"Probabilidad ({u_pp})",
            out_path=os.path.join(gdir, "pprob.png")
        )

    if wspd_ok:
        plot_line(
            times_ok, wspd_ok,
            title=f"Viento (48h) — {label} — {tz}",
            xlabel="Hora",
            ylabel=f"Velocidad ({u_ws})",
            out_path=os.path.join(gdir, "wind_speed.png")
        )

    if temp_ok and feel_ok:
        plot_two_lines(
            times_ok, temp_ok, feel_ok,
            label1="Temperatura",
            label2="Sensación",
            title=f"Temp vs Sensación (48h) — {label} — {tz}",
            xlabel="Hora",
            ylabel=f"Temperatura ({u_temp})",
            out_path=os.path.join(gdir, "temp_vs_feel.png")
        )

    # Precip acumulada
    acumulada = []
    total = 0.0
    for v in prec_ok:
        total += safe_float(v, 0.0)
        acumulada.append(total)

    plot_line(
        times_ok, acumulada,
        title=f"Precipitación acumulada (48h) — {label} — {tz}",
        xlabel="Hora",
        ylabel=f"Acumulada ({u_prec})",
        out_path=os.path.join(gdir, "precip_acum.png")
    )

    # Dirección viento
    if wdir_ok:
        plt.figure()
        plt.plot(times_ok, wdir_ok)
        plt.title(f"Dirección del viento (48h) — {label} — {tz}")
        plt.xlabel("Hora")
        plt.ylabel("Dirección (°)")
        plt.ylim(0, 360)
        plt.grid(True)
        plt.xticks(rotation=45, ha="right")
        save_fig(os.path.join(gdir, "wind_dir_deg.png"))


# ============================================================
# Operaciones: add city / update cities
# ============================================================

def add_city(cfg: Dict[str, Any], city_query: str, country_code: Optional[str], pick: int, timezone: str):
    cities = cfg.get("cities", []) or []
    if len(cities) >= MAX_CITIES:
        raise RuntimeError(f"Ya tienes {MAX_CITIES} ciudades. Elimina una antes de agregar otra.")

    results = geocoding(city_query, country_code, count=5)

    print("\nCandidatos encontrados:")
    for i, r in enumerate(results):
        name = r.get("name", "")
        admin1 = r.get("admin1", "")
        country = r.get("country", "")
        tz = r.get("timezone", "")
        lat = r.get("latitude", "")
        lon = r.get("longitude", "")
        print(f"  [{i}] {name} · {admin1} · {country} | {lat},{lon} | tz={tz}")

    if pick < 0 or pick >= len(results):
        raise RuntimeError(f"--pick fuera de rango. Debe ser 0..{len(results)-1}")

    loc = results[pick]
    lat = loc["latitude"]
    lon = loc["longitude"]

    label = f"{loc.get('name','')} · {loc.get('admin1','')} · {loc.get('country','')}".strip(" ·")
    cid = slugify(f"{loc.get('name','')}_{loc.get('admin1','')}_{loc.get('country','')}")

    # Evitar duplicados por id
    for c in cities:
        if c.get("id") == cid:
            raise RuntimeError("Esa ciudad ya está guardada (id duplicado).")

    cities.append({
        "id": cid,
        "query": city_query,
        "countryCode": (country_code.upper() if country_code else None),
        "pick": pick,
        "lat": lat,
        "lon": lon,
        "label": label,
        "timezone": timezone,
    })

    cfg["cities"] = cities
    print(f"\n✅ Agregada: {label} (id={cid})")


def update_city(data_dir: str, settings: Dict[str, Any], city: Dict[str, Any]):
    cid = city["id"]
    label = city["label"]

    hours = int(settings.get("forecast_hours", DEFAULT_FORECAST_HOURS))
    tz = city.get("timezone") or settings.get("timezone", DEFAULT_TIMEZONE)
    retention = int(settings.get("snapshot_retention", DEFAULT_SNAPSHOT_RETENTION))

    try:
        data = forecast_hourly(city["lat"], city["lon"], tz, hours)
        save_latest_and_snapshot(data_dir, cid, data, retention=retention)
        generate_graphs(data_dir, city, data)
        write_status(data_dir, cid, ok=True, message="OK")
        print(f"✅ {label} actualizado ({iso_now()})")
    except Exception as e:
        write_status(data_dir, cid, ok=False, message=str(e))
        print(f"❌ {label} falló: {e}")


def run_loop(cfg_path: str, data_dir: str, once: bool, interval_override: Optional[int]):
    cfg = load_config(cfg_path)
    settings = cfg.get("settings", {}) or {}
    cities = cfg.get("cities", []) or []

    if not cities:
        print("📭 No hay ciudades en la config. Usa --add para agregar (máx 4).")
        return

    interval = interval_override if interval_override is not None else int(settings.get("interval_seconds", DEFAULT_INTERVAL_SECONDS))

    print("\n============================================================")
    print("🚀 Modo continuo iniciado")
    print(f"📁 data_dir: {data_dir}")
    print(f"⏱️  intervalo: {interval} segundos")
    print(f"🏙️  ciudades: {len(cities)} (máx {MAX_CITIES})")
    print("Parar con Ctrl+C")
    print("============================================================\n")

    try:
        while True:
            # recargar config en cada ciclo para que puedas editar cities.json en caliente
            cfg = load_config(cfg_path)
            settings = cfg.get("settings", {}) or {}
            cities = cfg.get("cities", []) or []

            if not cities:
                print("📭 Te quedaste sin ciudades. Agrega una con --add o edita cities.json.")
            else:
                for city in cities:
                    update_city(data_dir, settings, city)

            if once:
                print("\n✅ Ejecución única terminada (--once).")
                break

            print(f"\n⏳ Durmiendo {interval} segundos...\n")
            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n🛑 Detenido por el usuario (Ctrl+C).")


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Modo continuo Open-Meteo (máx 4 ciudades) + retención + gráficas.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Ruta al cities.json")
    parser.add_argument("--data", default=DEFAULT_DATA_DIR, help="Carpeta donde se guardan latest/snapshots/graphs")
    parser.add_argument("--list", action="store_true", help="Lista ciudades guardadas")

    parser.add_argument("--add", metavar="CITY", help='Agrega ciudad (ej: "Valencia" o "Lima")')
    parser.add_argument("--countryCode", default=None, help="Filtro país ISO2 (ej: ES, PE). Opcional.")
    parser.add_argument("--pick", type=int, default=0, help="Qué candidato usar del geocoding (0 = primero).")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE, help='Timezone guardado (recomendado: "auto").')

    parser.add_argument("--remove", metavar="ID_OR_INDEX", help="Elimina ciudad por id o por índice (ej: 0)")

    parser.add_argument("--run", action="store_true", help="Inicia el loop continuo")
    parser.add_argument("--once", action="store_true", help="Ejecuta una actualización y sale (para probar)")
    parser.add_argument("--interval", type=int, default=None, help="Override del intervalo en segundos (ej: 300)")

    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.list:
        list_cities(cfg)
        return

    if args.remove:
        ok = remove_city(cfg, args.remove.strip())
        if not ok:
            print("❌ No se pudo eliminar (id/índice no encontrado). Usa --list para ver opciones.")
            return
        save_config(args.config, cfg)
        return

    if args.add:
        add_city(cfg, args.add.strip(), args.countryCode, args.pick, args.timezone)
        save_config(args.config, cfg)
        return

    # Si pides run/once, arrancamos loop
    if args.run or args.once:
        run_loop(args.config, args.data, once=args.once, interval_override=args.interval)
        return

    # Si no pasa nada, mostramos ayuda rápida
    print("\nNada que hacer. Prueba:")
    print("  py 014-clima_modo_continuo_4ciudades.py --add \"Madrid\" --countryCode ES")
    print("  py 014-clima_modo_continuo_4ciudades.py --list")
    print("  py 014-clima_modo_continuo_4ciudades.py --run\n")


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        print("❌ Error de red/HTTP:", e)
    except Exception as e:
        print("❌ Error:", e)
