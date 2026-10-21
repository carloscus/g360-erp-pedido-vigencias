## Context

La app debe crearse en C:\\Users\\ccusi\\Documents\\Proyect_Coder\\G360-ecosystem\\projects\\g360-erp-pedido-vigencias/ como proyecto local dentro del ecosistema G360. Funciona como dashboard Flet desktop para analizar vigencias de pedidos CIPSA. Se basa en archivos XLS/XLSX exportados desde el ERP que contienen columns como ID_ARTICULO, CAN_PEDIDO, CAN_DESPACHO, VIGENCIA, NOM_ALMACEN, CONDICION_PAGO, etc. El enrichment se hace con dos fuentes: catálogo maestro local (JSON de g360-master-data) y API G360 Stock en Render.

El SKU es el campo critico: viene como texto preservado del archivo (dtype=str), y el catalogo contiene SKUs de 5 y 6 digitos coexistentes. No se aplica padding - matching directo.

## Goals / Non-Goals

**Goals:**
- Ingestar multiples archivos XLS/XLSX de vigencias con SKU preservado como texto
- Enriquecer con catalogo maestro y stock API
- Dashboard interactivo con busqueda multi-campo y filtros
- Export XLSX estructurado con hojas para pivot y presentaciones
- Alertas QC (saldo > 5000 units en VES como candidatos a liberacion 121)

**Non-Goals:**
- Ejecutar traslados reales entre almacenes (solo alerta)
- Modificar el ERP o la API G360 Stock
- Soporte para formatos de archivo distintos a XLS/XLSX
- Query con IA (busqueda por keywords + filtros visuales)
- Multiples usuarios concurrentes (app desktop local)

## Decisions

### 1. Estructura del proyecto
**Decision:** App monolitica Flet con estructura clara de modulos, inspirada en g360-erp-stock-monitor.

g360-erp-pedido-vigencias/   (path: C:\\Users\\ccusi\\Documents\\Proyect_Coder\\G360-ecosystem\\projects\\)
+-- main.py                    # Entry point (ft.app pattern)
+-- pyproject.toml
+-- requirements.txt
+-- src/
|   +-- __init__.py
|   +-- app.py                 # App class, page setup
|   +-- config/
|   |   +-- __init__.py
|   |   +-- settings.py        # API URL, cache, categorias
|   |   +-- theme.py           # Paleta CIPSA (dark/light)
|   +-- core/
|   |   +-- __init__.py
|   |   +-- ingest.py          # Read XLS, SKU preservation, enrichment
|   |   +-- analytics.py       # KPIs, segmentacion, alerts, queries
|   |   +-- exporters.py       # XLSX export (5 hojas, formulas)
|   +-- ui/
|       +-- __init__.py
|       +-- dashboard.py       # Main layout: sidebar + KPIs + table
|       +-- upload_view.py     # FilePicker + drag-drop
|       +-- filters.py         # Sidebar filters (cat, alm, pago, vendedor)
|       +-- query_bar.py       # Multi-field search bar

**Alternative considered:** Usar g360-cli como dependencia. **Rejected** because user wants independent repo; g360-cli referenced as knowledge source (segmentation) not as dependency.

### 2. SKU matching
**Decision:** Lectura con pd.read_excel(..., dtype=str) + matching directo contra catalogo. Sin padding, sin smart_match.

df = pd.read_excel(path, engine=xlrd, dtype=str)
sku = df[ID_ARTICULO]  # 01240 stays 01240, 011019 stays 011019
# Direct match
categoria = sku.map(catalog_dict.get).map(lambda x: x[categoria] if x else )

**Alternative considered:** Smart matching (raw -> pad5 -> pad6). **Rejected** because ERP data already comes with correct format; padding was an initial error.

### 3. API Stock: batch vs individual
**Decision:** Batch query por SKU usando endpoint /api/v1/stock?search={sku} with parallelization limited (max 10 concurrent) to not overload Render. Local cache 15 min.

**Alternative considered:** Mass query without filter. **Rejected** because API does not support bulk multi-SKU in single request; must iterate.

### 4. Export XLSX con formulas
**Decision:** Usar openpyxl con formulas Excel en hoja DETALLE para campos calculados (saldo, por_atendido, cajas). Hojas RESUMEN y POR_CLIENTE con datos agregados listos para pivot.

**Alternative considered:** Generate CSV. **Rejected** because user needs Excel formulas and pivot.

### 5. Query natural
**Decision:** Regex simple parser, no AI. Keywords detected: categorias (VINIBALL/VINIFAN/REPRESENTADAS), known fields (cliente, SKU, cajas, condiciones de pago). Parser extracts tokens and builds composite filters.

**Alternative considered:** LLM-based query. **Rejected** because overkill for internal dashboard; regex is faster and predictable.

## Risks / Trade-offs

- **API Render downtime** -> Mitigation: app works 100% offline with XLS data; stock API is optional enrichment. Shows badge API offline and continues.
- **Catalog outdated** -> Mitigation: last update timestamp visible in UI; manual refresh button.
- **19K+ rows in memory** -> Mitigation: pagination 100 rows, lazy loading. Pandas handles 19K rows without problem (~15MB RAM).
- **SKU without catalog (7-22% of data)** -> Mitigation: Sin Catalogo section in alerts; user can import updated catalog.
- **Multi-period without FECHA column** -> Mitigation: app groups by loaded file; if user loads vig_hoy + vig_mes, each row marked with source filename.

## Open Questions

Ninguna - todas las decisiones estan resueltas in this exploration.

## Migration Plan

1. Crear directorio local C:\\Users\\ccusi\\Documents\\Proyect_Coder\\G360-ecosystem\\projects\\g360-erp-pedido-vigencias/
2. Scaffold con estructura de carpetas + pyproject.toml
3. Implementar core (ingest + analytics) primero, validar con vig_hoy.xls
4. Implementar UI (dashboard + filtros + busqueda)
5. Implementar exporters (XLSX 5 hojas)
6. Testing manual con archivos reales
7. CI basico con GitHub Actions (pytest + ruff)
8. Publicar portable build (zip con uv)

No hay migracion - es un proyecto nuevo.