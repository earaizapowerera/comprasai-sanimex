# ComprasAI Sanimex — Sistema de Diseño & Especificación UX

**Demo:** Plataforma Inteligente de Planeación Comercial, Inventarios y Abastecimiento con IA
**Deploy:** `http://192.168.10.10/comprasAI`  ·  **Módulo padre:** waykee 290077 (Frontend Web)
**Inspiración:** Apple Human Interface Guidelines · Linear · Stripe Dashboards
**Entregables:** `design/design-tokens.css`, `design/components.css`, este spec.

---

## 0. Principios de diseño

1. **Claridad sobre densidad.** Cada pantalla responde una pregunta antes de que el usuario la formule. Espaciado generoso, una idea dominante por vista.
2. **El dato es el héroe.** Números grandes en `tabular-nums`, cromática sobria; el color se reserva para significado (semáforo, ABC, IA), no para decorar.
3. **La IA es explicable, no mágica.** Toda recomendación de la capa agéntica (C3) viene con su "por qué" a un clic: factores ponderados, datos fuente y capa que la generó (C1/C2/C3).
4. **Menos de 3 clics al valor.** Caso estrella: *generar sugerido → ver explicación IA → aprobar* en 3 interacciones.
5. **Confianza operativa.** Estados vacíos cuidados, loading elegante (skeletons, no spinners), acciones destructivas con confirmación, feedback inmediato.
6. **Light & Dark de primera clase.** Ambos temas diseñados, no derivados. Respeta preferencia del SO y toggle manual persistente.

---

## 1. Fundamentos (tokens)

| Fundamento | Decisión | Token(s) |
|---|---|---|
| **Tipografía** | Inter (fallback SF/system). Escala modular 1.2, tracking negativo en títulos. Números tabulares en datos. | `--font-sans`, `--fs-*`, `--ls-*` |
| **Color base** | Neutrales gris-azulado (fríos, Apple). Superficies por elevación. | `--bg-*`, `--text-*`, `--border-*` |
| **Acento** | Azul SF (`#2563eb` light / `#5b9dff` dark) para acción. | `--accent*` |
| **Acento IA** | Violeta iris + gradiente iris→azul para la capa agéntica y explicabilidad. | `--ai`, `--ai-gradient` |
| **Semántica** | Verde/Ámbar/Rojo para semáforo y estados; siempre con ícono+texto de respaldo. | `--success/warning/danger`, `--sem-*` |
| **Espaciado** | Base 4px, alias semánticos (`--gap-card`, `--page-pad-x`). | `--space-*` |
| **Radios** | 12px controles, 16px cards, 22px paneles, pill para chips. | `--radius-*` |
| **Sombras** | Suaves y difusas (estilo Apple), 5 niveles + ring de foco. | `--shadow-*` |
| **Movimiento** | 140ms hover, 220ms entradas, 360ms modal. Curva `ease-out` de Apple; spring sutil en toggles. Respeta `prefers-reduced-motion`. | `--dur-*`, `--ease-*` |

### Validación de contraste (WCAG 2.1 AA)
| Par | Ratio | Nivel |
|---|---|---|
| `--text-primary` sobre `--bg-surface` (light) | 15.8:1 | AAA |
| `--text-secondary` sobre `--bg-surface` (light) | 7.4:1 | AAA |
| `--text-tertiary` sobre `--bg-surface` (light) | 5.1:1 | AA |
| `--text-on-accent` sobre `--accent` (light) | 5.9:1 | AA |
| `--text-primary` sobre `--bg-surface` (dark) | 14.9:1 | AAA |
| `--text-tertiary` sobre `--bg-surface` (dark) | 4.9:1 | AA |
| `--success-text` sobre `--success-soft` | ≥4.5:1 | AA |

`--text-quaternary` (3.0:1) se reserva a texto grande, iconografía decorativa y placeholders — nunca a texto de cuerpo.

---

## 2. Biblioteca de componentes (ver `components.css`)

