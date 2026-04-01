import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = BASE_DIR / "data" / "raw"

files = {
    "concentradohogar": RAW_DIR / "concentradohogar.csv",
    "gastoshogar": RAW_DIR / "gastoshogar.csv",
    "ingresos": RAW_DIR / "ingresos.csv",
    "poblacion": RAW_DIR / "poblacion.csv",
}

for name, path in files.items():
    print("\n" + "=" * 80)
    print(f"Archivo: {name}")
    print(f"Ruta: {path}")

    try:
        df = pd.read_csv(path, low_memory=False)
        print(f"Filas: {df.shape[0]}")
        print(f"Columnas: {df.shape[1]}")
        print("\nPrimeras 20 columnas:")
        print(df.columns[:20].tolist())

        print("\nTipos de datos:")
        print(df.dtypes.head(20))

        print("\nPrimeras 3 filas:")
        print(df.head(3))

    except Exception as e:
        print(f"Error al leer {name}: {e}")