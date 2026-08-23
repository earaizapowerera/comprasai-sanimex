"""Constantes de negocio compartidas entre routers/motores.

Única fuente de verdad para valores que antes se repetían (o se hubieran
duplicado) entre módulos independientes -- evita que dos guards del mismo
concepto terminen con umbrales distintos por accidente.
"""

# Umbral mínimo de demanda mensual para considerarla "real" al calcular
# cobertura_meses (disponible_neto / demanda_prom). El dataset REAL CAR trae
# demandas que pueden venir en 0 o en valores residuales ~1e-15 (ruido de
# punto flotante / redondeos de origen); sin este guard, una división con un
# denominador ínfimo produce coberturas absurdas (del orden de 1e+15 meses).
# Por debajo de EPS_DEMANDA tratamos la demanda como "sin dato" -> misma
# semántica que demanda=0 (cobertura_meses=None), el sentinel que el frontend
# renderiza como "sin_dato"/"—".
#
# Origen: T16 (waykee 290112, commit 1ecdefe) lo introdujo en kpis.py.
# T18 (waykee 290114) lo extrajo aquí para reusarlo también en
# inventarios.py (COBERTURA_CTE) y engines/sugeridos.py (calc_cobertura_meses,
# reusado a su vez por engines/balanceos.py).
EPS_DEMANDA = 1e-6
