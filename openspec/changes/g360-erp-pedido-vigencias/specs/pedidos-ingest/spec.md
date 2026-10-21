## Purpose

Ingresa archivos XLS/XLSX de vigencias del ERP, preserva los SKUs como texto sin pérdida de ceros a la izquierda, y los enriquece con datos del catálogo maestro y stock del API G360.

## ADDED Requirements

### Requirement: SKU se lee como texto sin transformación
El sistema SHALL leer todas las columnas de los archivos XLS/XLSX como texto (dtype=str) para preservar ceros a la izquierda en SKUs (ej: 01240 no se convierte a 1240).

#### Scenario: Archivo con SKU de 5 dígitos con cero inicial
- **WHEN** el usuario carga fc00845a.xls que contiene ID_ARTICULO = 01240
- **THEN** el sistema retiene el valor como 01240 (string) y no como 1240 (int)

#### Scenario: Archivo con SKU de 6 dígitos
- **WHEN** el usuario carga un archivo con ID_ARTICULO = 011019
- **THEN** el sistema lo retiene como 011019 sin modificar

### Requirement: Matching directo contra catálogo maestro
El sistema SHALL hacer matching del campo ID_ARTICULO (tal como viene en el archivo) contra el catálogo maestro (catalogo_productos.json) sin aplicar padding ni transformación alguna.

#### Scenario: SKU encontrado en catálogo
- **WHEN** el SKU del archivo es 01240 y existe en el catálogo
- **THEN** se asignan categoría (VINIBALL), estado_linea, un_bx, y nombre del catálogo

#### Scenario: SKU no encontrado en catálogo
- **WHEN** el SKU del archivo no existe en el catálogo
- **THEN** se marca como sin_catalogo con categoría vacía y se registra en alerta de productos sin catálogo

#### Scenario: SKU con formato mixto (algunos 5 dig, otros 6 dig)
- **WHEN** un archivo contiene SKUs de diferente longitud (ej: 01240 y 011019)
- **THEN** cada SKU se busca individualmente en el catálogo sin normalización

### Requirement: Enrichment con catálogo maestro
El sistema SHALL completar cada fila con datos del catálogo: categoria, estado_linea, un_bx, nombre_catalogo.

#### Scenario: Producto con datos completos en catálogo
- **WHEN** el SKU 02187 tiene entrada en catálogo con categoria=VINIFAN, un_bx=100, estado_linea=TRADICIONAL
- **THEN** la fila resultante incluye estos campos enriquecidos

#### Scenario: Producto sin datos en catálogo
- **WHEN** el SKU 02202 no tiene entrada en catálogo
- **THEN** la fila se marca con categoria=, un_bx=1, estado_linea=, nombre_catalogo=

### Requirement: Enrichment con stock API
El sistema SHALL consultar el API G360 Stock (/api/v1/stock?search={sku}&almacen={alm}) para obtener stock disponible por almacén y agregarlo como campo stock_api_disponible.

#### Scenario: SKU con stock disponible en VES
- **WHEN** se consulta el SKU 02187 con almacén VES
- **THEN** se agrega stock_api_disponible con el valor retornado por el API

#### Scenario: SKU sin stock en API (no encontrado)
- **WHEN** se consulta un SKU que no existe en el API
- **THEN** stock_api_disponible se setea a 0 y se marca como sin_stock_api

#### Scenario: API no disponible
- **WHEN** el API G360 no responde (timeout o error)
- **THEN** el sistema continúa con los datos del archivo ERP y marca api_unavailable=True

### Requirement: Cálculo de campos derivados
El sistema SHALL calcular las siguientes columnas derivadas para cada fila:
- saldo = CAN_PEDIDO - CAN_DESPACHO
- por_atendido = (CAN_DESPACHO / CAN_PEDIDO) * 100
- por_pendiente = (saldo / CAN_PEDIDO) * 100
- cajas = saldo / un_bx
- valor_saldo = (saldo / CAN_PEDIDO) * PRE_ARTICULO

#### Scenario: Fila con pedido completo despachado
- **WHEN** CAN_PEDIDO=540, CAN_DESPACHO=540
- **THEN** saldo=0, por_atendido=100.0, por_pendiente=0.0, cajas=0.0

#### Scenario: Fila con pendiente total
- **WHEN** CAN_PEDIDO=384, CAN_DESPACHO=0
- **THEN** saldo=384, por_atendido=0.0, por_pendiente=100.0, cajas=8.0 (si un_bx=48)

### Requirement: Soporte multi-archivo
El sistema SHALL permitir cargar múltiples archivos XLS/XLSX simultáneamente y consolidarlos en un único DataFrame maestro.

#### Scenario: Dos archivos con mismo cliente
- **WHEN** se cargan fc00845a.xls y fc00845.xls (mismo cliente 10214)
- **THEN** se consolida en un solo DataFrame con todas las filas

#### Scenario: Archivos con diferentes conjuntos de columnas
- **WHEN** un archivo tiene PEDIDO_FECHA y otro no
- **THEN** las columnas ausentes se llenan con null sin error

### Requirement: Asociación SKU-nombre y cliente-id-nombre
El sistema SHALL mantener siempre asociado el SKU con su nombre (del archivo y del catálogo), y el COD_CLIENTE con NOM_CLIENTE, como pares inseparables en todo el pipeline.

#### Scenario: Búsqueda por SKU muestra nombre
- **WHEN** el usuario busca 02187 en la barra de búsqueda
- **THEN** se muestran las filas con SKU 02187 y su descripción FORRO N VINIFORRITO CRISTAL 20-25

#### Scenario: Búsqueda por cliente muestra todos sus SKUs
- **WHEN** el usuario busca Tottus en la barra de búsqueda
- **THEN** se muestran todas las filas del cliente con nombre que contiene Tottus
