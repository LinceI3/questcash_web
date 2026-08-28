#!/usr/bin/env bash
# docs/semanaED1/prueba_aislamiento.sh
#
# Comprueba que el plano privado está realmente aislado.
# No basta con dibujarlo: aquí se intenta llegar a la base de datos por
# los caminos que usaría un atacante, y se documenta que fallan.
#
# Requisito previo:
#   docker compose -f docker-compose.segmentado.yml up -d --build
#
# Uso:
#   bash docs/semanaED1/prueba_aislamiento.sh 2>&1 | tee docs/semanaED1/salida_aislamiento.txt

set -u

COMPOSE="docker compose -f docker-compose.segmentado.yml"
LINEA="========================================================================"

titulo() { echo; echo "$LINEA"; echo "  $1"; echo "$LINEA"; }

titulo "0. Estado de los contenedores"
$COMPOSE ps

titulo "1. ¿Qué puertos están publicados hacia la máquina anfitriona?"
echo "Solo debe aparecer el gateway. Si aquí sale 5432, la separación no existe."
docker ps --format 'table {{.Names}}\t{{.Ports}}'

titulo "2. Intento de conectar a Postgres desde el anfitrión (debe FALLAR)"
echo "\$ nc -zv 127.0.0.1 5432"
if nc -zv -w 3 127.0.0.1 5432 2>&1; then
  echo ">> ATENCIÓN: el puerto respondió. La base está expuesta."
else
  echo ">> Correcto: no hay nada escuchando en 5432 en el anfitrión."
fi

titulo "3. ¿Docker publica algún puerto de db? (debe FALLAR)"
echo "\$ docker compose -f docker-compose.segmentado.yml port db 5432"
$COMPOSE port db 5432 || echo ">> Correcto: el servicio db no tiene puertos publicados."

titulo "4. Desde el gateway (plano público) hacia la base (debe FALLAR)"
echo "El Nginx no comparte red con Postgres: ni siquiera resuelve el nombre."
docker exec qc_gateway sh -c 'nc -zv -w 3 db 5432' 2>&1 \
  || echo ">> Correcto: el gateway no tiene ruta hacia la base de datos."

titulo "5. Desde la aplicación (la frontera) hacia la base (debe FUNCIONAR)"
echo "Este es el único camino legítimo."
docker exec qc_web sh -c 'nc -zv -w 3 db 5432' 2>&1 \
  && echo ">> Correcto: la aplicación sí alcanza la base de datos."

titulo "6. Desde la base hacia Internet (debe FALLAR)"
echo "La red privada está declarada 'internal': sin salida a Internet,"
echo "lo que corta la exfiltración de datos desde la propia base."
docker exec qc_db_privada sh -c 'getent hosts example.com || echo sin-DNS' 2>&1
docker exec qc_db_privada sh -c 'timeout 4 bash -c "echo > /dev/tcp/1.1.1.1/443" && echo "SALIÓ A INTERNET"' 2>&1 \
  || echo ">> Correcto: la base de datos no puede salir a Internet."

titulo "7. La aplicación sí responde desde fuera (el plano público funciona)"
echo "\$ curl -si http://localhost:8443/login | head -1"
curl -si --max-time 5 http://localhost:8443/login | head -1 \
  || echo ">> El gateway no respondió; revisa que los contenedores estén arriba."

titulo "8. Redes de Docker y quién pertenece a cada una"
for red in questcash-segmentado_publica questcash-segmentado_privada; do
  echo "--- $red ---"
  docker network inspect "$red" \
    --format '{{range .Containers}}{{.Name}} {{end}}| internal={{.Internal}}' 2>/dev/null \
    || echo "(red no encontrada)"
done

echo
echo "$LINEA"
echo "  FIN DE LA PRUEBA DE AISLAMIENTO"
echo "$LINEA"
