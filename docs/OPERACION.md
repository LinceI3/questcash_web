# Operar QuestCash

Qué mirar cuando algo va mal, y qué hacer para que no se pierdan los datos.

## Sondas de salud

| Ruta | Pregunta que responde | Si falla |
|---|---|---|
| `/health` | ¿El proceso está vivo? No toca la base. | Reiniciar el contenedor |
| `/ready` | ¿Puede atender tráfico? Comprueba Postgres. | El problema está **fuera** de la aplicación |

La distinción no es cosmética: si `/health` consultara la base, un orquestador
reiniciaría la aplicación en bucle cuando lo que se cayó fue Postgres —y
reiniciarla no arregla nada—.

El `HEALTHCHECK` del contenedor usa `/health`. Un monitor de disponibilidad
externo debería apuntar a `/ready`.

## Logs

Una línea JSON por evento en la salida estándar, que es donde cualquier
recolector los espera. En desarrollo se pueden pedir legibles:

```bash
LOG_FORMATO=texto LOG_NIVEL=DEBUG docker compose up
```

Cada petición registra: `peticion_id`, `metodo`, `ruta`, `estado`, `ms`,
`usuario_id` e `ip`.

### Lo que nunca aparece, y por qué

Correos, nombres, notas de movimientos, descripciones de gastos, importes,
contraseñas y tokens. QuestCash cifra los datos personales en reposo;
volcarlos al log los sacaría por la puerta de atrás, y los logs acaban en
sistemas con retención más larga y control de acceso más laxo que la base de
datos.

Se registra el **id numérico** del usuario, que permite investigar un incidente
sin exponer de quién se trata.

### El identificador de petición

Toda respuesta lleva `X-Request-ID`. Si alguien reporta un fallo y cita ese
valor, se encuentra su petición exacta:

```bash
docker logs questcash_web 2>&1 | grep '"peticion_id":"a1b2c3"'
```

Si el cliente manda la cabecera, se respeta, para poder seguir una operación a
través de varios servicios.

### Seguimiento de errores

Definir `SENTRY_DSN` lo activa. Sin esa variable la aplicación funciona igual y
los errores quedan en el log. Va configurado con `send_default_pii=False` y sin
cuerpos de petición: QuestCash trata datos financieros y esos no deben salir
hacia un tercero.

## Respaldos

```bash
set -a; . ./.env; set +a
RESPALDO_CLAVE_GPG='...' scripts/respaldo.sh
```

Objetivo declarado: **RPO 24 h / RTO 4 h**. Un día de datos perdidos como
máximo, y de vuelta en pie en cuatro horas.

El script verifica cada respaldo antes de darlo por bueno —tamaño, integridad
del gzip y presencia del esquema—, lo cifra si hay `RESPALDO_CLAVE_GPG`, y
aplica retención de 7 diarios más los lunes.

**Sin `RESPALDO_CLAVE_GPG` el volcado queda en claro.** Contiene los hashes de
contraseña y todos los criptogramas: guardarlo sin cifrar fuera de la base
anula buena parte del cifrado en reposo.

### Restaurar, y probar que se puede

```bash
scripts/restaurar.sh --verificar          # base desechable, no toca producción
scripts/restaurar.sh --a questcash_copia respaldos/questcash-AAAAMMDD.sql.gz
```

`--verificar` restaura el último respaldo en una base temporal, cuenta lo
restaurado, comprueba que los correos siguen cifrados y que ninguna meta quedó
con el saldo descuadrado, y borra la base al terminar.

> **Un respaldo que nunca se ha restaurado no es un respaldo.** El RTO de 4
> horas es una ilusión mientras nadie haya cronometrado una restauración real.
> Hacerlo **una vez por trimestre** y anotar la fecha y cuánto tardó.

| Fecha | Quién | Duración | Resultado |
|---|---|---|---|
| 2026-08-28 | verificación automática | < 1 min (datos de desarrollo) | Correcto |

## Lo que todavía no existe

Depende de contratar infraestructura — ver `docs/COSTOS.md`:

- **Postgres gestionado** con respaldos automáticos fuera de la máquina. Hoy
  los scripts funcionan pero alguien tiene que ejecutarlos.
- **Monitor de disponibilidad** externo apuntando a `/ready`.
- **Alertas** a un canal que alguien lea.
- **Agregación de logs**: hoy están en la salida del contenedor y se pierden al
  recrearlo.
