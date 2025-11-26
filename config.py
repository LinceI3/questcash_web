# config.py
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    # Clave secreta fuerte (cámbiala en producción por una variable de entorno)
    SECRET_KEY = "super-secret-questcash-change-this-in-production"

    # Base de datos
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "questcash.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Seguridad de formularios (CSRF)
    WTF_CSRF_ENABLED = True

    # Seguridad de cookies
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = False  # cambia a True si usas HTTPS
    SESSION_COOKIE_SAMESITE = "Lax"

    REMEMBER_COOKIE_HTTPONLY = True
    SESSION_REFRESH_EACH_REQUEST = True
    SESSION_PROTECTION = "strong"

    # Duración de la sesión
    from datetime import timedelta
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)

    # Opcional: evita fuga de información en errores si no estás en desarrollo
    PROPAGATE_EXCEPTIONS = False

    # --- Subida de archivos (foto de perfil) ---
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads", "profiles")
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2 MB

    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}