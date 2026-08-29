# auth_jwt.py
"""Autenticación por token para la API (/api/v1).

Modelo de dos tokens
--------------------
Antes se emitía un único JWT de 30 días, sin identificador, sin lista de
revocación y sin forma de renovarlo. Cerrar sesión solo lo borraba del
dispositivo: seguía siendo válido un mes para quien lo tuviera, y cambiar la
contraseña tampoco lo invalidaba.

Ahora:

  ACCESS  60 minutos. No se guarda en ninguna parte. Se valida por firma,
          caducidad y `token_version` — incrementar esa columna en `usuarios`
          invalida de golpe todos los access vivos de la cuenta, sin buscarlos.

  REFRESH 30 días. Vive en la tabla `sesiones` y se puede revocar. ROTA en cada
          uso: al canjearlo se revoca el anterior y se emite uno nuevo. Si
          alguien roba un refresh y lo canjea, el legítimo falla en su
          siguiente intento y el robo se nota.

Del refresh solo se guarda su SHA-256. Igual que con las contraseñas: quien lea
la tabla no puede suplantar a nadie con lo que encuentre.

Es independiente de la sesión por cookie que usan las vistas HTML.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import current_app, g, jsonify, request

from models import Sesion, Usuario, db

TIPO_ACCESO = "access"


# ---------------------------------------------------------------------------
#  Access token
# ---------------------------------------------------------------------------
def generar_access_token(usuario):
    ahora = datetime.now(timezone.utc)
    minutos = int(current_app.config.get("JWT_ACCESS_MINUTOS", 60))
    payload = {
        "sub": str(usuario.id),
        "typ": TIPO_ACCESO,
        # Versión de tokens de la cuenta en el momento de emitir. Si cambia,
        # este token deja de valer sin que nadie tenga que ir a buscarlo.
        "tv": int(usuario.token_version or 1),
        "iat": ahora,
        "exp": ahora + timedelta(minutes=minutos),
        # Identificador único: permite correlacionar en los logs y deja la
        # puerta abierta a una lista de revocación por token si hiciera falta.
        "jti": secrets.token_urlsafe(12),
    }
    return jwt.encode(payload, current_app.config["JWT_SECRET_KEY"], algorithm="HS256"), minutos * 60


def decode_token(token):
    """Lanza jwt.ExpiredSignatureError / jwt.InvalidTokenError si no es válido."""
    return jwt.decode(token, current_app.config["JWT_SECRET_KEY"], algorithms=["HS256"])


# ---------------------------------------------------------------------------
#  Refresh token
# ---------------------------------------------------------------------------
def _hash_refresh(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def emitir_refresh_token(usuario, dispositivo=None):
    """Crea una sesión nueva y devuelve el refresh en claro (única vez que existe)."""
    crudo = secrets.token_urlsafe(48)
    dias = int(current_app.config.get("JWT_REFRESH_DIAS", 30))
    sesion = Sesion(
        usuario_id=usuario.id,
        token_hash=_hash_refresh(crudo),
        dispositivo=(dispositivo or "")[:120] or None,
        expira_en=datetime.now(timezone.utc) + timedelta(days=dias),
    )
    db.session.add(sesion)
    return crudo, sesion


def canjear_refresh_token(crudo, dispositivo=None):
    """Valida un refresh, lo rota y devuelve (usuario, nuevo_refresh).

    Devuelve (None, None) si el token no existe, ya se usó, se revocó o
    caducó. La rotación es lo que hace detectable el robo: un refresh ya
    canjeado queda revocado, así que el segundo en usarlo se queda fuera.
    """
    if not crudo:
        return None, None

    ahora = datetime.now(timezone.utc)
    sesion = Sesion.query.filter_by(token_hash=_hash_refresh(crudo)).first()
    if sesion is None or not sesion.esta_viva(ahora):
        return None, None

    usuario = Usuario.query.get(sesion.usuario_id)
    if usuario is None:
        return None, None

    sesion.revocada_en = ahora
    sesion.motivo_revocacion = "rotacion"
    sesion.ultimo_uso = ahora

    nuevo, _ = emitir_refresh_token(usuario, dispositivo or sesion.dispositivo)
    return usuario, nuevo


def revocar_refresh_token(crudo, motivo="logout"):
    """Cierra una sesión concreta. True si había algo que cerrar."""
    if not crudo:
        return False
    sesion = Sesion.query.filter_by(token_hash=_hash_refresh(crudo)).first()
    if sesion is None or sesion.revocada_en is not None:
        return False
    sesion.revocada_en = datetime.now(timezone.utc)
    sesion.motivo_revocacion = motivo
    return True


def revocar_todas_las_sesiones(usuario, motivo="cierre_total"):
    """Cierra todas las sesiones e invalida los access tokens ya emitidos.

    Las dos cosas son necesarias: revocar las sesiones corta la renovación,
    pero un access token vivo seguiría funcionando hasta caducar. Subir
    token_version lo mata también.
    """
    ahora = datetime.now(timezone.utc)
    cerradas = (
        Sesion.query
        .filter(Sesion.usuario_id == usuario.id, Sesion.revocada_en.is_(None))
        .update({"revocada_en": ahora, "motivo_revocacion": motivo}, synchronize_session=False)
    )
    usuario.token_version = int(usuario.token_version or 1) + 1
    return cerradas


# ---------------------------------------------------------------------------
#  Decorator
# ---------------------------------------------------------------------------
def _extraer_token():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    return header[len("Bearer "):].strip()


def jwt_required(vista):
    """Exige un access token válido y carga g.api_usuario."""
    @wraps(vista)
    def wrapped(*args, **kwargs):
        token = _extraer_token()
        if not token:
            return jsonify({"error": "missing_token"}), 401

        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            # El cliente debe canjear su refresh en /auth/refresh y reintentar.
            return jsonify({"error": "token_expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "invalid_token"}), 401

        # Un refresh token no es un JWT, así que no llega aquí; la comprobación
        # de `typ` protege igualmente de que un token de otro propósito valga
        # como credencial de acceso.
        if payload.get("typ") != TIPO_ACCESO:
            return jsonify({"error": "invalid_token"}), 401

        usuario = Usuario.query.get(int(payload["sub"]))
        if usuario is None:
            return jsonify({"error": "invalid_token"}), 401

        if int(payload.get("tv", 0)) != int(usuario.token_version or 1):
            # Cambió la contraseña o se cerraron todas las sesiones.
            return jsonify({"error": "token_revoked"}), 401

        g.api_usuario = usuario
        return vista(*args, **kwargs)

    return wrapped
