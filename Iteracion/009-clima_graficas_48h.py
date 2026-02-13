import os
import json
import glob
import argparse
from datetime import datetime

import matplotlib.pyplot as plt


# ============================================================
# 009-clima_graficas_48h.py
# ------------------------------------------------------------
# - Lee el último JSON hourly (48h) guardado por tu script 008
# - Genera 2 gráficas:
#     1) Temperatura por hora (línea)
#     2) Precipitación por hora (barras)
# - Guarda ambas como PNG
#
# Requisitos:
#   pip install matplotlib
# ============================================================

OUT_DIR = "salidas_clima"
GRAF_DIR = os.path.join(OUT_DIR, "graficas")


def cargar_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def encontrar_ultimo_hourly_json(out_dir: str) -> str | None:
    """
    Busca el JSON más reciente que parezca 'hourly'.
    Preferimos archivos tipo: *__hourly_*h.json
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

    # Ordena por fecha de modificación (más reciente primero)
    candidatos.sort(key=os.path.getmtime, reverse=True)

    # Si cae en *.json general, filtramos por presencia de hourly/time
    for path in candidatos:
        try:
            data = cargar_json(path)
            hourly = data.get("hourly", {}) or {}
            if "time" in hourly and len(hourly.get("time", [])) > 0:
                return path
        except Exception:
            continue

    return None


def parse_times(times: list[str]) -> list[datetime]:
    """
    Open-Meteo suele devolver: 'YYYY-MM-DDTHH:MM'
    """
    out = []
    for t in times:
        try:
            out.append(datetime.fromisoformat(t))
        except Exception:
            # fallback por si viene raro
            out.append(None)
    return out


def safe_list(d: dict, key: str) -> list:
    v = d.get(key, [])
    return v if isinstance(v, list) else []


def grafica_temperatura(times_dt, temps, unidad_temp, titulo, out_path, show=False):
    plt.figure()
    plt.plot(times_dt, temps)
    plt.title(titulo)
    plt.xlabel("Hora")
    plt.ylabel(f"Temperatura ({unidad_temp})")
    plt.grid(True)
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    if show:
        plt.show()
    plt.close()


def grafica_precipitacion(times_dt, precs, unidad_prec, titulo, out_path, show=False):
    plt.figure()
    plt.bar(times_dt, precs)
    plt.title(titulo)
    plt.xlabel("Hora")
    plt.ylabel(f"Precipitación ({unidad_prec})")
    plt.grid(True)
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    if show:
        plt.show()
    plt.close()


def main():
    parser = argparse.ArgumentParser(description="Genera 2 gráficas (temp + precip) desde JSON hourly (48h).")
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

    times = safe_list(hourly, "time")
    temps = safe_list(hourly, "temperature_2m")
    precs = safe_list(hourly, "precipitation")

    if not times or not temps or not precs:
        print("❌ El JSON no trae hourly/time o faltan variables (temperature_2m / precipitation).")
        return

    times_dt = parse_times(times)

    # Unidades
    u_temp = units.get("temperature_2m", "°C")
    u_prec = units.get("precipitation", "mm")

    # Base para nombres
    base = os.path.basename(json_path).replace(".json", "")
    out_temp = os.path.join(GRAF_DIR, f"{base}__temp.png")
    out_prec = os.path.join(GRAF_DIR, f"{base}__precip.png")

    # Títulos con ciudad si viene en el JSON
    tz = data.get("timezone", "Europe/Madrid")
    titulo_temp = f"Temperatura por hora (48h) — {tz}"
    titulo_prec = f"Precipitación por hora (48h) — {tz}"

    grafica_temperatura(times_dt, temps, u_temp, titulo_temp, out_temp, show=args.show)
    grafica_precipitacion(times_dt, precs, u_prec, titulo_prec, out_prec, show=args.show)

    print(f"✅ JSON usado: {json_path}")
    print(f"✅ Gráfica temperatura: {out_temp}")
    print(f"✅ Gráfica precipitación: {out_prec}")


if __name__ == "__main__":
    main()
