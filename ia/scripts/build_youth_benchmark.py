import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"

PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# -------------------------
# Cargar archivos
# -------------------------
concentrado = pd.read_csv(RAW_DIR / "concentradohogar.csv", low_memory=False)
poblacion = pd.read_csv(RAW_DIR / "poblacion.csv", low_memory=False)
ingresos = pd.read_csv(RAW_DIR / "ingresos.csv", low_memory=False)
gastos = pd.read_csv(RAW_DIR / "gastoshogar.csv", low_memory=False)

# -------------------------
# Llaves
# -------------------------
hogar_keys = ["folioviv", "foliohog"]
persona_keys = ["folioviv", "foliohog", "numren"]

# -------------------------
# 1) Filtrar jóvenes 18-29
# -------------------------
jovenes = poblacion[(poblacion["edad"] >= 18) & (poblacion["edad"] <= 29)].copy()

# Resumen de jóvenes por hogar
jovenes_hogar = (
    jovenes.groupby(hogar_keys)
    .agg(
        num_jovenes=("numren", "count"),
        edad_prom_joven=("edad", "mean"),
        edad_min_joven=("edad", "min"),
        edad_max_joven=("edad", "max"),
    )
    .reset_index()
)

# -------------------------
# 2) Ingreso de jóvenes
# -------------------------
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
# 3) Gasto del hogar
# -------------------------
# Convertir a numérico por si viene como texto
gastos["gasto"] = pd.to_numeric(gastos["gasto"], errors="coerce")
gastos["costo"] = pd.to_numeric(gastos["costo"], errors="coerce")

gasto_hogar = (
    gastos.groupby(hogar_keys)
    .agg(
        registros_gasto=("clave", "count"),
        gasto_reportado_sum=("gasto", "sum"),
        costo_reportado_sum=("costo", "sum"),
    )
    .reset_index()
)

# -------------------------
# 4) Unir todo al concentrado
# -------------------------
benchmark = concentrado.merge(jovenes_hogar, on=hogar_keys, how="inner")
benchmark = benchmark.merge(ingreso_joven_hogar, on=hogar_keys, how="left")
benchmark = benchmark.merge(gasto_hogar, on=hogar_keys, how="left")

# -------------------------
# 5) Variables derivadas
# -------------------------
benchmark["ingreso_tri_jovenes"] = benchmark["ingreso_tri_jovenes"].fillna(0)
benchmark["perceptores_jovenes"] = benchmark["perceptores_jovenes"].fillna(0)
benchmark["gasto_reportado_sum"] = benchmark["gasto_reportado_sum"].fillna(0)
benchmark["costo_reportado_sum"] = benchmark["costo_reportado_sum"].fillna(0)

# ahorro estimado simple usando lo agregado desde gasto
benchmark["ahorro_estimado_joven_hogar"] = (
    benchmark["ingreso_tri_jovenes"] - benchmark["gasto_reportado_sum"]
)

# presión financiera simple
benchmark["presion_gasto_vs_ingreso_joven"] = benchmark.apply(
    lambda row: row["gasto_reportado_sum"] / row["ingreso_tri_jovenes"]
    if row["ingreso_tri_jovenes"] > 0 else None,
    axis=1
)

# bandera de hogar con jóvenes perceptores
benchmark["hogar_con_joven_perceptor"] = benchmark["perceptores_jovenes"].apply(
    lambda x: 1 if x > 0 else 0
)

# -------------------------
# Guardar
# -------------------------
output_path = PROCESSED_DIR / "benchmark_jovenes_hogar.csv"
benchmark.to_csv(output_path, index=False)

print(f"Archivo generado: {output_path}")
print(f"Filas: {benchmark.shape[0]}")
print(f"Columnas: {benchmark.shape[1]}")
print("\nColumnas nuevas principales:")
print([
    "num_jovenes",
    "edad_prom_joven",
    "ingreso_tri_jovenes",
    "perceptores_jovenes",
    "gasto_reportado_sum",
    "ahorro_estimado_joven_hogar",
    "presion_gasto_vs_ingreso_joven",
    "hogar_con_joven_perceptor",
])
print("\nPrimeras 5 filas:")
print(benchmark.head())