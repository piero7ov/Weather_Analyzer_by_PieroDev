import os
import json
import glob
import argparse
from datetime import datetime

import matplotlib.pyplot as plt


# ============================================================
# 010-clima_graficas_extra_48h.py
# ------------------------------------------------------------
# - Lee el último JSON hourly (48h) guardado por tu script 008
# - Genera un pack de gráficas EXTRA (Paso 9), además de las
#   2 básicas del Paso 8 (temp y precip).
#
# Gráficas extra:
#   1) Probabilidad de precipitación (línea)
#   2) Viento: velocidad (línea)
#   3) Temperatura vs Sensación térmica (2 líneas)
#   4) Precipitación acumulada (línea)
#   5) Dirección del viento (°) (línea)
#
# Requisitos:
#   pip install matplotlib
# ============================================================

OUT_DIR = "salidas_clima"
GRAF_DIR = os.path.join(OUT_DIR, "graficas")


# ----------------------------
# Helpers de archivos / JSON
# ----------------------------
def cargar_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def encontrar_ultimo_hourly_json(out_dir: str) -> str | None:
    """
    Busca el JSON más reciente que parezca hourly.
    Preferimos patrón: *__hourly_*h.json
    """
    patrones = [
        os.path.join(out_dir, "*__hourly_*h.json"),
        os.path.join(out_dir, "*hourly*.json"),
        os.path.join(out_dir, "*.json"),
    ]

    candidatos = []
    for p in patrones:
        candidatos.extend(glob.glob(p))

    if not candidatos:
        return None

    candidatos.sort(key=os.path.getmtime, reverse=True)

    # Validamos que realmente tenga hourly/time
    for path in candidatos:
        try:
            data = cargar_json(path)
            hourly = data.get("hourly", {}) or {}
            if isinstance(hourly.get("time", None), list) and len(hourly["time"]) > 0:
                return path
        except Exception:
            continue

    return None


def safe_list(d: dict, key: str) -> list:
    v = d.get(key, [])
    return v if isinstance(v, list) else []


def parse_times(times: list[str]) -> list[datetime]:
    """
    Open-Meteo suele devolver strings tipo: 'YYYY-MM-DDTHH:MM'
    """
    out = []
    for t in times:
        try:
            out.append(datetime.fromisoformat(t))
        except Exception:
            # Si algo viene raro, metemos None (y luego lo filtramos)
            out.append(None)
    return out


def filtrar_none(times_dt, series: list[list]):
    """
    Filtra posiciones donde time es None (para que matplotlib no truene).
    """
    idx_ok = [i for i, dt in enumerate(times_dt) if dt is not None]
    times_ok = [times_dt[i] for i in idx_ok]
    series_ok = []
    for arr in series:
        series_ok.append([arr[i] if i < len(arr) else None for i in idx_ok])
    return times_ok, series_ok


# ----------------------------
# Helpers de gráficas
# ----------------------------
def guardar_fig(path: str, show: bool):
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    if show:
        plt.show()
    plt.close()


def plot_line(times, y, title: str, xlabel: str, ylabel: str, out_path: str, show: bool):
    plt.figure()
    plt.plot(times, y)
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.grid(True)
    plt.xticks(rotation=45, ha="right")
    guardar_fig(out_path, show)


def plot_two_lines(times, y1, y2, label1: str, label2: str, title: str, xlabel: str, ylabel: str, out_path: str, show: bool):
    plt.figure()
    plt.plot(times, y1, label=label1)
    plt.plot(times, y2, label=label2)
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.grid(True)
    plt.legend()
    plt.xticks(rotation=45, ha="right")
    guardar_fig(out_path, show)


