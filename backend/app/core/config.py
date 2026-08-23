"""Configuración centralizada de la app, resuelta desde variables de entorno."""

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent

# Ruta del archivo SQLite. Cuando T1 entregue el extracto real de SAP, se
# reemplaza el archivo en esta misma ruta (o se apunta COMPRASAI_DB_PATH a él)
# sin tocar código de la API ni de los motores.
DB_PATH = Path(os.environ.get("COMPRASAI_DB_PATH", str(BACKEND_DIR / "data" / "comprasai.db")))

# Prefijo bajo el cual nginx expone la app (ver deploy/nginx-comprasAI.conf.example).
# Se pasa a uvicorn como --root-path para que OpenAPI/redirects generen URLs correctas.
ROOT_PATH = os.environ.get("ROOT_PATH", "/comprasAI")

# Carpeta con el build estático del frontend (T5). Si no existe al arrancar,
# se sirve un placeholder para no romper el contenedor.
FRONTEND_STATIC_DIR = Path(
    os.environ.get("FRONTEND_STATIC_DIR", str(BACKEND_DIR.parent / "frontend_static"))
)

# Si el .db no existe al arrancar, generar automáticamente el dataset sintético
# para que la demo funcione out-of-the-box en cualquier ambiente.
AUTO_SEED_IF_MISSING = os.environ.get("AUTO_SEED_IF_MISSING", "1") == "1"
