# validators.py
"""Validaciones de formularios reutilizadas por las vistas HTML y la API JSON.

Funciones puras (sin closures de Flask): reciben strings crudos, devuelven
(errores, datos) donde `datos` solo se llena si `errores` está vacío.
"""
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from models import Usuario

# Máximo aceptado en cualquier importe. Cabe de sobra en Numeric(14, 2).
MONTO_MAXIMO = Decimal("1000000000")


def a_dinero(crudo):
    """Convierte la entrada del usuario en un Decimal de dos decimales.

    Se parte del TEXTO original, no de un float intermedio: `Decimal("0.1")`
    vale exactamente 0.1, mientras que `Decimal(0.1)` arrastra el error binario
    del float. Por eso la conversión es directa desde la cadena.

    Lanza ValueError si el valor no es un número finito. `Decimal` acepta
    "nan" e "infinity" igual que `float`, así que la comprobación sigue siendo
    necesaria: sin ella, NaN pasaba todas las validaciones —toda comparación
    con NaN es falsa— y corrompía el monto de la meta de forma irreversible.
    """
    try:
        valor = Decimal(str(crudo).strip())
    except (InvalidOperation, TypeError, ValueError, ArithmeticError) as exc:
        raise ValueError("monto inválido") from exc
    if not valor.is_finite():
        raise ValueError("monto no finito")
    # Redondeo a centavos: es la unidad mínima con la que trabaja el producto.
    return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

EMAIL_REGEX = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
ALLOWED_EMAIL_TLDS = (".com", ".mx", ".com.mx", ".org", ".net", ".edu", ".gob.mx")

CATEGORIAS_MOVIMIENTO_VALIDAS = {
    "general",
    "salario",
    "ahorro_programado",
    "extra",
    "comida",
    "transporte",
    "entretenimiento",
    "viaje",
    "regalos",
    "salud",
    "otros",
}


def validar_registro(nombre, correo, password, password2):
    """Valida el formulario de registro. Devuelve una lista de errores (vacía si es válido)."""
    errores = []

    if not nombre:
        errores.append("El nombre es obligatorio.")
    if not correo:
        errores.append("El correo es obligatorio.")
    if not password:
        errores.append("La contraseña es obligatoria.")
    if password != password2:
        errores.append("Las contraseñas no coinciden.")

    if nombre and len(nombre) > 100:
        errores.append("El nombre es demasiado largo (máximo 100 caracteres).")
    if correo and len(correo) > 150:
        errores.append("El correo es demasiado largo (máximo 150 caracteres).")
    if password and len(password) > 128:
        errores.append("La contraseña es demasiado larga (máximo 128 caracteres).")

    if correo:
        if not re.match(EMAIL_REGEX, correo):
            errores.append("El correo no tiene un formato válido.")
        if not any(correo.endswith(tld) for tld in ALLOWED_EMAIL_TLDS):
            errores.append(
                "El dominio de correo no está permitido. Usa un correo con dominio común (.com, .mx, .org, .net, .edu, .gob.mx)."
            )

    if password:
        if len(password) < 8:
            errores.append("La contraseña debe tener al menos 8 caracteres.")
        if not any(c.islower() for c in password):
            errores.append("La contraseña debe incluir al menos una letra minúscula.")
        if not any(c.isupper() for c in password):
            errores.append("La contraseña debe incluir al menos una letra mayúscula.")
        if not any(c.isdigit() for c in password):
            errores.append("La contraseña debe incluir al menos un número.")
        if nombre and password.lower() == nombre.lower():
            errores.append("La contraseña no puede ser igual a tu nombre.")
        if correo and password.lower() == correo.lower():
            errores.append("La contraseña no puede ser igual a tu correo.")

    if correo and not errores:
        # Búsqueda por índice ciego: la columna `correo` está cifrada y no
        # se puede consultar directamente (ver crypto_utils.py).
        if Usuario.por_correo(correo):
            errores.append("Ya existe una cuenta registrada con ese correo.")

    return errores


def validar_password_nueva(password, password2, nombre=None, correo=None):
    """Reglas de una contraseña nueva, compartidas por el registro, el cambio y
    el restablecimiento. Antes vivían solo dentro de validar_registro, así que
    cualquier flujo nuevo habría acabado duplicándolas o relajándolas."""
    errores = []
    if not password:
        errores.append("La contraseña es obligatoria.")
        return errores
    if password != password2:
        errores.append("Las contraseñas no coinciden.")
    if len(password) < 8:
        errores.append("La contraseña debe tener al menos 8 caracteres.")
    if len(password) > 128:
        errores.append("La contraseña es demasiado larga (máximo 128 caracteres).")
    if not any(c.islower() for c in password):
        errores.append("La contraseña debe incluir al menos una letra minúscula.")
    if not any(c.isupper() for c in password):
        errores.append("La contraseña debe incluir al menos una letra mayúscula.")
    if not any(c.isdigit() for c in password):
        errores.append("La contraseña debe incluir al menos un número.")
    if nombre and password.lower() == nombre.lower():
        errores.append("La contraseña no puede ser igual a tu nombre.")
    if correo and password.lower() == correo.lower():
        errores.append("La contraseña no puede ser igual a tu correo.")
    return errores


