## Purpose

Analiza los pedidos de vigencias consolidados para extraer saldos pendientes, segmentación por categoría/linea/cliente/vendedor/almacén/condición de pago, y alertas de prioridad basadas en stock disponible y almacenes.

## ADDED Requirements

### Requirement: KPIs globales
El sistema SHALL calcular y mostrar KPIs globales: total items, total pedido unidades, total despachado, saldo pendiente unidades, total cajas pendientes, valor total en soles, cantidad de clientes, vendedores y almacenes.

#### Scenario: Cálculo de KPIs desde vig hoy
- **WHEN** se carga vig hoy.xls (19,314 filas)
- **THEN** se muestran: ~15.9M unidades pedidas, ~483K despachadas, ~15.5M saldo, ~1.97M cajas pendientes, S/ 67.98M valor total, 925 clientes, 63 vendedores, 23 almacenes

### Requirement: Segmentación por categoría de negocio
El sistema SHALL permitir filtrar y agrupar por las tres categorías principales: VINIBALL, VINIFAN, REPRESENTADAS, mostrando para cada una: items, pedido units, despachado, saldo, valor S/, cajas pendientes.

#### Scenario: Filtrar VINIBALL
- **WHEN** el usuario selecciona el filtro categoria = VINIBALL
- **THEN** se muestran 2,256 items con saldo de 602,436 units y valor S/ 3,376,353

#### Scenario: Filtrar VINIFAN
- **WHEN** el usuario selecciona el filtro categoria = VINIFAN
- **THEN** se muestran 11,953 items con saldo de 12,874,897 units y valor S/ 50,732,639

#### Scenario: Filtrar REPRESENTADAS
- **WHEN** el usuario selecciona el filtro categoria = REPRESENTADAS
- **THEN** se muestran 824 items con saldo de 479,857 units y valor S/ 3,016,285

### Requirement: Segmentación por estado_linea
El sistema SHALL desglosar cada categoría por estado_linea (NUEVO, TRADICIONAL, IMPORTADO, vacío) con sus propios KPIs.

#### Scenario: VINIFAN por estado_linea
- **WHEN** se filtra VINIFAN y se desglosa por estado_linea
- **THEN** se muestra: NUEVO (8,962 items, saldo 9,244,849), TRADICIONAL (2,926 items, saldo 3,587,267), IMPORTADO (48 items, saldo 7,788)

### Requirement: Query natural por categoría + cliente
El sistema SHALL responder queries como VINIFAN cliente 2241 mostrando: total soles, unidades pedido/despachado/saldo, cajas pendientes, desglose por estado_linea.

#### Scenario: Query VINIFAN cliente 2241
- **WHEN** el usuario escribe VINIFAN cliente 2241 en la barra de búsqueda
- **THEN** se muestra: S/ 1,119,569.51 total pedido, 297,301 units saldo, 4,665.9 cajas, desglose NUEVO S/ 726,864.97 / TRADICIONAL S/ 392,704.54

### Requirement: Query natural por SKU y cajas
El sistema SHALL responder queries como cuántas cajas de 02187 debemos calculando cajas pendientes desde el saldo.

#### Scenario: Query cajas de 02187
- **WHEN** el usuario escribe 02187 cajas o cuántas cajas de 02187
- **THEN** se muestra: SKU 02187, FORRO N VINIFORRITO CRISTAL 20-25, VINIFAN/TRADICIONAL, 4,901 units pendientes, 49.0 cajas

### Requirement: Alerta QC (almacén 121)
El sistema SHALL detectar SKUs con saldo pendiente > 5,000 units en el almacén VES como candidatos a solicitud de liberación desde almacén QC 121. Esta es solo una alerta, no ejecuta el traslado.

#### Scenario: Detección de alertas QC
- **WHEN** se procesan los datos y se identifican SKUs con saldo > 5,000 en VES
- **THEN** se muestra una sección de alertas con los SKUs, sus saldos, cajas equivalentes y categoría

#### Scenario: Top alertas QC
- **WHEN** hay 594 SKUs con saldo > 5,000 en VES
- **THEN** se muestran ordenados por saldo descendente, con los top 5 visibles inicialmente

### Requirement: Segmentación por condición de pago
El sistema SHALL agrupar por CONDICION_PAGO mostrando items, unidades y valor total para cada condición (CONTADO, FACTURA 60 DIAS, ANTICIPO EN LETRAS, etc.).

#### Scenario: Condición CONTADO
- **WHEN** se filtra por CONDICION_PAGO = CONTADO
- **THEN** se muestran ~4,231 items con valor total S/ 28,726,756 (mayor contribuidor)

#### Scenario: Condición ANTICIPO EN LETRAS
- **WHEN** se filtra por CONDICION_PAGO = ANTICIPO EN LETRAS
- **THEN** se muestran ~499 items con valor S/ 1,537,256 — prioridad alta para seguimiento de despacho

### Requirement: Segmentación por almacén
El sistema SHALL permitir filtrar por NOM_ALMACEN (VES, CIPTECH, EXPORTACION, SUCURSALES, etc.) y mostrar KPIs por almacén.

#### Scenario: Filtrar VES
- **WHEN** se selecciona almacén CENTRO LOGISTICO VES
- **THEN** se muestran ~15,901 items con valor S/ 64,408,321

### Requirement: Ranking de clientes por saldo
El sistema SHALL mostrar ranking de clientes por saldo pendiente en unidades y valor en soles.

#### Scenario: Top clientes por saldo
- **WHEN** se solicita ranking de clientes
- **THEN** se muestra: 1) Corporación Industrias Plas (6,749,648 units, S/ 33.4M), 2) Tottus (1,910,411 units, S/ 8.4M), 3) Supermercados Peruanos (1,331,394 units, S/ 5.8M)

### Requirement: Búsqueda multi-campo
El sistema SHALL permitir buscar por: NRO_DOCUMENTO (OC), COD_CLIENTE/NOM_CLIENTE, ID_ARTICULO/SKU, NOM_ARTICULO, PEDIDO_ESTADO, CONDICION_PAGO, NOM_VENDEDOR.

#### Scenario: Búsqueda por OC
- **WHEN** el usuario escribe un NRO_DOCUMENTO (ej: 20481150125)
- **THEN** se filtran todas las filas con ese número de documento

#### Scenario: Búsqueda por nombre de producto
- **WHEN** el usuario escribe viniball en la barra de búsqueda
- **THEN** se muestran todas las filas cuyo NOM_ARTICULO o SKU contiene viniball

#### Scenario: Búsqueda por condición de pago
- **WHEN** el usuario escribe contado en la barra de búsqueda
- **THEN** se muestran todas las filas con CONDICION_PAGO = CONTADO
