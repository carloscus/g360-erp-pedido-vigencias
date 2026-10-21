## Why

El equipo de Compras CIPSA maneja reportes de vigencias de pedidos (XLS/XLSX) con miles de SKUs, múltiples clientes y vendedores, pero no existe una herramienta que consolide estos archivos, los enriquezca con el catálogo maestro y el stock en tiempo real del API G360, y presente saldos pendientes, cajas por entregar y alertas de prioridad (incluyendo QC/almacén 121) de forma interactiva y exportable a XLSX con hojas estructuradas para pivot y presentaciones.

## What Changes

- Nueva app Flet desktop (g360-erp-pedido-vigencias) que ingesta uno o más archivos XLS/XLSX de vigencias del ERP
- Pipeline de ingesta que lee SKUs como texto (dtype=str) sin padding ni transformación, matching directo contra catálogo maestro, y enriquecimiento con stock API
- Motor de análisis que calcula saldos, porcentajes de despacho/pendiente, cajas por entregar, segmentación por categoría/linea/cliente/vendedor/almacén/condición de pago
- Detección de alertas QC: SKUs con saldo > 5,000 units en VES como candidatos a liberación desde almacén 121
- Dashboard Flet con barra de búsqueda multi-campo (OC, cliente, SKU, estado, condición de pago), filtros por categoría/almacén/vendedor, KPIs en tiempo real
- Export XLSX con hojas estructuradas (Resumen, Por Cliente, Por Vendedor, Detalle, Alertas QC) con fórmulas Excel para pivot manual y presentaciones
- App como repositorio local en projects/g360-erp-pedido-vigencias/ (no repositorio GitHub separado)

## Capabilities

### New Capabilities
- pedidos-ingest: ingesta de archivos XLS/XLSX de vigencias ERP, lectura SKU como texto preservado, matching directo contra catálogo maestro, enrichment con datos de stock API
- pedidos-analytics: motor de análisis de pedidos — cálculo de saldos, porcentajes, cajas, segmentación por categoría/linea/cliente/vendedor/almacén/condición de pago, detección de alertas QC
- pedidos-ui: dashboard Flet desktop con barra de búsqueda, filtros, tabla dinámica y export XLSX con hojas estructuradas

### Modified Capabilities

## Impact

- Nuevo repositorio GitHub independiente: g360-erp-pedido-vigencias
- Dependencias: flet[desktop], pandas, xlrd, openpyxl, requests
- Integra con g360-stock-api (Render) para enrichment de stock por SKU y almacén
- Catálogo maestro consumido desde g360-master-data/output/catalogo_productos.json
- Reutiliza patrón UI de g360-erp-stock-monitor (theme, sidebar, KPIs, paginación)
- Reutiliza engine de segmentación de g360-cli/py/src/g360_core/processor_segmentacion.py
- Output: XLSX con fórmulas para pivot manual y presentaciones
