# Entregable ED — Semana 1

Separación público/privado, hashing de contraseñas y cifrado en reposo.

El documento a entregar es **`reporte_semanaED1.pdf`**.

---

## ⚠️ Antes de arrancar la app: hay que migrar

`models.py` ahora cifra `usuarios.nombre`, `usuarios.correo`, `usuarios.alias`,
`movimientos.nota` y `gastos.descripcion`, y el login busca por la columna nueva
`usuarios.correo_bi`. **Si arrancas la app sin migrar, nadie podrá iniciar
sesión**, porque esa columna no existe todavía en tu base.

```bash
cd ~/questcash_web

# 1) Instalar la dependencia nueva
pip install -r requirements.txt          # agrega `cryptography`

# 2) Generar las dos claves (una sola vez en la vida del proyecto)
python -c "import os,base64;print('DATA_ENC_KEY='+base64.urlsafe_b64encode(os.urandom(32)).decode())"
python -c "import os,base64;print('BLIND_INDEX_KEY='+base64.urlsafe_b64encode(os.urandom(32)).decode())"

# 3) Pegarlas en .env  (ver .env.example como plantilla)
#    y también en el panel Environment de Render.

# 4) Migrar la base (respalda sola antes de tocar nada)
source .env
python migrar_cifrado.py --dry-run       # primero en seco, para ver qué hará
python migrar_cifrado.py                 # ahora sí

# 5) Arrancar y comprobar que el login sigue funcionando
python app.py
```

> **Si se pierde `DATA_ENC_KEY`, los datos cifrados no se recuperan.**
> **Si se cambia `BLIND_INDEX_KEY` sin recalcular `correo_bi`, nadie entra.**

El script es idempotente: correrlo dos veces no hace daño.

---

## Reproducir las evidencias del reporte

### Ya incluidas en el PDF (salidas reales, ya ejecutadas)

```bash
source .env
python docs/semanaED1/evidencia.py       # -> salida_evidencia.txt
```

Las 8 pruebas: hashing, query directa a la base, login correcto e incorrecto,
sal aleatoria, migración de parámetros y cifrado en reposo con detección de
manipulación.

### Pendientes de capturar

**Hashing vía API (equivalente a Postman) — captura H1**

```bash
source .env && python app.py             # en otra terminal
bash docs/semanaED1/pruebas_api.sh | tee docs/semanaED1/salida_api.txt
```

**Aislamiento del plano privado — captura A1**

```bash
docker compose -f docker-compose.segmentado.yml up -d --build
bash docs/semanaED1/prueba_aislamiento.sh | tee docs/semanaED1/salida_aislamiento.txt
docker compose -f docker-compose.segmentado.yml down
```

Ambas capturas van en los recuadros marcados del reporte.

---

## Recompilar el PDF

```bash
cd docs/semanaED1
pdflatex reporte_semanaED1.tex           # dos veces, por el índice
pdflatex reporte_semanaED1.tex
```

Las rutas de los anexos son relativas (`../../crypto_utils.py`), así que hay
que compilar desde esta carpeta.

---

## Archivos

| Archivo | Qué es |
|---|---|
| `reporte_semanaED1.tex` / `.pdf` | El entregable |
| `evidencia.py` | Las 8 pruebas de consola |
| `pruebas_api.sh` | Evidencia del hashing por HTTP |
| `prueba_aislamiento.sh` | Batería de separación público/privado |
| `salida_*.txt` | Salidas reales ya capturadas, incluidas en el PDF |

En la raíz del proyecto:

| Archivo | Qué es |
|---|---|
| `crypto_utils.py` | AES-256-GCM + índice ciego **(nuevo)** |
| `password_hashing.py` | Política de hashing centralizada **(nuevo)** |
| `migrar_cifrado.py` | Migración de los datos existentes **(nuevo)** |
| `docker-compose.segmentado.yml` | Separación público/privado **(nuevo)** |
| `.env.example` | Plantilla de variables **(nuevo)** |
| `models.py` | `TextoCifrado`, `correo_bi`, `por_correo()` *(modificado)* |
| `app.py`, `api.py`, `validators.py` | Usan la política nueva *(modificado)* |
| `requirements.txt` | `+ cryptography` *(modificado)* |
