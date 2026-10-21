# g360-erp-pedido-vigencias

Dashboard Flet desktop para el analisis de **vigencias de pedidos CIPSA**.
Consolida reportes XLS/XLSX del ERP, los enriquece con el catalogo maestro y el
stock en tiempo real del API G360, y presenta saldos pendientes, cajas por
entregar y alertas de prioridad (incluyendo QC / almacen 121) de forma
interactiva y exportable a XLSX con hojas estructuradas.

## Requisitos

- Python 3.10+
- npm no requerido (app desktop local)

## Instalacion

```bash
# 1. Crear entorno virtual (recomendado)
python -m venv .venv
.venv\Scripts\activate

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Ejecutar la aplicacion
python main.py
```

## Uso

### Reporte de acciones desde consola (sin UI)

```bash
# Genera el reporte en el escritorio (auto-detecta el .xls/.xlsx del ERP)
python reporte.py

# Doble click: generar_reporte.bat / generar_reporte.vbs
```

Parametros utiles:

| Flag | Que hace |
|---|---|
| `--fuente` | Ruta del `.xls/.xlsx` del ERP (por defecto: el mas reciente del escritorio) |
| `--salida` | Ruta del `.xlsx` (por defecto: escritorio) |
| `--familia` | `ANTICIPO` (default), `CONTADO`, `CANJE`, `LETRA`, `FACTURA` |
| `--dias` | Recorte por antiguedad del pedido (default 30, `0` = todo) |
| `--linea` / `--categoria` / `--estado` | Segmentacion (repetible) |
| `--allowlist` | Allowlist de lineas (archivo `.json` o `01,02,MA`) |
| `--sin-allowlist` | Desactiva el filtro estricto de lineas |
| `--incluir-detalle` | Agrega la hoja DETALLE con formulas vivas |

### Catalogo unico (maestro de la DB de ventas)

El pipeline usa **Render** como verdad de stock/catalogo del dia. La DB de
ventas entra como **maestro de referencia estatico** (foto), importado desde
el *cartucho* que exporta `g360-erp-nc-sustentor`:

```bash
# UNA sola vez por cartucho: extrae historial.db (3.8 GB) a temp,
# lee las dimensiones y escribe .cache/catalogo_unico.json (~4 MB)
python cartucho_import.py

# otras opciones
python cartucho_import.py --zip "C:\\...\\cartucho-20261012-172938.zip"
python cartucho_import.py --anios 10 --force
```

- Es idempotente: si el `sha256` del cartucho no cambio, no re-importa.
- El temp se purga al terminar; el catalogo queda como archivo liviano.
- `historial.db` (3.8 GB) **no** se lee en las corridas diarias.
- Aporta: lineas (53) resueltas por nombre o codigo, alias por nombre,
  articulos, vendedores y clientes (ultimos 5 anos) y la **allowlist**.

### Maestro de productos del ERP (PRODUCTOS.xls)

El ERP exporta periodicamente el maestro de productos (`codigos productos.xls`
/ `PRODUCTOS.xls`, 12k SKUs). Es la misma fuente que usa `g360-master-data`
para generar `catalogo_productos.json`, pero este trae el maestro **completo**
(no solo los ~2.5k de la guia `SKU_BX`).

```bash
# El reporte lo lee solo si lo encuentra en el escritorio
python reporte.py --catalogo-productos "C:\\...\\codigos productos.xls"

# Fusionarlo al catalogo unico (deja el maestro autocontenido)
python catalogo_import.py
```

Aporta lo que Render no trae:

| Dato | Origen | Impacto |
|---|---|---|
| `peso_kg` | `CAN_KG_UM` | 3.449 SKUs (Render: 1.171) -> la lista del camion va con peso real |
| `ean13` / `ean14` | `COD_EAN` / `COD_EAN_14` | picking completo |
| taxonomia | `LINEA` / `GRUPO` / `TIPO` / `FAMILIA` | resuelve lineas que Render no trae |
| ciclo de vida | `FLG_DESCONTINUADO` | pedidos con producto descontinuado -> renegocio |

Prioridad: **Render** (verdad del dia) > **maestro ERP** > **catalogo unico** >
catalogo local > ERP. El peso final es la union de Render y el maestro ERP.

### Filtro estricto de lineas (allowlist)

Solo pasa al embudo lo que pertenece a una linea autorizada (24 lineas core).

