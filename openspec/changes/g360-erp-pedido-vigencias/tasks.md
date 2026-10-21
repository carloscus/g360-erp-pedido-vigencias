## 1. Scaffold del proyecto

- [x] Crear directorio local en C:\\Users\\ccusi\\Documents\\Proyect_Coder\\G360-ecosystem\\projects\\g360-erp-pedido-vigencias/ con estructura de carpetas (src/app.py, src/config/, src/core/, src/ui/, tests/)
- [x] Crear main.py con patrón ft.app(main, view=ft.AppView.FLET_APP) y logger RotatingFileHandler
- [x] Crear pyproject.toml con dependencies: flet[desktop], pandas, xlrd, openpyxl, requests, pydantic-settings
- [x] Crear .gitignore (venv, __pycache__, .env, dist/, .venv/, run_log.txt, .cache/)
- [x] Configurar Git init + README.md con instrucciones de setup (pip install -r requirements.txt, python main.py)

## 2. Configuración y theme

- [x] Crear src/config/settings.py con S1_API_URL, S1_API_KEY, CACHE_TTL, PRIMARY_CATEGORIES, ALMACENES_PRIORIDAD, ALERTA_QC_THRESHOLD=5000
- [x] Crear src/config/theme.py con paleta CIPSA dark (#0A0F1E bg, #141D33 surface, #10B981 accent) y light mode
- [x] Crear src/config/__init__.py que exporta settings y theme

## 3. Core: ingest.py

- [x] Crear clase Ingester con método load_file(path) que lee XLS/XLSX con dtype=str y retorna DataFrame
- [x] Implementar detección automática de motor (xlrd para .xls, openpyxl para .xlsx)
- [x] Implementar load_multiple(paths) que concatena múltiples archivos marcando cada fila con su fuente
- [x] Crear función enrich_with_catalog(df, catalog_path) que hace matching SKU directo (sin padding) y agrega categoria, estado_linea, un_bx, nombre_catalogo
- [x] Crear función enrich_with_stock_api(df, api_url, api_key) que consulta stock API por SKU en batch (max 10 concurrentes) y agrega stock_api_disponible
- [x] Crear función compute_derived(df) que calcula: saldo, por_atendido, por_pendiente, cajas, valor_saldo
- [x] Crear función detect_unmatched(df) que identifica SKUs sin catálogo y sin stock API

## 4. Core: analytics.py

- [x] Crear clase PedidosAnalytics con constructor que recibe DataFrame enriquecido
- [x] Implementar get_kpis() que retorna dict con: total_items, total_pedido, total_despachado, saldo_total, cajas_total, valor_total, n_clientes, n_vendedores, n_almacenes
- [x] Implementar get_by_category() que retorna DataFrame agrupado por categoria con items, pedido, desp, saldo, valor, cajas
- [x] Implementar get_by_estado_linea(categoria) que desglosa una categoría por NUEVO/TRADICIONAL/IMPORTADO
- [x] Implementar get_by_cliente() que retorna ranking de clientes por saldo units y valor
- [x] Implementar get_by_vendedor() que retorna resumen por vendedor
- [x] Implementar get_by_almacen() que retorna KPIs por almacén
- [x] Implementar get_by_condition_payment() que retorna agrupado por CONDICION_PAGO
- [x] Implementar get_qc_alerts(threshold=5000) que retorna SKUs con saldo > threshold en VES
- [x] Implementar query_natural(text) que parsea keywords y aplica filtros compuestos retornando DataFrame filtrado + explicación textual
- [x] Implementar get_vinifan_client_summary(client_id) que responde la query de ejemplo: soles, units, cajas, estado_linea breakdown
- [x] Implementar get_sku_box_query(sku) que responde cuántas cajas de un SKU específico se deben

## 5. UI: upload_view.py

- [x] Crear UploadView con FilePicker ref, drag-and-drop zone, lista de archivos cargados, botón procesar
- [x] Reutilizar patrón de g360-erp-preorder-allocator/src/ui/upload_view.py (DropZone, ActionBtn, FileItem)
- [x] Al procesar, llamar Ingester.load_multiple() en thread separado con ProgressBar
- [x] Emitir callback on_processed(df_enriched) cuando termine

## 6. UI: filters.py

- [x] Crear FiltersPanel con dropdowns: Categoria (Todas/VINIBALL/VINIFAN/REPRESENTADAS), Estado Línea, Almacén, Condición Pago, Vendedor
- [x] Cada filtro actualiza el estado reactivo y dispara reconstrucción de tabla + KPIs
- [x] Filtros combinables (AND lógico)
- [x] Botón Limpiar filtros que restaura vista completa

## 7. UI: query_bar.py

- [x] Crear QueryBar con TextField amplio, icono de búsqueda, placeholder dinámico
- [x] Al enviar, llamar analytics.query_natural(text) y actualizar tabla + mostrar resultado textual
- [x] Soportar keywords: nombres de categorías, cajas, cliente, vendedor, nombres de condiciones de pago
- [x] Si no hay match, mostrar mensaje amigable con sugerencias

## 8. UI: dashboard.py

- [x] Crear Dashboard principal con layout: sidebar (izq) + main content (der)
- [x] Sidebar: logo CIPSA, navegación (Dashboard, Alertas QC, Sin Catálogo), filtros, lista de archivos
- [x] Main: header con barra de búsqueda + botón refresh API + toggle tema
- [x] KPI row: 5 tarjetas (Items, Saldo Units, Valor S/, Cajas, % Despacho)
- [x] Tabla dinámica con VirtualScroll (paginación 100 filas), ordenamiento por clic en header
- [x] Sección alertas QC expandible con top 5 y badge contador
- [x] Status bar inferior: timestamp última carga, cantidad archivos, modo API (online/offline)
- [x] Reutilizar patrón de g360-erp-stock-monitor/src/ui/dashboard.py (sidebar chips, KPI row, search)

## 9. Core: exporters.py

- [x] Crear función export_to_xlsx(df, output_path) que genera XLSX con 5 hojas
- [x] Hoja RESUMEN: KPIs globales + tabla por categoría con fórmulas Excel
- [x] Hoja POR_CLIENTE: agrupado por COD_CLIENTE + NOM_CLIENTE con columns: Categoria, Items, Saldo, Cajas, Valor S/, Cond_Pago
- [x] Hoja POR_VENDEDOR: agrupado por ID_VENDEDOR + NOM_VENDEDOR
- [x] Hoja DETALLE: todas las filas con todas las columnas, fórmulas en columnas calculadas (saldo=D-E, por_atendido=E/D*100, cajas=F/G)
- [x] Hoja ALERTAS_QC: SKUs con saldo > 5000 ordenados por saldo descendente
- [x] Nombre de archivo: pedidos_vigencias_YYYYMMDD_HHMMSS.xlsx
- [x] Formato: header fill #10B981, white font bold, freeze panes, auto-width columns

## 10. App integration

- [x] Crear src/app.py que orquesta: carga settings, inicia Dashboard, conecta UploadView → Ingester → Analytics → Exporters
- [x] Manejar errores de API (timeout, 403, sin conexión) con mensaje al usuario
- [x] Cache local de resultados de API en .cache/ con TTL 15 min
- [x] Log rotativo a run_log.txt (máx 2MB, 3 backups)
- [x] On close: save cache, log shutdown

## 11. Testing

- [x] Crear tests/test_ingest.py: pruebas de dtype=str, matching SKU, enrichment catálogo
- [x] Crear tests/test_analytics.py: pruebas de KPIs, segmentación, query natural
- [x] Crear tests/test_exporters.py: pruebas de generación XLSX, fórmulas, hojas
- [x] Crear tests/test_sku_match.py: validación de que 01240 no se confunde con 001240
- [x] Correr tests con pytest

## 12. Packaging

- [x] Crear build.bat con python main.py
- [x] Crear launch.vbs para ejecutar minimizado
- [x] Crear script de build portable con PyInstaller (opcional)
- [x] Configurar Git remote + GitHub Actions: test + lint (ruff) en push/main (opcional, proyecto local primero)