def validar_quest_form(nombre, monto_objetivo_raw, monto_actual_raw, fecha_limite_raw, descripcion, tipo):
    """Valida el formulario de creación/edición de una meta. Devuelve (errores, datos)."""
    errores = []

    if not nombre:
        errores.append("El nombre del reto es obligatorio.")
    if not monto_objetivo_raw:
        errores.append("El monto objetivo es obligatorio.")
    if not fecha_limite_raw:
        errores.append("La fecha límite es obligatoria.")

    monto_objetivo_float = None
    try:
        monto_objetivo_float = a_dinero(monto_objetivo_raw)
        if monto_objetivo_float <= 0:
            errores.append("El monto objetivo debe ser mayor a 0.")
    except (TypeError, ValueError):
        errores.append("El monto objetivo debe ser un número válido.")

    monto_actual_float = None
    try:
        monto_actual_float = a_dinero(monto_actual_raw) if monto_actual_raw else Decimal("0.00")
        if monto_actual_float < 0:
            errores.append("El monto actual no puede ser negativo.")
    except (TypeError, ValueError):
        errores.append("El monto actual debe ser un número válido.")

    fecha_limite_date = None
    try:
        fecha_limite_date = datetime.strptime(fecha_limite_raw, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        errores.append("La fecha límite no tiene un formato válido (AAAA-MM-DD).")

    if tipo not in ("individual", "colaborativo"):
        errores.append("Tipo de reto no válido.")

    if nombre and len(nombre) > 100:
        errores.append("El nombre del reto es demasiado largo (máximo 100 caracteres).")
    if descripcion and len(descripcion) > 500:
        errores.append("La descripción es demasiado larga (máximo 500 caracteres).")

    if monto_objetivo_float is not None and monto_objetivo_float > MONTO_MAXIMO:
        errores.append("El monto objetivo es demasiado grande.")
    if monto_objetivo_float is not None and monto_actual_float is not None:
        if monto_actual_float > monto_objetivo_float:
            errores.append("El monto actual no puede ser mayor que el monto objetivo.")

    if fecha_limite_date is not None:
        hoy = date.today()
        if fecha_limite_date < hoy:
            errores.append("La fecha límite no puede ser anterior a hoy.")
        if fecha_limite_date > hoy + timedelta(days=365 * 10):
            errores.append("La fecha límite es demasiado lejana (máximo 10 años desde hoy).")

    datos = {}
    if not errores:
        datos = {
            "monto_objetivo_float": monto_objetivo_float,
            "monto_actual_float": monto_actual_float,
            "fecha_limite_date": fecha_limite_date,
        }

    return errores, datos


def validar_movimiento(tipo_raw, monto_raw, nota_raw, categoria_raw, quest):
    """Valida un aporte/retiro sobre una meta. Devuelve (errores, datos)."""
    errores = []
    tipo = (tipo_raw or "").strip().lower()
    nota = (nota_raw or "").strip()
    if len(nota) > 500:
        nota = nota[:500]
    categoria = (categoria_raw or "general").strip().lower()

    if tipo not in ("aporte", "retiro"):
        errores.append("Tipo de movimiento no válido.")

    monto_float = None
    try:
        monto_float = a_dinero(monto_raw)
        if monto_float <= 0:
            errores.append("El monto debe ser mayor a 0.")
        if monto_float > MONTO_MAXIMO:
            errores.append("El monto es demasiado grande.")
    except (TypeError, ValueError):
        errores.append("Monto inválido.")

    if len(nota) > 500:
        errores.append("La nota no puede superar 500 caracteres.")

    if not categoria:
        categoria = "general"
    elif categoria not in CATEGORIAS_MOVIMIENTO_VALIDAS:
        categoria = "otros"

    if not errores and tipo == "retiro" and monto_float is not None:
        if monto_float > quest.monto_actual:
            errores.append("No puedes retirar más de lo que tienes ahorrado en este reto.")
        if quest.estatus == "completado":
            errores.append("No puedes retirar en un reto ya completado.")

    datos = {}
    if not errores:
        datos = {
            "tipo": tipo,
            "monto_float": monto_float,
            "nota": nota,
            "categoria": categoria,
        }

    return errores, datos


def validar_gasto(monto_raw, descripcion_raw, fecha_raw):
    """Valida un gasto nuevo. Devuelve (errores, datos)."""
    errores = []
    descripcion = (descripcion_raw or "").strip()

    monto = None
    try:
        monto = a_dinero(monto_raw)
        if monto <= 0:
            errores.append("El monto del gasto debe ser mayor a 0.")
        if monto > MONTO_MAXIMO:
            errores.append("El monto del gasto es demasiado grande.")
    except (TypeError, ValueError):
        errores.append("El monto del gasto no es válido.")

    fecha_str = (fecha_raw or "").strip()
    if fecha_str:
        try:
            fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except ValueError:
            errores.append("La fecha no tiene un formato válido (AAAA-MM-DD).")
            fecha = date.today()
    else:
        fecha = date.today()

    if descripcion and len(descripcion) > 200:
        errores.append("La descripción no puede superar 200 caracteres.")

    datos = {}
    if not errores:
        datos = {
            "monto": monto,
            "descripcion": descripcion,
            "fecha": fecha,
        }

    return errores, datos
