#!/usr/bin/env bash
# docs/semanaED1/pruebas_api.sh
#
# Evidencia del hashing contra la API REAL (equivalente a hacerlo en Postman).
# Registra un usuario por HTTP, inicia sesión con él, y acto seguido consulta
# la base de datos para mostrar que la contraseña que se envió no está
# guardada en ninguna parte.
#
# Requisito previo: la app corriendo en 127.0.0.1:5001
#     source .env && python app.py
#
# Uso:
#   bash docs/semanaED1/pruebas_api.sh 2>&1 | tee docs/semanaED1/salida_api.txt

set -u

BASE="http://127.0.0.1:5001/api/v1"
DB="questcash.db"
CORREO="hash_$(date +%s)@gmail.com"
PASSWORD="QuestCash2026!"

lim() { sed 's/\r$//' | grep -vE "^(Server|Date|Connection):"; }
linea() { printf '\n========================================================================\n %s\n========================================================================\n' "$1"; }

linea "H1 - REGISTRO por API: se envía la contraseña EN CLARO por el cuerpo"
echo "correo   = $CORREO"
echo "password = $PASSWORD"
echo
echo "\$ curl -i -X POST \$BASE/auth/register -d '{\"nombre\":\"Prueba Hash\",\"correo\":\"$CORREO\",\"password\":\"$PASSWORD\",\"password2\":\"$PASSWORD\"}'"
curl -s -i -X POST "$BASE/auth/register" -H "Content-Type: application/json" \
  -d "{\"nombre\":\"Prueba Hash\",\"correo\":\"$CORREO\",\"password\":\"$PASSWORD\",\"password2\":\"$PASSWORD\"}" | lim

linea "H2 - QUERY A LA BASE: qué se guardó realmente de ese usuario"
echo "\$ sqlite3 $DB \"SELECT id, nombre, correo, correo_bi, password_hash FROM usuarios ORDER BY id DESC LIMIT 1;\""
python3 - "$DB" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
fila = c.execute(
    "SELECT id, nombre, correo, correo_bi, password_hash FROM usuarios ORDER BY id DESC LIMIT 1"
).fetchone()
etiquetas = ("id", "nombre", "correo", "correo_bi", "password_hash")
for etiqueta, valor in zip(etiquetas, fila):
    print(f"{etiqueta:<14} = {valor}")
PY
echo
echo "Búsqueda literal de la contraseña en TODO el archivo de base de datos:"
echo "\$ grep -c '$PASSWORD' $DB"
if grep -c "$PASSWORD" "$DB" 2>/dev/null; then
  echo ">> ATENCIÓN: la contraseña aparece en el archivo."
else
  echo "0"
  echo ">> Correcto: la contraseña en claro NO existe en ninguna parte del archivo."
fi

linea "H3 - LOGIN con la contraseña correcta => 200 y token"
echo "\$ curl -i -X POST \$BASE/auth/login -d '{\"correo\":\"$CORREO\",\"password\":\"$PASSWORD\"}'"
curl -s -i -X POST "$BASE/auth/login" -H "Content-Type: application/json" \
  -d "{\"correo\":\"$CORREO\",\"password\":\"$PASSWORD\"}" | lim

linea "H4 - LOGIN con el HASH como contraseña => 401 (el hash no es la llave)"
HASH=$(python3 -c "
import sqlite3,sys
print(sqlite3.connect('$DB').execute('SELECT password_hash FROM usuarios ORDER BY id DESC LIMIT 1').fetchone()[0])")
echo "Se intenta iniciar sesión usando el hash robado de la base de datos."
curl -s -i -X POST "$BASE/auth/login" -H "Content-Type: application/json" \
  -d "{\"correo\":\"$CORREO\",\"password\":\"$HASH\"}" | lim

linea "H5 - LOGIN con contraseña incorrecta => 401 invalid_credentials"
curl -s -i -X POST "$BASE/auth/login" -H "Content-Type: application/json" \
  -d "{\"correo\":\"$CORREO\",\"password\":\"QuestCash2026\"}" | lim

linea "FIN"
echo "Usuario de prueba creado: $CORREO (id más alto de la tabla usuarios)."
echo "Puedes borrarlo con:"
echo "  sqlite3 $DB \"DELETE FROM usuarios WHERE correo_bi = (SELECT correo_bi FROM usuarios ORDER BY id DESC LIMIT 1);\""
