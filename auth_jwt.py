# auth_jwt.py
"""Autenticación por JWT para la API móvil (/api/v1). Independiente de la
sesión por cookie usada por las vistas HTML."""
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import current_app, g, jsonify, request

from models import Usuario


def generate_token(usuario_id):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(usuario_id),
        "iat": now,
        "exp": now + timedelta(days=current_app.config["JWT_EXP_DAYS"]),
    }
    return jwt.encode(payload, current_app.config["JWT_SECRET_KEY"], algorithm="HS256")


def decode_token(token):
    """Lanza jwt.ExpiredSignatureError / jwt.InvalidTokenError si el token no es válido."""
    payload = jwt.decode(token, current_app.config["JWT_SECRET_KEY"], algorithms=["HS256"])
    return payload


def _extraer_token():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    return header[len("Bearer "):].strip()


def jwt_required(vista):
    """Decorator para rutas de la API: exige un Bearer token válido y carga g.api_usuario."""
    @wraps(vista)
    def wrapped(*args, **kwargs):
        token = _extraer_token()
        if not token:
            return jsonify({"error": "missing_token"}), 401

        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "token_expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "invalid_token"}), 401

        usuario = Usuario.query.get(int(payload["sub"]))
        if usuario is None:
            return jsonify({"error": "invalid_token"}), 401

        g.api_usuario = usuario
        return vista(*args, **kwargs)

    return wrapped
