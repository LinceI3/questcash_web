# correo.py
"""Envío de correo transaccional, independiente del proveedor.

Por qué SMTP y no el SDK de nadie
---------------------------------
Resend, Amazon SES, Postmark, Brevo y Mailgun hablan todos SMTP estándar.
Programar contra SMTP en vez de contra el SDK de uno de ellos significa que
cambiar de proveedor es cambiar variables de entorno, no reescribir código. Es
la misma regla que se aplicó con Render: la aplicación no debe estar diseñada
alrededor de un proveedor concreto.

El día que se contrate uno, basta rellenar en el entorno:

    MAIL_SMTP_HOST, MAIL_SMTP_PORT, MAIL_SMTP_USUARIO, MAIL_SMTP_PASSWORD

Modo consola
------------
Si no hay MAIL_SMTP_HOST, los correos se escriben en el log en vez de
enviarse. Permite desarrollar y probar los flujos completos sin contratar
nada. En staging y production config.py exige la configuración real, así que
este modo no puede colarse en un despliegue.

En desarrollo, docker-compose levanta Mailpit: un servidor SMTP de mentira con
bandeja web en http://localhost:8025 que recibe todo y no reenvía nada. Es la
forma de ver el correo tal y como le llegará al usuario sin mandarle nada a
nadie.

Envío en segundo plano
----------------------
El envío NO va en el hilo de la petición. Si el proveedor tarda o falla, el
registro del usuario se quedaría colgado o devolvería un error por algo que no
es culpa suya. Con el volumen de QuestCash —recuperaciones e invitaciones—
basta un hilo; una cola tipo Celery no se justifica todavía.
"""
from __future__ import annotations

import logging
import os
import smtplib
import threading
from email.message import EmailMessage
from email.utils import formataddr

logger = logging.getLogger("questcash.correo")


def _config():
    return {
        "host": os.environ.get("MAIL_SMTP_HOST", "").strip(),
        "puerto": int(os.environ.get("MAIL_SMTP_PUERTO", "587")),
        "usuario": os.environ.get("MAIL_SMTP_USUARIO", "").strip(),
        "password": os.environ.get("MAIL_SMTP_PASSWORD", ""),
        # STARTTLS es lo que usan casi todos en el 587. Mailpit no lo necesita.
        "tls": os.environ.get("MAIL_SMTP_TLS", "1").strip().lower() in ("1", "true", "yes", "on"),
        "remitente": os.environ.get("MAIL_REMITENTE", "no-responder@questcash.local"),
        "nombre_remitente": os.environ.get("MAIL_REMITENTE_NOMBRE", "QuestCash"),
    }


def hay_proveedor() -> bool:
    return bool(_config()["host"])


def _construir(destinatario, asunto, texto, html=None):
    cfg = _config()
    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["From"] = formataddr((cfg["nombre_remitente"], cfg["remitente"]))
    mensaje["To"] = destinatario
    # Marca el correo como automático: evita respuestas automáticas de
    # vacaciones y ayuda a que los filtros lo clasifiquen como transaccional.
    mensaje["Auto-Submitted"] = "auto-generated"
    mensaje.set_content(texto)
    if html:
        mensaje.add_alternative(html, subtype="html")
    return mensaje


def _cuerpo_de_texto(mensaje):
    """Parte de texto plano de un mensaje, sea simple o multiparte.

    `mensaje.get_content()` lanza KeyError sobre un multipart/alternative, que
    es lo que produce cualquier correo con versión HTML. En modo consola eso
    mataba el hilo de envío en silencio.
    """
    if mensaje.is_multipart():
        parte = mensaje.get_body(preferencelist=("plain",))
        if parte is not None:
            return parte.get_content()
        return "(sin parte de texto plano)"
    return mensaje.get_content()


def _enviar_ahora(mensaje, destinatario):
    cfg = _config()
    if not cfg["host"]:
        # Modo consola: se registra el cuerpo para poder seguir el flujo en
        # desarrollo. Solo ocurre sin proveedor configurado, y config.py exige
        # uno en staging y production.
        try:
            cuerpo = _cuerpo_de_texto(mensaje)
        except Exception:
            cuerpo = "(no se pudo extraer el cuerpo)"
        logger.info(
            "[CORREO EN CONSOLA] para=%s asunto=%s\n%s",
            destinatario, mensaje["Subject"], cuerpo,
        )
        return True

    try:
        with smtplib.SMTP(cfg["host"], cfg["puerto"], timeout=15) as servidor:
            if cfg["tls"]:
                servidor.starttls()
            if cfg["usuario"]:
                servidor.login(cfg["usuario"], cfg["password"])
            servidor.send_message(mensaje)
        logger.info("correo enviado a %s: %s", destinatario, mensaje["Subject"])
        return True
    except Exception:
        # No se relanza: que falle el correo no debe romper la operación que lo
        # disparó. Queda en el log para que el seguimiento de errores lo vea.
        logger.exception("fallo al enviar correo a %s", destinatario)
        return False


