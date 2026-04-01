import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
PROCESSED_DIR = BASE_DIR / "data" / "processed"

df = pd.read_csv(PROCESSED_DIR / "questy_benchmark_clean.csv", low_memory=False)

summary = (
    df.groupby("segmento_questy")
    .agg(
        hogares=("segmento_questy", "count"),
        ingreso_prom=("ing_cor", "mean"),
        gasto_prom=("gasto_mon", "mean"),
        ahorro_prom=("ahorro_hogar_aprox", "mean"),
        deuda_prom=("deudas", "mean"),
        ratio_gasto_ingreso_prom=("ratio_gasto_ingreso", "mean"),
        ratio_deuda_ingreso_prom=("ratio_deuda_ingreso", "mean"),
        transporte_prom=("transporte", "mean"),
        esparci_prom=("esparci", "mean"),
        educacion_prom=("educacion", "mean"),
        num_jovenes_prom=("num_jovenes", "mean"),
        edad_joven_prom=("edad_prom_joven", "mean"),
    )
    .reset_index()
)

percentiles = (
    df.groupby("segmento_questy")
    .agg(
        ingreso_p25=("ing_cor", lambda x: x.quantile(0.25)),
        ingreso_p50=("ing_cor", lambda x: x.quantile(0.50)),
        ingreso_p75=("ing_cor", lambda x: x.quantile(0.75)),
        ahorro_p25=("ahorro_hogar_aprox", lambda x: x.quantile(0.25)),
        ahorro_p50=("ahorro_hogar_aprox", lambda x: x.quantile(0.50)),
        ahorro_p75=("ahorro_hogar_aprox", lambda x: x.quantile(0.75)),
        deuda_p75=("deudas", lambda x: x.quantile(0.75)),
    )
    .reset_index()
)

segment_summary = summary.merge(percentiles, on="segmento_questy", how="left")

output = PROCESSED_DIR / "segment_summary.csv"
segment_summary.to_csv(output, index=False)

print(f"Archivo generado: {output}")
print(segment_summary.head())