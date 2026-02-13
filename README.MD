# Weather Analyzer by PieroDev 🌦️ (Flask + Live Charts)

Dashboard web tipo **data analyzer** para consultar el clima de **hasta 4 ciudades**, con actualización automática, gráficas y vista de texto (resumen + tablas). Ideal como base para evolucionar hacia un sistema más completo (alertas, más métricas, fuentes oficiales, etc.).

---

## ✨ Características

* ✅ **Máximo 4 ciudades** guardadas (añadir/eliminar desde el panel)
* ✅ **Actualización automática** (por defecto cada 5 minutos)
* ✅ Botón **“Actualizar ahora”** (forzar update manual)
* ✅ **Gráficas** generadas con `matplotlib` (PNG)
* ✅ Vista **Texto** con:

  * clima actual (`current`)
  * resumen semanal (`stats`)
  * predicción 7 días (`daily`)
  * predicción **hourly 48h agrupada por día** (más legible)
  * reporte **Markdown** descargable
* ✅ Guardado de datos en JSON con **retención** (evita miles de archivos)
* ✅ UI estilo corporativo con **logo + favicon**

---

## 🗂️ Estructura de archivos generados

Al ejecutar el script se crea una carpeta:

```
clima_live/
  cities.json
  cities/
    <city_id>/
      latest.json
      status.json
      graphs/
        temp.png
        precip.png
        pprob.png
        wind_speed.png
        temp_vs_feel.png
        precip_acum.png
        wind_dir_deg.png
      snapshots/
        20260213_101530.json
        ...
```

* `latest.json`: último resultado (se **sobrescribe**)
* `snapshots/`: historial con retención configurable
* `graphs/`: gráficas (se **sobrescriben**, no crecen sin control)

---

## ✅ Requisitos

* Python 3.9+ (recomendado)
* Dependencias:

```bash
pip install flask requests matplotlib
```

---

## ▶️ Cómo ejecutar

1. Renombra el script a:

```
Wheather_Analyzer_by_PieroDev.py
```

2. Ejecuta:

```bash
python Wheather_Analyzer_by_PieroDev.py
```

3. Abre el dashboard:

```
http://127.0.0.1:5000
```

---

## 🧭 Cómo usar el dashboard

### Añadir ciudad

En **Gestión → Añadir ciudad**:

* Ciudad: `Valencia` o `Lima`
* `countryCode` (opcional, ISO2): `ES`, `PE`, etc.

Si el geocoding devuelve varias coincidencias, verás una pantalla para **elegir** la correcta.

### Eliminar ciudad

Botón 🗑️ en la tarjeta de la ciudad.

### Actualizar manualmente

Botón **🔄 Actualizar ahora** (ideal después de añadir una ciudad).

---

## ⚙️ Configuración (desde la UI)

En el panel **Gestión** puedes cambiar:

* `interval_seconds`: cada cuántos segundos se actualiza (mínimo 30)
* `snapshot_retention`: cuántos snapshots JSON se conservan por ciudad

---

## 🧪 Notas importantes

* Este proyecto consume una **API** de clima (Open-Meteo) y genera datos/plots localmente.
* La etiqueta “oficial” aplica a **AEMET en España**, pero esta versión **no consume AEMET todavía**.
* Si quieres integrar AEMET, el siguiente paso natural sería:

  * Añadir un “provider” alternativo (Open-Meteo / AEMET)
  * Conmutar fuente desde settings (sin romper el dashboard)

---

## 🛠️ Personalización rápida

### Logo corporativo

El script ya incluye un `BRAND_LOGO_URL` en la configuración.
Puedes reemplazarlo por tu propio recurso o servirlo localmente (recomendado para producción).

### Ajustar el número máximo de ciudades

En el script:

```python
MAX_CITIES = 4
```
---

## 📄 Licencia

Elige la que prefieras para tu repo (MIT suele ser buena para proyectos personales).

---

## 👤 Autor

**PieroDev** — Weather Analyzer Dashboard (Flask + Matplotlib)