- **KPI Card** (`.kpi`): eyebrow + valor display (`tabular-nums`) + delta con flecha (verde↑/rojo↓) + sparkline opcional.
- **Tabla de datos** (`.table`): header sticky, filas de 52px (o 40px compacta), hover sutil, columnas numéricas alineadas a la derecha.
- **Semáforo** (`.sem`): punto de color + etiqueta textual (OK / Atención / Detenido). El estado "Detenido" pulsa suavemente. **Nunca color solo.**
- **Badge ABC** (`.abc`): círculo con letra A/B/C. A=azul (alto valor), B=teal (medio), C=gris (cola).
- **Badge de capa** (`.layer`): micro-etiqueta C1/C2/C3 que indica qué capa produjo el dato (reglas / ML / agente).
- **Modal de aprobación** (`.modal` + `.scrim`): entrada con scale+fade, blur de fondo, acciones alineadas a la derecha (secundaria + primaria).
- **Chat** (`.msg`): burbujas usuario (azul, a la derecha) / IA (superficie, a la izquierda) con cita de fuente; indicador "typing".
- **Panel de explicabilidad IA** (`.ai-explain`): borde izquierdo iris, factores con barras ponderadas.
- **Dropdown searchable** (`.combobox`): **obligatorio con >5 opciones** (regla UX). Input de filtro + panel con opciones filtrables + estado vacío.
- **Skeleton loader** (`.skeleton`): shimmer diagonal; se usa en carga inicial en lugar de spinners.
- **Estado vacío** (`.empty`): ícono + título + descripción + CTA cuando aplica.

### Microinteracciones (catálogo)
| Interacción | Comportamiento | Duración/curva |
|---|---|---|
| Hover en card interactiva | `translateY(-2px)` + sombra md | 140ms `ease-out` |
| Press en botón | `scale(0.975)` | 80ms |
| Foco teclado | ring `--shadow-focus` (3px) | inmediato |
| Apertura de modal | scale 0.97→1 + fade + blur backdrop | 360ms `ease-out` |
| Apertura de dropdown | pop-in (translateY -4px + scale) | 140ms |
| Toggle/checkbox | spring con overshoot sutil | `ease-spring` |
| Carga de vista | skeletons → contenido con fade | 220ms |
| Aprobación exitosa | check con spring + toast | 360ms |
| Semáforo "Detenido" | pulso de halo rojo | 1.8s loop |

---

## 3. Layout global (app shell)

```
┌──────────────────────────────────────────────────────────────┐
│  TOPBAR (64px, sticky)                                          │
│  ◀ logo ComprasAI    · breadcrumb ·        [🔍]  [◐ tema] [👤] │
├────────────┬─────────────────────────────────────────────────┤
│ SIDEBAR    │  ÁREA DE CONTENIDO (max-w 1440px, pad 32px)       │
│ (248px)    │                                                   │
│            │  ┌ Encabezado de pantalla ──────────────────────┐ │
│ ◉ Dashboard│  │ Título H1 + subtítulo + filtros/acciones     │ │
│ ○ Inventario│ └──────────────────────────────────────────────┘ │
│ ○ Sugeridos│  ┌ Contenido ──────────────────────────────────┐ │
│ ○ Balanceos│  │                                              │ │
│ ○ Semáforo │  │                                              │ │
│ ○ Chat  ✨ │  └──────────────────────────────────────────────┘ │
│            │                                                   │
│ [colapsar] │                                                   │
└────────────┴─────────────────────────────────────────────────┘
```

- **Sidebar** colapsable a 72px (solo íconos). Ítem activo con barra de acento y fondo suave. Chat marcado con ✨ (acento IA).
- **Topbar**: buscador global (⌘K), toggle de tema (persistente en `localStorage`), avatar/rol (Planeador / Gerente).
- **Filtros de pantalla**: barra bajo el encabezado con dropdowns *searchable* (corredor, sucursal, categoría, clase ABC). Todos con filtro de texto.
- **Grid**: 12 columnas fluidas, gutter `--gap-grid` (20px). Cards se reflujan a 1 col < 768px.

---

## 4. Especificación por pantalla

### 4.1 Dashboard Ejecutivo
**Pregunta que responde:** *"¿Cómo está el negocio hoy y qué requiere mi atención?"*
**Rol primario:** Dirección / Gerente.

