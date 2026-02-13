#!/usr/bin/env python3
# ============================================================
# 012-runner_clima.py
# ------------------------------------------------------------
# Runner único (un comando) que ejecuta en cadena:
#   1) 011-clima_open_meteo_horas_lugar.py   -> genera JSON hourly
#   2) 009-clima_graficas_48h.py             -> 2 gráficas (temp + precip)
#   3) 010-clima_graficas_extra_48h.py       -> pack extra (pprob, viento, etc.)
#
# Ventajas:
# - No tienes que ir ejecutando 3 scripts manualmente
# - Extrae automáticamente la ruta del JSON generado
# - Si por algún motivo no puede leer la ruta, usa fallback:
#   toma el JSON hourly más reciente en la carpeta de salida
#
# Uso:
#   py 012-runner_clima.py
#   py 012-runner_clima.py --city "Valencia" --countryCode ES
#   py 012-runner_clima.py --city "Lima" --countryCode PE
#
# Nota:
# - Los nombres de scripts están en CONFIG al inicio por si cambian.
# ============================================================

import os
import re
import sys
import glob
import argparse
import subprocess
from typing import Optional


# ============================================================
# CONFIG: nombres de tus scripts
# ============================================================
SCRIPT_FETCH = "011-clima_open_meteo_horas_lugar.py"
SCRIPT_GRAF_BASICO = "009-clima_graficas_48h.py"
SCRIPT_GRAF_EXTRA = "010-clima_graficas_extra_48h.py"

DEFAULT_OUTDIR = "salidas_clima"


# ============================================================
# Helpers
# ============================================================
def script_exists(path: str) -> bool:
    return os.path.exists(path) and os.path.isfile(path)


def find_latest_hourly_json(out_dir: str) -> Optional[str]:
    """
    Fallback: busca el JSON hourly más reciente.
    Preferimos patrón: *__hourly_*h.json
    """
    patterns = [
        os.path.join(out_dir, "*__hourly_*h.json"),
        os.path.join(out_dir, "*hourly*.json"),
    ]
    candidates = []
    for p in patterns:
        candidates.extend(glob.glob(p))

    if not candidates:
        return None

    candidates.sort(key=os.path.getmtime, reverse=True)
    return candidates[0]


def run_and_capture_json_path(cmd: list[str]) -> Optional[str]:
    """
    Ejecuta un comando y:
      - imprime la salida en vivo
      - intenta extraer la ruta del JSON desde la línea:
        "✅ JSON guardado en: <ruta>"
    """
    json_path = None
    regex = re.compile(r"JSON guardado en:\s*(.+)$")

    # Popen para streaming
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert proc.stdout is not None

    for line in proc.stdout:
        print(line, end="")  # ya viene con \n
        m = regex.search(line)
        if m:
            possible = m.group(1).strip()
            # por si viene entre comillas
            possible = possible.strip('"').strip("'")
            json_path = possible

    rc = proc.wait()
    if rc != 0:
        print(f"\n❌ El comando falló con código {rc}:")
        print(" ".join(cmd))
        return None

    return json_path


def run_simple(cmd: list[str]) -> bool:
    """
    Ejecuta un comando y muestra salida (normal).
    """
    result = subprocess.run(cmd)
    return result.returncode == 0


# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Runner único: fetch hourly + gráficas paso 8 + pack paso 9.")
    parser.add_argument("--city", default="Madrid", help="Ciudad (ej: Madrid, Valencia, Lima)")
    parser.add_argument("--countryCode", default=None, help="Filtro país ISO2 (ej: ES, PE). Opcional.")
    parser.add_argument("--hours", type=int, default=48, help="Horas de predicción (recomendado 48).")
    parser.add_argument("--timezone", default="auto", help="Timezone (auto recomendado).")
    parser.add_argument("--pick", type=int, default=0, help="Índice del resultado del geocoding (0 = primero).")
    parser.add_argument("--out", default=DEFAULT_OUTDIR, help="Carpeta de salida (default: salidas_clima).")
    parser.add_argument("--show", action="store_true", help="Muestra las gráficas (si tus scripts 009/010 lo soportan).")
    args = parser.parse_args()

    # Verificar scripts existen
    for s in [SCRIPT_FETCH, SCRIPT_GRAF_BASICO, SCRIPT_GRAF_EXTRA]:
        if not script_exists(s):
            print(f"❌ No encuentro el script: {s}")
            print("Asegúrate de estar en la carpeta correcta o cambia el nombre en CONFIG.")
            return

    os.makedirs(args.out, exist_ok=True)

    # 1) Ejecutar fetch hourly
    cmd_fetch = [
        sys.executable, SCRIPT_FETCH,
        "--city", args.city,
        "--hours", str(args.hours),
        "--timezone", args.timezone,
        "--pick", str(args.pick),
        "--out", args.out,
    ]
    if args.countryCode:
        cmd_fetch += ["--countryCode", args.countryCode]

    print("============================================================")
    print("1) Bajando forecast hourly (Open-Meteo)")
    print("============================================================")
    json_path = run_and_capture_json_path(cmd_fetch)

    # Fallback si no capturamos la ruta por stdout
    if not json_path or not os.path.exists(json_path):
        print("\n⚠️ No pude detectar la ruta del JSON en la salida.")
        print("➡️ Intentando fallback: buscar el último JSON hourly en la carpeta de salida...")
        json_path = find_latest_hourly_json(args.out)

    if not json_path or not os.path.exists(json_path):
        print("❌ No se encontró ningún JSON hourly para graficar.")
        print("Ejecuta primero el 011 manualmente para ver si está generando archivos.")
        return

    print("\n✅ JSON a usar para gráficas:")
    print("   ", json_path)

    # 2) Gráficas básicas (Paso 8)
    print("\n============================================================")
    print("2) Generando gráficas básicas (Paso 8): temp + precip")
    print("============================================================")
    cmd_graf1 = [sys.executable, SCRIPT_GRAF_BASICO, "--input", json_path]
    if args.show:
        cmd_graf1 += ["--show"]

    ok = run_simple(cmd_graf1)
    if not ok:
        print("❌ Falló la generación de gráficas básicas.")
        return

    # 3) Pack extra (Paso 9)
    print("\n============================================================")
    print("3) Generando pack extra (Paso 9)")
    print("============================================================")
    cmd_graf2 = [sys.executable, SCRIPT_GRAF_EXTRA, "--input", json_path]
    if args.show:
        cmd_graf2 += ["--show"]

    ok = run_simple(cmd_graf2)
    if not ok:
        print("❌ Falló la generación del pack extra.")
        return

    print("\n✅ Listo. Todo ejecutado en cadena.")
    print(f"📁 Revisa las salidas en: {args.out}")
    print("   - JSON hourly: (el que se imprimió arriba)")
    print("   - Gráficas: salidas_clima/graficas/ (según tus scripts 009/010)")


if __name__ == "__main__":
    main()
