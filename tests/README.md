# Pruebas de QuestCash

## Cómo se corren

```bash
# 1. La pila local tiene que estar arriba (Postgres y Redis)
docker compose up -d

# 2. Crear la base de pruebas, una sola vez
set -a; . ./.env; set +a
docker compose exec -T db psql -U "$POSTGRES_USER" -d postgres \
  -c "CREATE DATABASE questcash_test;"

# 3. Correr
set -a; . ./.env; set +a
./venv/bin/python -m pytest -q
```

## Contra PostgreSQL real, no SQLite

No es un capricho. Casi todo lo que hay que verificar aquí no existe o se
comporta distinto en SQLite:

- `Numeric` con precisión decimal exacta,
- `SELECT ... FOR UPDATE`, que sostiene el bloqueo de saldo,
- las restricciones `UNIQUE` que sostienen la idempotencia,
- los tipos con zona horaria.

Una suite que pasara en SQLite no diría nada sobre producción.

El esquema se crea aplicando las **migraciones**, no `db.create_all()`. Así
cada ejecución comprueba de paso que las migraciones reproducen el esquema que
los modelos describen — que es justo lo que se rompió una vez durante la fase 2.

`conftest.py` se niega a arrancar si la base no termina en `_test`: las pruebas
truncan todas las tablas entre casos, y apuntar por accidente a la de
desarrollo la vaciaría entera.

## Qué cubre cada archivo

| Archivo | Qué protege |
|---|---|
| `test_dinero.py` | NaN e infinitos, precisión decimal, idempotencia, saldo que cuadra con sus movimientos |
| `test_autorizacion.py` | Que los datos de una persona no sean alcanzables por otra |
| `test_sesiones.py` | Rotación de refresh, revocación, bloqueo por intentos |
| `test_invitaciones.py` | Consentimiento en metas compartidas, no revelar quién tiene cuenta |
| `test_cuenta.py` | Exportar, eliminar de verdad, no descuadrar a terceros |
| `test_crypto.py` | Que lo escrito en disco sea ilegible y siga leyéndose desde la app |
| `test_correo.py` | Que el envío no rompa nada, con proveedor o sin él |
| `test_e2e.py` | El recorrido completo del usuario, en el orden real |

**Cada prueba corresponde a un defecto que existió de verdad** y se corrigió
durante la auditoría. No son hipótesis: son regresiones que ya ocurrieron una
vez, y los comentarios de cada una explican cuál era el fallo.

## Concurrencia: `tests/humo/`

```bash
python tests/humo/concurrencia.py --url http://localhost:5002
```

Esto **no** es pytest, y es deliberado. El cliente de pruebas de Flask atiende
una petición a la vez en el mismo proceso, así que los tres defectos que
verifica —aportes perdidos, idempotencia rota, contador de intentos que no se
comparte— darían verde siempre. Solo aparecen con varios procesos compitiendo
de verdad.

Ese fue exactamente el error durante la fase 3: el primer arreglo de la
condición de carrera se dio por bueno probándolo con un solo worker, y era
inerte. La pila destino debe correr con **al menos 2 workers**.

## Que la suite pueda fallar

Una suite que no puede fallar no vale nada. Estas cuatro mutaciones se
inyectaron a propósito para comprobar que se detectan:

| Mutación | Resultado |
|---|---|
| Quitar la guarda `is_finite()` de los montos | 11 pruebas fallan |
| Volver a exponer el correo de otros participantes | 1 prueba falla |
| Devolver el dinero a `Float` | 31 fallan, 14 errores |
| Borrar los aportes ajenos al eliminar la cuenta | 1 prueba falla |

Conviene repetir el ejercicio al añadir cobertura nueva: es la única forma de
saber si una prueba prueba algo.

## CI

`.github/workflows/ci.yml` corre en cada push y cada pull request:

1. **Detección de secretos** con gitleaks sobre el historial completo. Va
   primero: si algo se filtró, da igual que los tests pasen.
2. **Pruebas** contra un Postgres de servicio, en Python 3.12 —la misma versión
   del contenedor—, más `pip-audit` sobre las dependencias.
3. **Imagen y pila completa**: construye, levanta con 2 workers, y comprueba
   las cabeceras de seguridad, que la web no cargue ningún origen externo, y la
   concurrencia.

Antes ejecutaba `pytest` sobre un archivo cuyo contenido íntegro era
`assert True`, y desplegaba con `echo`.
