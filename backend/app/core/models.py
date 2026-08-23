"""Modelos Pydantic de respuesta (reflejan el contrato de datos de schema.sql)."""

from typing import Optional

from pydantic import BaseModel


class Material(BaseModel):
    material_id: str
    descripcion: str
    familia: str
    formato: Optional[str] = None
    m2_por_caja: Optional[float] = None
    abc: Optional[str] = None
    precio_venta: float
    costo: float
    economico: int


class Sucursal(BaseModel):
    plant: str
    nombre: str
    organizacion: str
    canal: str
    corredor: Optional[str] = None
    es_cedis: int


class InventarioItem(BaseModel):
    material_id: str
    plant: str
    descripcion: Optional[str] = None
    nombre_sucursal: Optional[str] = None
    disponible: float
    transito: float
    comprometido: float
    pedidos_abiertos: float
    cajas_remanentes: int
    disponible_neto: float
    meses_objetivo: Optional[float] = None


class VentaPunto(BaseModel):
    clave: str
    anio_mes: str
    cantidad_m2: float
    importe: float


class KpiResponse(BaseModel):
    fill_rate_pct: float
    cobertura_promedio_meses: float
    dias_inventario_promedio: float
    valor_inventario_total: float
    compras_urgentes: int
    pares_material_plant: int
    pares_en_quiebre: int


class PagedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list