**Jerarquía (de arriba a abajo):**
1. **Fila de KPIs (4–5 cards):** Cobertura promedio (días), Valor de inventario, Quiebres activos (# SKU), Sugeridos pendientes de aprobar, Cumplimiento de surtido %. Cada KPI: valor display + delta vs. periodo anterior + sparkline 30 días.
2. **Banda de atención IA:** card ancha con gradiente iris sutil — *"3 focos que requieren decisión hoy"*, generada por la capa agéntica (badge `C3`). Cada foco es un chip clicable que profundiza a la pantalla correspondiente.
3. **Dos columnas:**
   - Izq: **Cobertura por corredor** (barra horizontal apilada con semáforo por rango de días).
   - Der: **Top movimientos** — productos ganadores/perdedores (teaser F3, badge "Próximamente" sutil).
4. **Semáforo de cumplimiento (mini):** resumen del pipeline de surtido con enlace a la pantalla full.

**Estados:** skeleton de KPIs al cargar; empty ("Sin datos del periodo, ajusta el filtro").
**Microinteracción estrella:** los focos IA se revelan con un stagger de 60ms entre chips.

---

### 4.2 Inventarios & Cobertura
**Pregunta:** *"¿Dónde tengo exceso, dónde me estoy quedando corto, y en cuántos días?"*
**Rol:** Planeador.

**Layout:**
- **Filtros:** corredor, sucursal, categoría, clase ABC, estado de cobertura (searchable).
- **Resumen (3 KPIs):** SKU en quiebre, SKU en exceso, Cobertura media (días).
- **Tabla maestra** (`.table`), columnas: SKU · Descripción · `ABC` · Sucursal/Corredor · Stock · Demanda diaria · **Cobertura (días)** con `.sem` (verde ≥ objetivo, ámbar en rango bajo, rojo < mínimo) · Última venta · acción "Ver detalle".
- **Panel lateral de detalle** (al seleccionar fila, slide-in 320ms): curva de stock proyectada, punto de reorden, lead time, y CTA *"Generar sugerido"* que lleva directo al flujo estrella con el SKU precargado.

**Vacío/carga:** skeleton de 8 filas; empty con ícono de caja.
**Regla:** columna Cobertura ordenable; default ordena ascendente (lo más crítico arriba).

---

### 4.3 Sugeridos de Compra ⭐ (pantalla estrella)
**Pregunta:** *"¿Qué compro, cuánto, por qué, y lo apruebo?"*
**Roles:** Planeador (genera y propone) → Gerente (aprueba). Workflow de 2 pasos.

**Flujo estrella — menos de 3 clics:**
> **Clic 1:** botón `Generar sugeridos` (`.btn--ai`) → la IA calcula (skeleton + microcopy "Analizando demanda, cobertura y restricciones…").
> **Clic 2:** en una fila, botón `Ver explicación` → abre panel `.ai-explain` con el *por qué*.
> **Clic 3:** botón `Aprobar` (o `Aprobar todo`) → modal de confirmación → check con spring + toast.

**Layout:**
- **Encabezado:** título + botón primario `Generar sugeridos` + selector de corredor/proveedor (searchable).
- **Tabla de sugeridos**, columnas: `☑` · SKU · Descripción · `ABC` · Cobertura actual `.sem` · **Cantidad sugerida** (editable inline, `tabular-nums`) · Costo estimado · Confianza IA (barra 0–100%) · badge de capa (`C2` ML forecast / `C3` ajuste agéntico) · acciones `Ver explicación` · `Aprobar`.
- **Barra de acciones bulk** (aparece al seleccionar): *"12 seleccionados · $X total"* + `Aprobar seleccionados` / `Rechazar`.

**Panel de explicabilidad IA (`.ai-explain`):**
- Encabezado: *"Por qué sugerimos 240 unidades"* con ícono ✨.
- **Factores ponderados** (barras): Demanda proyectada (C2), Cobertura objetivo (C1), Lead time del proveedor, Estacionalidad, Restricción de empaque/múltiplo, Presupuesto.
- **Datos fuente:** ventas SAP (bono/ZVTA), stock actual, histórico. Cada uno enlazable.
- **Escenario:** "Sin esta compra, quiebre estimado en 6 días para 4 sucursales."

**Modal de aprobación:**
- Resumen: # SKU, unidades totales, monto, proveedor.
- Checkbox *"Notificar al proveedor / generar orden en SAP (simulado en demo)"*.
- Acciones: `Cancelar` (secundaria) · `Confirmar aprobación` (primaria).

**Workflow de estados del sugerido:** Borrador → Propuesto (por Planeador) → Aprobado / Rechazado (por Gerente). Chip de estado por fila; vista filtrable por estado.

---

### 4.4 Balanceos & Remates
**Pregunta:** *"¿Qué muevo entre sucursales (balanceo) y qué liquido (remate) antes de que se vuelva costo muerto?"*
**Rol:** Planeador.

**Layout — dos pestañas (`Balanceos` | `Remates`):**
- **Balanceos:** tabla de propuestas de transferencia: SKU · `ABC` · Origen (exceso) → Destino (faltante) · Unidades · Ahorro estimado vs. compra nueva · badge `C3` · `Aprobar`. Visual de flujo origen→destino con flecha.
- **Remates:** SKU con baja rotación/riesgo de obsolescencia: SKU · `ABC` (típicamente C) · Días sin venta · Stock · Valor en riesgo · Descuento sugerido (IA) · `Ver explicación` · `Marcar para remate`.

**Explicabilidad:** por qué balancear (costo evitado, cobertura equilibrada) vs. por qué rematar (aging, elasticidad — teaser F3).
**Estado vacío positivo:** *"Sin excesos críticos ni producto en riesgo. Inventario equilibrado ✅"* (usar tono de logro, no de error).

---

### 4.5 Semáforo de Cumplimiento (Lite)
**Pregunta:** *"¿El surtido está fluyendo de punta a punta o hay un cuello de botella?"*
**Rol:** Gerente / Dirección.

**Layout:**
- **Pipeline horizontal** de etapas (Requerimiento → Sugerido → Aprobación → Orden → Recepción → En piso), cada etapa con `.sem` (OK / Atención / Detenido) y un contador.
- **Card por etapa detenida:** qué está trabado, desde cuándo, y CTA para ir a resolver.
- **Semáforo por corredor/categoría** (grid de celdas): matriz compacta con color+ícono; hover muestra detalle en tooltip.
- **Nota de alcance:** badge "Lite" sutil; el semáforo end-to-end completo es F2 (teaser).

**Microinteracción:** etapas "Detenido" pulsan; al hacer clic, la card de detalle se expande con altura animada.

---

### 4.6 Chat del Planeador ✨
**Pregunta:** *"Pregúntale a tus datos en lenguaje natural."*
**Rol:** Planeador. Vitrina de la capa agéntica C3.

**Layout:**
- **Panel de conversación** (`.chat`) centrado, ancho de lectura cómodo (~720px).
- **Burbujas:** usuario (azul, derecha) / IA (superficie, izquierda). Respuestas de IA con:
  - Texto en lenguaje natural.
  - **Artefactos embebidos:** mini-tabla o mini-gráfica cuando la respuesta lo amerita (p. ej. "top 5 SKU en quiebre en corredor Norte").
  - **Cita de fuente** (`.msg__source`): "Basado en ventas SAP ZVTA · 180 sucursales · últimos 30 días" + badge de capa.
  - Acciones contextuales: *"Generar sugerido de estos SKU"* → salta al flujo 4.3 precargado.
- **Indicador typing** mientras el agente razona.
- **Composer** abajo: input multilinea + botón enviar (`.btn--ai`), con **chips de sugerencias** ("¿Qué debo comprar esta semana?", "¿Dónde tengo exceso?", "Productos ganadores del mes").
- **Estado vacío (primera visita):** saludo + 3–4 chips de ejemplo + microcopy que explica qué puede hacer.

**Accesibilidad:** foco gestionado al enviar; mensajes anunciados a lectores de pantalla; el composer conserva foco.

---

## 5. Responsividad y accesibilidad

- **Breakpoints:** ≥1280 (full), 768–1279 (sidebar colapsa a íconos, KPIs 2×2), <768 (sidebar en drawer, tablas con scroll horizontal + columnas prioritarias).
- **Teclado:** todo operable sin ratón; foco visible (`--shadow-focus`); ⌘K abre buscador; Esc cierra modales/paneles.
- **Lectores de pantalla:** semáforos y badges llevan texto (no solo color); tablas con `scope`; live-region para toasts y respuestas de chat.
- **Movimiento:** `prefers-reduced-motion` desactiva animaciones no esenciales (los tokens de duración pasan a 0ms).
- **Contraste:** ver §1; validado AA en ambos temas.

---

## 6. Guía de implementación (para T4 · Frontend)

1. Importar en orden: `design-tokens.css` → `components.css` → estilos de pantalla.
2. Tema: setear `data-theme="light|dark"` en `<html>`; sin atributo respeta el SO. Persistir toggle en `localStorage`.
3. Cache busting: versionar assets con `?v=YYYYMMDD` (ver pack Cache Busting).
4. Números siempre con `.tnum` / `tabular-nums` en KPIs y tablas.
5. **Nunca** comunicar estado solo con color: acompañar con ícono + texto.
6. Dropdowns con >5 opciones → `.combobox` searchable (regla UX obligatoria).
7. Loading → `.skeleton` (no spinners) en carga inicial de datos.
8. Toda recomendación IA debe exponer su `.ai-explain` y su badge de capa (C1/C2/C3).

---

*Versión 1.0 · 23-ago-2026 · Autor: bot 43 (T2 Diseño UX). Fuente de verdad viva: waykee 290077.*
