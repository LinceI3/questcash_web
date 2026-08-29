# tokens_correo.py
"""Emisión y canje de los tokens de un solo uso que viajan por correo."""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from models import TokenCorreo, Usuario, db

# Ventana corta: un enlace de recuperación en un buzón es una llave de la
# cuenta, y cuanto menos tiempo viva, menos vale robarlo.
MINUTOS_VALIDEZ = int(os.environ.get("RECUPERACION_MINUTOS", "60"))


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def emitir(usuario, tipo=TokenCorreo.RECUPERACION, ip=None):
    """Crea un token y devuelve el valor en claro (la única vez que existe).

    Invalida los anteriores del mismo tipo: pedir un enlace nuevo debe dejar
    inservible el viejo, o pedir varios multiplicaría las llaves vivas.
    """
    ahora = datetime.now(timezone.utc)
    (TokenCorreo.query
        .filter(TokenCorreo.usuario_id == usuario.id,
                TokenCorreo.tipo == tipo,
                TokenCorreo.usado_en.is_(None))
        .update({"usado_en": ahora}, synchronize_session=False))

    crudo = secrets.token_urlsafe(32)
    db.session.add(TokenCorreo(
        usuario_id=usuario.id,
        tipo=tipo,
        token_hash=_hash(crudo),
        expira_en=ahora + timedelta(minutes=MINUTOS_VALIDEZ),
        ip_solicitud=(ip or "")[:45] or None,
    ))
    return crudo


def usuario_de(crudo, tipo=TokenCorreo.RECUPERACION):
    """Devuelve (usuario, token) si el token sirve; (None, None) si no.

    No lo marca como usado: eso ocurre al confirmar el cambio, para que abrir
    el enlace y equivocarse en el formulario no queme el enlace.
    """
    if not crudo:
        return None, None
    ahora = datetime.now(timezone.utc)
    token = TokenCorreo.query.filter_by(token_hash=_hash(crudo), tipo=tipo).first()
    if token is None or not token.esta_vivo(ahora):
        return None, None
    usuario = Usuario.query.get(token.usuario_id)
    if usuario is None:
        return None, None
    return usuario, token


def consumir(token):
    token.usado_en = datetime.now(timezone.utc)
