"""Lógica de negocio de QuestCash, fuera de las vistas.

Antes todo esto vivía como closures dentro de `create_app()` en app.py, y
`api.py` las recibía en un diccionario `ctx` con diecinueve entradas. Funcionaba
y evitaba duplicar reglas entre la web y la API, pero tenía un costo: nada se
podía importar, probar en aislamiento ni mover a otro sitio sin instanciar una
aplicación Flask completa.

Cada módulo de aquí es importable por sí solo. Los que no tocan la base de
datos —rangos, puntos— son funciones puras.
"""