> **SKUs Crayola (prefijo C):** el catalogo unico (cartucho) tiene lineas
> propias para cada sub-marca Crayola: CA (PINTURA), CB (ESCRITURA),
> CC (PEGAMENTOS), CD (ACCESORIOS), CE (MANUALIDADES), CF (SET).
> Un SKU como `CA087` resuelve a linea **CA**, no a 77 (PINTURA).
> La resolucion usa el **prefijo** de 2 chars (primeros caracteres) cuando
> el valor tiene 3+ chars y el resolver por codigo no da un resultado
> valido en el maestro. Esto evita que `CA087` caiga en 01 (PELOTAS)
> por el sufijo "87".
>
> **SKUs numericos:** `78698` -> linea **78** (ARCHIVO), `011019` -> linea
> **01** (PELOTAS). El prefijo se prioriza sobre el sufijo cuando ambos
> existen en el maestro.
La linea manda: si resuelve a un codigo no autorizado se descarta, y una linea
vacia tambien (el grupo no rescata). Lo descartado queda en `SANEAMIENTO`
(`tipo=FUERA_DE_ALLOWLIST`) con unidades y valor: nada se pierde en silencio.

### App desktop (Flet)

1. **Cargar archivos**: arrastra uno o mas reportes XLS/XLSX de vigencias
   (ej: `vig hoy.xls`, `fc00845a.xls`) o usa el boton *Explorar archivos*.
2. **Procesar**: la app consolida las filas, preservando los SKUs como texto
   (ceros a la izquierda intactos) y enriquece con el catalogo maestro
   (`g360-master-data/output/catalogo_productos.json`) y el stock del API G360.
3. **Analizar**: usa la barra de busqueda multi-campo (OC, cliente, SKU,
   producto, condicion de pago) y los filtros laterales (categoria, estado de
   linea, almacen, condicion, vendedor). Los KPIs se actualizan en tiempo real.
4. **Exportar**: genera `pedidos_vigencias_YYYYMMDD_HHMMSS.xlsx` con 5 hojas
   (RESUMEN, POR_CLIENTE, POR_VENDEDOR, DETALLE con formulas, ALERTAS_QC).

## Convenciones clave

- **SKU como texto**: `pd.read_excel(..., dtype=str)` sin padding ni
  transformacion. `01240` no se confunde con `001240` ni `1240`.
- **Saldos**: `saldo = CAN_PEDIDO - CAN_DESPACHO`; `cajas = saldo / un_bx`.
- **Precios (definitivos)**: salen del **reporte de vigencias**, nunca del
  catalogo. El ERP cumple `PEDIDO_IMPORTE_ARITCULO = (PRE_ARTICULO / VIGENCIA) * CAN_PEDIDO`,
  y el **precio unitario** es `PRE_ARTICULO / VIGENCIA` (identico a
  `PEDIDO_IMPORTE_ARITCULO / CAN_PEDIDO`). El `precio` del catalogo (API /
  master-data) es **referencial** (precio de lista) y NO se cruza con el
  historico del cartucho. El PANEL reporta la **coherencia de precios**
  (lineas que cumplen la formula, con tolerancia relativa).
- **Alerta QC**: SKUs con saldo > 5000 units en VES son candidatos a liberacion
  desde el almacen 121 (solo alerta, no ejecuta traslados).
- **Prioridad de fuentes**: Render (dia) > catalogo unico (maestro) >
  catalogo local > ERP.

## Estructura

```
g360-erp-pedido-vigencias/
+-- main.py                # Entry point (ft.app FLET_APP)
+-- reporte.py             # CLI del reporte de acciones (sin UI)
+-- cartucho_import.py     # Bootstrap del catalogo unico desde el cartucho
+-- catalogo_import.py     # Fusiona el maestro de productos del ERP al catalogo
+-- generar_reporte.bat    # Lanzador por doble click (consola)
+-- generar_reporte.vbs    # Lanzador por doble click (sin consola)
+-- pyproject.toml
+-- requirements.txt
+-- src/
|   +-- app.py             # Orquestacion: UploadView -> Ingester -> Analytics -> Exporters
|   +-- config/            # settings.py (API, cache, umbrales) y theme.py (paleta CIPSA)
|   +-- core/              # ingest.py, analytics.py, exporters.py
|   |   +-- cartucho.py        # Importador del cartucho (zip -> dimensiones)
|   |   +-- catalogo_unico.py  # Lector del catalogo unico + lookups
|   |   +-- catalogo_productos.py  # Maestro de productos del ERP (PRODUCTOS.xls)
|   |   +-- allowlist.py       # Filtro estricto de lineas
|   |   +-- lineas.py          # Reglas de linea y normalizacion de nombres
|   |   +-- rutas.py           # Rutas del sistema (escritorio)
|   +-- ui/                # dashboard.py, upload_view.py, filters.py, query_bar.py
+-- tests/                 # test_ingest.py, test_analytics.py, test_exporters.py,
|                          # test_sku_match.py, test_catalogo_unico.py
+-- assets/                # marca CIPSA (logo, icono)
+-- .cache/                # cache local (ignorado): catalogo_unico.json, stock, snapshots
```

## Tests

```bash
pytest
```

## Proyecto local

Este es un proyecto local del ecosistema G360 (no repo GitHub separado).