def enviar(destinatario, asunto, texto, html=None, sincrono=False):
    """Encola un correo. `sincrono=True` solo en pruebas."""
    if not destinatario:
        return False
    mensaje = _construir(destinatario, asunto, texto, html)

    if sincrono:
        return _enviar_ahora(mensaje, destinatario)

    hilo = threading.Thread(
        target=_enviar_ahora, args=(mensaje, destinatario), daemon=True
    )
    hilo.start()
    return True


# ---------------------------------------------------------------------------
#  Plantillas
# ---------------------------------------------------------------------------
_ENVOLTURA_HTML = """\
<!doctype html>
<html lang="es"><body style="margin:0;padding:24px;background:#F5F6F9;
  font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#10151E">
  <div style="max-width:520px;margin:0 auto;background:#fff;border-radius:8px;padding:32px">
    <p style="font-size:20px;font-weight:700;margin:0 0 24px">QuestCash</p>
    {cuerpo}
    <hr style="border:0;border-top:1px solid #E4E8EF;margin:32px 0 16px">
    <p style="font-size:12px;color:#626C7C;margin:0">
      Este es un correo automático, no respondas a esta dirección.
    </p>
  </div>
</body></html>"""

_BOTON = (
    '<p style="margin:24px 0"><a href="{url}" style="display:inline-block;'
    'background:#1B3FA0;color:#fff;text-decoration:none;padding:12px 24px;'
    'border-radius:6px;font-weight:600">{texto}</a></p>'
    '<p style="font-size:13px;color:#626C7C;margin:0">'
    'Si el botón no funciona, copia esta dirección en tu navegador:<br>'
    '<span style="word-break:break-all">{url}</span></p>'
)


def enviar_recuperacion(destinatario, url, minutos):
    asunto = "Restablece tu contraseña de QuestCash"
    texto = (
        "Recibimos una solicitud para restablecer la contraseña de tu cuenta "
        f"de QuestCash.\n\nAbre esta dirección para elegir una nueva:\n{url}\n\n"
        f"El enlace caduca en {minutos} minutos y solo se puede usar una vez.\n\n"
        "Si no fuiste tú, ignora este correo: tu contraseña no cambia hasta que "
        "alguien abra ese enlace."
    )
    cuerpo = (
        "<p>Recibimos una solicitud para restablecer la contraseña de tu cuenta.</p>"
        + _BOTON.format(url=url, texto="Elegir nueva contraseña")
        + f'<p style="font-size:13px;color:#626C7C;margin:16px 0 0">El enlace caduca '
          f"en {minutos} minutos y solo se puede usar una vez. Si no fuiste tú, "
          "ignora este correo: tu contraseña no cambia hasta que alguien lo abra.</p>"
    )
    return enviar(destinatario, asunto, texto, _ENVOLTURA_HTML.format(cuerpo=cuerpo))


def enviar_aviso_sin_cuenta(destinatario):
    """Se manda cuando alguien pide recuperar una cuenta que no existe.

    Es lo que permite responder SIEMPRE lo mismo en el formulario sin dejar a
    nadie a medias: quien tiene cuenta recibe el enlace, quien no la tiene
    recibe esto y entiende por qué. Desde fuera, las dos peticiones son
    indistinguibles.
    """
    asunto = "Solicitud de recuperación en QuestCash"
    texto = (
        "Alguien pidió restablecer la contraseña de una cuenta de QuestCash "
        f"asociada a esta dirección, pero no existe ninguna.\n\n"
        "Si fuiste tú, quizá te registraste con otro correo. Si no, puedes "
        "ignorar este mensaje."
    )
    cuerpo = (
        "<p>Alguien pidió restablecer la contraseña de una cuenta asociada a esta "
        "dirección, pero no existe ninguna.</p>"
        "<p>Si fuiste tú, quizá te registraste con otro correo. Si no, puedes "
        "ignorar este mensaje.</p>"
    )
    return enviar(destinatario, asunto, texto, _ENVOLTURA_HTML.format(cuerpo=cuerpo))


def enviar_password_cambiada(destinatario):
    asunto = "Tu contraseña de QuestCash cambió"
    texto = (
        "La contraseña de tu cuenta de QuestCash acaba de cambiar, y se cerraron "
        "todas las sesiones abiertas.\n\n"
        "Si no fuiste tú, restablece tu contraseña de inmediato: alguien más "
        "tiene acceso a tu cuenta."
    )
    cuerpo = (
        "<p>La contraseña de tu cuenta acaba de cambiar, y se cerraron todas las "
        "sesiones abiertas.</p>"
        '<p style="color:#A81F27"><strong>Si no fuiste tú</strong>, restablece tu '
        "contraseña de inmediato: alguien más tiene acceso a tu cuenta.</p>"
    )
    return enviar(destinatario, asunto, texto, _ENVOLTURA_HTML.format(cuerpo=cuerpo))
