# ia/scripts/list_concentrado_columns.py
import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = BASE_DIR / "data" / "raw"

df = pd.read_csv(RAW_DIR / "concentradohogar.csv", low_memory=False)

print(f"Total de columnas: {len(df.columns)}")
print("\nColumnas:")
for col in df.columns:
    print(col)