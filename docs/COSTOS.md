# QuestCash — lo que cuesta dinero

Inventario de todo lo que exige pagar antes de que QuestCash pueda operar
públicamente. **Nada de esto está contratado.** Todo el código que lo necesita
está escrito y probado contra sustitutos locales, así que contratar cada cosa
es rellenar variables de entorno, no programar.

Este archivo existe para que la lista no dependa de que alguien se acuerde.

---

## Orden de dependencia

Importa el orden, no solo la lista: **el dominio bloquea al correo, y el correo
bloquea la publicación en tiendas.**

```
Dominio  ──►  Proveedor de correo  ──►  Recuperación de contraseña operativa
   │                                              │
   │                                              ▼
   └──►  HTTPS / certificado          Requisito de App Store y Play
```

Sin dominio propio no se pueden publicar los registros SPF, DKIM y DMARC. Sin
esos registros, el correo de recuperación cae en spam o lo rechazan. Y sin
recuperación operativa, la app no pasa revisión de tienda — y, más importante,
un usuario que olvida su contraseña pierde la cuenta.

---

## 1. Dominio — lo primero y lo más barato

| | |
|---|---|
| **Coste** | ~10–20 USD/año |
| **Bloquea** | Correo, HTTPS, publicación en tiendas, aviso de privacidad |
| **Estado del código** | `APP_URL` ya se lee del entorno; los enlaces de correo se construyen con ella y no con el `Host` de la petición |

Registrar `questcash.mx` o equivalente. Después hay que publicar en su DNS los
registros que pida el proveedor de correo.

---

## 2. Proveedor de correo transaccional

| | |
|---|---|
| **Coste** | 0 al principio — los niveles gratuitos cubren el volumen inicial de sobra |
| **Recomendado** | **Resend** ahora; **Amazon SES** como destino cuando el volumen justifique el cambio |
| **Estado del código** | `correo.py` habla SMTP estándar. Cambiar de proveedor son cuatro variables |

Variables a rellenar:

```
MAIL_SMTP_HOST, MAIL_SMTP_PUERTO, MAIL_SMTP_USUARIO, MAIL_SMTP_PASSWORD
MAIL_REMITENTE, MAIL_REMITENTE_NOMBRE
```

**Google no sirve.** Gmail y Workspace prohíben explícitamente el correo de
aplicación, tienen límites duros por cuenta, no ofrecen gestión de rebotes ni
reputación de dominio propia, y si algo parece spam suspenden la cuenta entera
—que es también el correo personal—. La recuperación de contraseña es la
función más sensible a la entregabilidad de todo el producto.

En desarrollo se usa **Mailpit** (`docker compose`, bandeja en
`http://localhost:8025`), que recibe todo y no reenvía nada. Cuesta 0.

---

## 3. PostgreSQL gestionado

| | |
|---|---|
| **Coste** | ~7–25 USD/mes según proveedor |
| **Bloquea** | El objetivo RPO 24 h / RTO 4 h. Hoy la pérdida de datos sería total y definitiva |
| **Estado del código** | La aplicación solo lee `DATABASE_URL`. Migrar es cambiar esa cadena |

Es lo que convierte «sin respaldos» en «con respaldos» sin construir nada.
Contratar **antes del primer usuario real**, no después.

Sigue haciendo falta, aparte del proveedor: **una restauración de prueba
documentada por trimestre.** Un respaldo que nunca se ha restaurado no es un
respaldo.

---

## 4. Almacenamiento de objetos (fotos de perfil)

| | |
|---|---|
| **Coste** | Céntimos al mes con este volumen |
| **Bloquea** | Escalar a más de una instancia, y la subida de foto desde la app móvil |
| **Estado del código** | **Pendiente.** Hoy se guardan en el disco del contenedor |

Las fotos desaparecen en cada redespliegue y solo existen en el proceso que las
recibió. Cualquier servicio compatible con S3 sirve.

---

## 5. Cuentas de desarrollador

| | Apple | Google Play |
|---|---|---|
| **Coste** | 99 USD/año | 25 USD, pago único |
| **Cuándo** | Solo al ir a publicar | Solo al ir a publicar |

No hacen falta para desarrollar ni para compilar: EAS permite builds de
desarrollo y de vista previa sin cuenta de pago.

Ambas tiendas exigen además una **URL pública de política de privacidad**, que
depende del dominio y de la fase legal.

---

## 6. Asesoría legal

| | |
|---|---|
| **Coste** | Variable |
| **Bloquea** | Operar públicamente |

El marco mexicano de protección de datos cambió de forma sustancial en 2025:
nueva Ley Federal de Protección de Datos Personales en Posesión de los
Particulares y cambio de autoridad reguladora. Hay que **confirmar el estado
vigente con un abogado** antes de publicar aviso de privacidad o términos.

QuestCash trata datos personales *patrimoniales o financieros*, categoría que
exige consentimiento **expreso**, no tácito.

---

## Lo que NO cuesta dinero y conviene no confundir

- Certificado TLS: gratis con Let's Encrypt.
- Redis, Postgres y el servidor SMTP de desarrollo: contenedores locales.
- Seguimiento de errores, uptime y logs: los niveles gratuitos bastan para
  arrancar.
- Builds de desarrollo y vista previa de la app móvil.
- Identificadores de aplicación, firma gestionada por EAS, perfiles de build.

---

## Total para arrancar

| Concepto | Primer año |
|---|---|
| Dominio | ~15 USD |
| Correo | 0 |
| Postgres gestionado | ~84–300 USD |
| Almacenamiento de objetos | ~5 USD |
| Apple + Google | 124 USD |
| **Suma sin la parte legal** | **~230–450 USD** |

La parte legal es la partida grande y la más difícil de estimar, y es también
la única sin la que no se puede operar públicamente aunque todo lo demás esté
pagado.
