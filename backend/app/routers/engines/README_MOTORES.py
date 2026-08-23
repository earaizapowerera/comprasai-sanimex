"""
Punto de montaje para los motores de negocio (T4/T5/T6), NO se importa
automáticamente -- es solo referencia de cómo agregar un motor nuevo.

Cada motor (C1 deterministas, C2 ML forecast, C3 agente) debe:

  1. Vivir en su propio módulo dentro de `app/routers/engines/`, por ejemplo:
       - app/routers/engines/remates.py       (C1: motor de remates minuta GAM)
       - app/routers/engines/sugeridos.py     (C1: disponible, cobertura, MOQ/pallet)
       - app/routers/engines/forecast.py      (C2: forecast por canal)
       - app/routers/engines/chat_agente.py   (C3: explicabilidad + chat)

  2. Exponer un `router = APIRouter(prefix="/api/engines/<nombre>", tags=[...])`
     igual que los routers en app/routers/*.py (materiales, sucursales, etc.)

  3. Registrarse en app/main.py:
       from app.routers.engines import <modulo>
       app.include_router(<modulo>.router)

  4. Consumir el contrato de datos (core/schema.sql) vía `app.core.db.get_db`,
     igual que los routers existentes -- así el motor funciona igual con el
     dataset sintético o con datos reales de SAP, sin cambios de código.

Ver /api/engines/status (registrado en main.py) para un endpoint placeholder
que confirma que este punto de montaje está listo.
"""
