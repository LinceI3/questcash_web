"""El envío de correo no debe romper nada, tenga proveedor o no."""
import correo


def test_modo_consola_no_revienta_con_html():
    """`mensaje.get_content()` lanza KeyError sobre un multipart/alternative,
    que es lo que produce cualquier correo con versión HTML. Sin proveedor
    configurado eso mataba el hilo de envío en silencio."""
    assert correo.enviar(
        "alguien@questcash.com", "Asunto", "cuerpo en texto",
        html="<p>cuerpo en HTML</p>", sincrono=True,
    ) is True


def test_modo_consola_con_solo_texto():
    assert correo.enviar(
        "alguien@questcash.com", "Asunto", "solo texto", sincrono=True
    ) is True


def test_sin_destinatario_no_hace_nada():
    assert correo.enviar("", "Asunto", "cuerpo", sincrono=True) is False


def test_las_tres_plantillas_se_construyen():
    """Cada plantilla arma un multiparte con texto y HTML."""
    assert correo.enviar_recuperacion("a@questcash.com", "https://x/y", 60) is True
    assert correo.enviar_aviso_sin_cuenta("a@questcash.com") is True
    assert correo.enviar_password_cambiada("a@questcash.com") is True


def test_el_aviso_sin_cuenta_no_lleva_enlace_de_restablecimiento():
    """Es lo que permite responder siempre igual en el formulario sin dejar a
    nadie esperando: quien no tiene cuenta recibe una explicación, no una
    llave."""
    mensaje = correo._construir(
        "a@questcash.com", "Solicitud",
        "Alguien pidió restablecer la contraseña de una cuenta de QuestCash "
        "asociada a esta dirección, pero no existe ninguna.",
    )
    assert "/recuperar/" not in correo._cuerpo_de_texto(mensaje)


def test_sin_proveedor_configurado_se_detecta():
    assert correo.hay_proveedor() is False
