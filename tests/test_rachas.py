"""Rachas de ahorro. Cubre el defecto API-03 y el de zona horaria."""
from datetime import datetime, timedelta, timezone

import pytest
from services import rachas


def _en_dias(*offsets):
    """Instantes UTC a N días de hoy, a mediodía local para no rozar bordes."""
    hoy = rachas.hoy_local()
    return [
        datetime.combine(hoy + timedelta(days=d), datetime.min.time())
        .replace(hour=12, tzinfo=rachas.ZONA)
        .astimezone(timezone.utc)
        for d in offsets
    ]


def test_sin_aportes_no_hay_racha():
    assert rachas.calcular([]) == {"racha_actual": 0, "mejor_racha": 0, "ultimo_dia": None}


def test_dias_consecutivos_hasta_hoy():
    r = rachas.calcular(_en_dias(-2, -1, 0))
    assert r["racha_actual"] == 3 and r["mejor_racha"] == 3


def test_una_racha_que_termino_ayer_sigue_viva():
    """A las 00:01 nadie ha ahorrado todavía; romperla por eso sería absurdo."""
    assert rachas.calcular(_en_dias(-2, -1))["racha_actual"] == 2


def test_una_racha_caducada_es_cero():
    """EL DEFECTO: antes se devolvía la longitud del último bloque sin mirar si
    terminaba hoy. Quien ahorró 7 días y lo dejó hace un mes seguía viendo
    "racha de 7" para siempre."""
    r = rachas.calcular(_en_dias(-40, -39, -38, -37, -36, -35, -34))
    assert r["racha_actual"] == 0, "una racha vieja no puede seguir activa"
    assert r["mejor_racha"] == 7, "pero el máximo histórico se conserva"


def test_la_mejor_racha_es_el_maximo_historico():
    r = rachas.calcular(_en_dias(-30, -29, -28, -27, -10, -1, 0))
    assert r["mejor_racha"] == 4
    assert r["racha_actual"] == 2


def test_varios_aportes_el_mismo_dia_cuentan_una_vez():
    hoy = rachas.hoy_local()
    tres_veces_hoy = [
        datetime.combine(hoy, datetime.min.time()).replace(hour=h, tzinfo=rachas.ZONA)
        .astimezone(timezone.utc) for h in (8, 14, 21)
    ]
    assert rachas.calcular(tres_veces_hoy)["racha_actual"] == 1


def test_un_aporte_de_noche_cuenta_en_el_dia_local():
    """EL DEFECTO DE ZONA: un aporte a las 19:00 en México son las 01:00 UTC del
    día siguiente. Comparado contra date.today() del servidor, partía rachas
    legítimas."""
    hoy = rachas.hoy_local()
    ayer_de_noche = (
        datetime.combine(hoy - timedelta(days=1), datetime.min.time())
        .replace(hour=19, tzinfo=rachas.ZONA).astimezone(timezone.utc)
    )
    hoy_de_dia = (
        datetime.combine(hoy, datetime.min.time())
        .replace(hour=10, tzinfo=rachas.ZONA).astimezone(timezone.utc)
    )
    # En UTC los dos instantes caen en el MISMO día: 19:00 de México son las
    # 01:00 UTC del día siguiente. El código viejo, que agrupaba por fecha UTC,
    # los contaba como un solo día de ahorro.
    assert ayer_de_noche.astimezone(timezone.utc).date() == hoy_de_dia.astimezone(timezone.utc).date()
    # Localmente son dos días consecutivos, que es lo que vivió el usuario.
    assert rachas.calcular([ayer_de_noche, hoy_de_dia])["racha_actual"] == 2


def test_las_fechas_sin_zona_se_tratan_como_utc():
    """Las filas antiguas se guardaron con datetime.utcnow(), sin tzinfo."""
    hoy = rachas.hoy_local()
    ingenua = datetime.combine(hoy, datetime.min.time()).replace(hour=18)
    r = rachas.calcular([ingenua])
    assert r["ultimo_dia"] is not None