# ----------------------------
# Main
# ----------------------------
def main():
    parser = argparse.ArgumentParser(description="Paso 9: pack de gráficas extra desde JSON hourly (48h).")
    parser.add_argument("--input", help="Ruta a un JSON específico. Si no, usa el último en salidas_clima.")
    parser.add_argument("--show", action="store_true", help="Muestra las gráficas en pantalla además de guardarlas.")
    args = parser.parse_args()

    os.makedirs(GRAF_DIR, exist_ok=True)

    json_path = args.input or encontrar_ultimo_hourly_json(OUT_DIR)
    if not json_path:
        print("❌ No encontré ningún JSON hourly en ./salidas_clima. Ejecuta primero tu 008.")
        return

    data = cargar_json(json_path)
    hourly = data.get("hourly", {}) or {}
    units = data.get("hourly_units", {}) or {}
    tz = data.get("timezone", "Europe/Madrid")

    times = safe_list(hourly, "time")
    if not times:
        print("❌ El JSON no tiene hourly.time")
        return

    # Variables que usaremos en este pack extra
    temp = safe_list(hourly, "temperature_2m")
    feel = safe_list(hourly, "apparent_temperature")
    pprob = safe_list(hourly, "precipitation_probability")
    prec = safe_list(hourly, "precipitation")
    wspd = safe_list(hourly, "wind_speed_10m")
    wdir = safe_list(hourly, "wind_direction_10m")

    # Unidades (fallbacks)
    u_temp = units.get("temperature_2m", "°C")
    u_feel = units.get("apparent_temperature", "°C")
    u_pprob = units.get("precipitation_probability", "%")
    u_prec = units.get("precipitation", "mm")
    u_wspd = units.get("wind_speed_10m", "km/h")

    # Parsear tiempos
    times_dt = parse_times(times)
    times_ok, series_ok = filtrar_none(times_dt, [temp, feel, pprob, prec, wspd, wdir])
    temp_ok, feel_ok, pprob_ok, prec_ok, wspd_ok, wdir_ok = series_ok

    base = os.path.basename(json_path).replace(".json", "")

    # ----------------------------
    # 1) Probabilidad de precipitación (línea)
    # ----------------------------
    if pprob_ok:
        out_pp = os.path.join(GRAF_DIR, f"{base}__pprob.png")
        plot_line(
            times_ok,
            pprob_ok,
            title=f"Probabilidad de precipitación (48h) — {tz}",
            xlabel="Hora",
            ylabel=f"Prob. precipitación ({u_pprob})",
            out_path=out_pp,
            show=args.show
        )
        print(f"✅ Guardada: {out_pp}")
    else:
        print("⚠️ No se encontró precipitation_probability en el JSON (saltando gráfica pprob).")

    # ----------------------------
    # 2) Viento: velocidad (línea)
    # ----------------------------
    if wspd_ok:
        out_ws = os.path.join(GRAF_DIR, f"{base}__wind_speed.png")
        plot_line(
            times_ok,
            wspd_ok,
            title=f"Velocidad del viento (48h) — {tz}",
            xlabel="Hora",
            ylabel=f"Viento ({u_wspd})",
            out_path=out_ws,
            show=args.show
        )
        print(f"✅ Guardada: {out_ws}")
    else:
        print("⚠️ No se encontró wind_speed_10m en el JSON (saltando gráfica viento).")

    # ----------------------------
    # 3) Temperatura vs Sensación térmica (2 líneas)
    # ----------------------------
    if temp_ok and feel_ok:
        out_tf = os.path.join(GRAF_DIR, f"{base}__temp_vs_feel.png")
        plot_two_lines(
            times_ok,
            temp_ok,
            feel_ok,
            label1="Temperatura",
            label2="Sensación",
            title=f"Temperatura vs Sensación térmica (48h) — {tz}",
            xlabel="Hora",
            ylabel=f"Temperatura ({u_temp})",
            out_path=out_tf,
            show=args.show
        )
        print(f"✅ Guardada: {out_tf}")
    else:
        print("⚠️ Falta temperature_2m o apparent_temperature (saltando temp vs feel).")

    # ----------------------------
    # 4) Precipitación acumulada (línea)
    # ----------------------------
    if prec_ok:
        # acumulada = suma progresiva
        acumulada = []
        total = 0.0
        for v in prec_ok:
            try:
                vv = float(v)
            except Exception:
                vv = 0.0
            total += vv
            acumulada.append(total)

        out_pc = os.path.join(GRAF_DIR, f"{base}__precip_acum.png")
        plot_line(
            times_ok,
            acumulada,
            title=f"Precipitación acumulada (48h) — {tz}",
            xlabel="Hora",
            ylabel=f"Precip acumulada ({u_prec})",
            out_path=out_pc,
            show=args.show
        )
        print(f"✅ Guardada: {out_pc}")
    else:
        print("⚠️ No se encontró precipitation en el JSON (saltando precipitación acumulada).")

    # ----------------------------
    # 5) Dirección del viento (°) (línea)
    # ----------------------------
    if wdir_ok:
        out_wd = os.path.join(GRAF_DIR, f"{base}__wind_dir_deg.png")
        plt.figure()
        plt.plot(times_ok, wdir_ok)
        plt.title(f"Dirección del viento (48h) — {tz}")
        plt.xlabel("Hora")
        plt.ylabel("Dirección (°)")
        plt.ylim(0, 360)  # rango típico
        plt.grid(True)
        plt.xticks(rotation=45, ha="right")
        guardar_fig(out_wd, args.show)
        print(f"✅ Guardada: {out_wd}")
    else:
        print("⚠️ No se encontró wind_direction_10m en el JSON (saltando dirección del viento).")

    print("\n✅ Listo. Pack extra del Paso 9 generado.")
    print(f"📄 JSON usado: {json_path}")
    print(f"📁 Carpeta de salida: {GRAF_DIR}")


if __name__ == "__main__":
    main()
