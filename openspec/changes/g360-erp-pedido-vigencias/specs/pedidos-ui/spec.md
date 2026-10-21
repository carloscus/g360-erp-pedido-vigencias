## Purpose

Presenta los datos de vigencias en un dashboard Flet desktop interactivo con búsqueda, filtros, KPIs y export XLSX estructurado para presentaciones y pivot manual.

## ADDED Requirements

### Requirement: Layout con sidebar y área principal
El sistema SHALL presentar un layout con sidebar izquierdo (navegación, filtros, archivos cargados) y área principal (KPIs, tabla dinámica, resultados de búsqueda).

#### Scenario: Primera apertura de la app
- **WHEN** el usuario inicia la aplicación
- **THEN** se muestra el layout con sidebar oscuro CIPSA, header con logo, zona de KPIs vacía, y mensaje de bienvenida invitando a cargar archivos

### Requirement: Barra de búsqueda multi-campo
El sistema SHALL tener una barra de búsqueda prominente que acepte: OC/número de documento, nombre de cliente, SKU, nombre de producto, condición de pago, estado de pedido.

#### Scenario: Búsqueda por SKU
- **WHEN** el usuario escribe 02187 en la barra de búsqueda
- **THEN** la tabla filtra y muestra las filas con SKU 02187, incluyendo nombre, categoría, saldo, cajas

#### Scenario: Búsqueda por cliente
- **WHEN** el usuario escribe Tottus en la barra de búsqueda
- **THEN** la tabla muestra todas las filas del cliente cuyo nombre contiene Tottus

#### Scenario: Búsqueda vacía
- **WHEN** el usuario limpia la barra de búsqueda
- **THEN** la tabla restaura la vista completa con todos los registros

### Requirement: Filtros laterales
El sistema SHALL proporcionar filtros dropdown en el sidebar para: Categoría (VINIBALL/VINIFAN/REPRESENTADAS/Todas), Estado Línea, Almacén, Condición de Pago, Vendedor.

#### Scenario: Filtro por categoría VINIBALL
- **WHEN** el usuario selecciona VINIBALL en el filtro categoría
- **THEN** la tabla muestra solo los 2,256 items de VINIBALL y los KPIs se actualizan

#### Scenario: Filtro múltiple combinado
- **WHEN** el usuario selecciona categoría VINIFAN + almacén VES + condición CONTADO
- **THEN** la tabla muestra solo los items que cumplen las tres condiciones simultáneamente

### Requirement: KPIs en tiempo real
El sistema SHALL mostrar tarjetas KPI en la parte superior que se actualicen con cada filtro/búsqueda: total items, saldo units, valor S/, cajas pendientes, % despacho global.

#### Scenario: Actualización de KPIs al filtrar
- **WHEN** el usuario aplica un filtro que reduce los resultados a 500 items
- **THEN** los KPIs muestran los valores agregados de esos 500 items (saldo, valor, cajas)

### Requirement: Tabla dinámica con paginación
El sistema SHALL mostrar los datos en una tabla con columnas: SKU, Categoría, Estado Línea, Artículo, Cliente, Vendedor, Almacén, Pedido, Despachado, Saldo, % Atendido, Cajas, Valor S/, Condición Pago. Paginación de 100 filas por página.

#### Scenario: Navegación de páginas
- **WHEN** hay más de 100 filas que cumplen los filtros
- **THEN** se muestran 100 filas por página con controles de navegación

#### Scenario: Ordenamiento de columnas
- **WHEN** el usuario hace clic en el header de la columna Saldo
- **THEN** la tabla se ordena descendente por saldo (mayor pendiente primero)

### Requirement: Sección de alertas QC
El sistema SHALL mostrar una sección destacada con las alertas de SKUs con saldo > 5,000 units en VES como candidatos a liberación desde QC 121.

#### Scenario: Visualización de alertas QC
- **WHEN** se cargan datos y hay 594 SKUs con saldo > 5,000
- **THEN** se muestra un badge con 594 alertas QC y al hacer clic se expande la lista con SKU, artículo, saldo, cajas

### Requirement: Export XLSX con hojas estructuradas
El sistema SHALL exportar a XLSX con las siguientes hojas: RESUMEN (KPIs agregados), POR_CLIENTE (agrupado por cliente), POR_VENDEDOR (agrupado por vendedor), DETALLE (filas completas con todas las columnas), ALERTAS_QC (SKUs con saldo > 5,000). Cada hoja SHALL tener encabezados formateados y datos estructurados para pivot manual.

#### Scenario: Export con resumen y detalle
- **WHEN** el usuario clickea Exportar XLSX
- **THEN** se genera un archivo con 5 hojas: Resumen, Por Cliente, Por Vendedor, Detalle, Alertas QC

#### Scenario: Hoja Detalle incluye fórmulas
- **WHEN** se exporta la hoja DETALLE
- **THEN** incluye columnas calculadas (saldo, por_atendido, cajas, valor_saldo) como fórmulas Excel para que el usuario pueda modificarlas

#### Scenario: Timestamp en el nombre del archivo
- **WHEN** se exporta el archivo
- **THEN** el nombre incluye la fecha/hora: pedidos_vigencias_20260813_153200.xlsx

### Requirement: Brand CIPSA
El sistema SHALL usar la paleta de colores CIPSA (accent #10B981 dark, #047857 light) con glassmorphism, siguiendo el estándar visual de g360-erp-stock-monitor.

#### Scenario: Modo oscuro CIPSA
- **WHEN** la app inicia en modo oscuro (default)
- **THEN** el fondo es #0A0F1E, surface #141D33, accent #10B981, texto #F1F5FB

#### Scenario: Toggle modo claro/oscuro
- **WHEN** el usuario clickea el botón de tema
- **THEN** cambia entre modo oscuro y claro manteniendo la paleta CIPSA
