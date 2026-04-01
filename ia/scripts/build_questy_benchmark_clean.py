import pandas as pd
import numpy as np
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"

PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

hogar_keys = ["folioviv", "foliohog"]
persona_keys = ["folioviv", "foliohog", "numren"]

# -------------------------
# Cargar datos
# -------------------------
concentrado = pd.read_csv(RAW_DIR / "concentradohogar.csv", low_memory=False)
poblacion = pd.read_csv(RAW_DIR / "poblacion.csv", low_memory=False)
ingresos = pd.read_csv(RAW_DIR / "ingresos.csv", low_memory=False)

# -------------------------
# Filtrar jóvenes 18-29
# -------------------------
jovenes = poblacion[(poblacion["edad"] >= 18) & (poblacion["edad"] <= 29)].copy()

jovenes_hogar = (
    jovenes.groupby(hogar_keys)
    .agg(
        num_jovenes=("numren", "count"),
        edad_prom_joven=("edad", "mean"),
        edad_min_joven=("edad", "min"),
        edad_max_joven=("edad", "max"),
        hombres_jovenes=("sexo", lambda s: (s == 1).sum()),
        mujeres_jovenes=("sexo", lambda s: (s == 2).sum()),
    )
    .reset_index()
)

# -------------------------
# Ingresos de jóvenes
# -------------------------
ingresos["ing_tri"] = pd.to_numeric(ingresos["ing_tri"], errors="coerce").fillna(0)

ingresos_jovenes = ingresos.merge(
    jovenes[persona_keys],
    on=persona_keys,
    how="inner"
)

ingreso_joven_hogar = (
    ingresos_jovenes.groupby(hogar_keys)
    .agg(
        ingreso_tri_jovenes=("ing_tri", "sum"),
        perceptores_jovenes=("numren", "nunique"),
    )
    .reset_index()
)

# -------------------------
# Selección de columnas útiles
# -------------------------
cols_keep = [
    "folioviv", "foliohog",
    "factor", "tam_loc", "est_socio", "clase_hog",
    "sexo_jefe", "edad_jefe", "educa_jefe",
    "tot_integ", "hombres", "mujeres", "mayores", "menores", "ocupados",
    "percep_ing", "perc_ocupa",
    "ing_cor", "ingtrab", "trabajo", "sueldos", "negocio", "rentas",
    "transfer", "becas", "remesas", "otros_ing",
    "gasto_mon", "alimentos", "ali_dentro", "ali_fuera",
    "vesti_calz", "vivienda", "agua", "energia", "salud",
    "transporte", "combus", "comunica", "educa_espa",
    "educacion", "esparci", "personales", "otros_gas",
    "percep_tot", "deposito", "prest_terc", "pago_tarje",
    "deudas", "balance", "otras_erog", "smg"
]

base = concentrado[cols_keep].copy()

# -------------------------
# Unir jóvenes + base
# -------------------------
benchmark = base.merge(jovenes_hogar, on=hogar_keys, how="inner")
benchmark = benchmark.merge(ingreso_joven_hogar, on=hogar_keys, how="left")

benchmark["ingreso_tri_jovenes"] = benchmark["ingreso_tri_jovenes"].fillna(0)
benchmark["perceptores_jovenes"] = benchmark["perceptores_jovenes"].fillna(0)

# -------------------------
# Variables derivadas Questy
# -------------------------

# ahorro simple del hogar
benchmark["ahorro_hogar_aprox"] = benchmark["ing_cor"] - benchmark["gasto_mon"]

# qué proporción del ingreso corriente se va en gasto monetario
benchmark["ratio_gasto_ingreso"] = np.where(
    benchmark["ing_cor"] > 0,
    benchmark["gasto_mon"] / benchmark["ing_cor"],
    np.nan
)

# qué tanto pesan las deudas contra el ingreso
benchmark["ratio_deuda_ingreso"] = np.where(
    benchmark["ing_cor"] > 0,
    benchmark["deudas"] / benchmark["ing_cor"],
    np.nan
)

# peso del transporte
benchmark["ratio_transporte_ingreso"] = np.where(
    benchmark["ing_cor"] > 0,
    benchmark["transporte"] / benchmark["ing_cor"],
    np.nan
)

# peso del entretenimiento
benchmark["ratio_esparci_ingreso"] = np.where(
    benchmark["ing_cor"] > 0,
    benchmark["esparci"] / benchmark["ing_cor"],
    np.nan
)

# peso de educación
benchmark["ratio_educacion_ingreso"] = np.where(
    benchmark["ing_cor"] > 0,
    benchmark["educacion"] / benchmark["ing_cor"],
    np.nan
)

# dependencia de transferencias
benchmark["ratio_transfer_ingreso"] = np.where(
    benchmark["ing_cor"] > 0,
    benchmark["transfer"] / benchmark["ing_cor"],
    np.nan
)

# ingreso promedio por integrante
benchmark["ingreso_por_integrante"] = np.where(
    benchmark["tot_integ"] > 0,
    benchmark["ing_cor"] / benchmark["tot_integ"],
    np.nan
)

# gasto promedio por integrante
benchmark["gasto_por_integrante"] = np.where(
    benchmark["tot_integ"] > 0,
    benchmark["gasto_mon"] / benchmark["tot_integ"],
    np.nan
)

# si hay jóvenes perceptores
benchmark["hogar_con_joven_perceptor"] = (benchmark["perceptores_jovenes"] > 0).astype(int)

# presión financiera simple
benchmark["presion_financiera"] = np.select(
    [
        benchmark["ratio_gasto_ingreso"] < 0.8,
        benchmark["ratio_gasto_ingreso"].between(0.8, 1.0, inclusive="left"),
        benchmark["ratio_gasto_ingreso"] >= 1.0
    ],
    [
        "baja",
        "media",
        "alta"
    ],
    default="sin_dato"
)

# nivel simple de ingreso
benchmark["nivel_ingreso"] = pd.qcut(
    benchmark["ing_cor"],
    q=4,
    labels=["bajo", "medio_bajo", "medio_alto", "alto"],
    duplicates="drop"
)

# segmento útil para Questy
benchmark["segmento_questy"] = (
    "jovenes_" +
    benchmark["nivel_ingreso"].astype(str) + "_" +
    benchmark["presion_financiera"].astype(str)
)

# -------------------------
# Guardar
# -------------------------
output_path = PROCESSED_DIR / "questy_benchmark_clean.csv"
benchmark.to_csv(output_path, index=False)

print(f"Archivo generado: {output_path}")
print(f"Filas: {benchmark.shape[0]}")
print(f"Columnas: {benchmark.shape[1]}")

print("\nColumnas derivadas clave:")
derived_cols = [
    "num_jovenes",
    "edad_prom_joven",
    "ingreso_tri_jovenes",
    "perceptores_jovenes",
    "ahorro_hogar_aprox",
    "ratio_gasto_ingreso",
    "ratio_deuda_ingreso",
    "ratio_transporte_ingreso",
    "ratio_esparci_ingreso",
    "ratio_educacion_ingreso",
    "hogar_con_joven_perceptor",
    "presion_financiera",
    "nivel_ingreso",
    "segmento_questy"
]
print(derived_cols)

print("\nPrimeras 5 filas:")
print(benchmark[derived_cols].head())