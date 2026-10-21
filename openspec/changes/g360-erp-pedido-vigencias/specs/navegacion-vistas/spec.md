## Purpose

Definir el **mapa funcional de pantallas** de la aplicación organizado por **tipo de vista** (y no por página suelta), y cerrar la **regla de negocio de Estado de Línea** antes de implementar el motor de cálculo y el rediseño de navegación. Este spec es la base de la Fase de análisis (Fase 0) y del modelo de negocio (Fase 1) del plan del proyecto.

## Context

Hoy la navegación es una lista plana de `nav_id` en el sidebar (dashboard, alerts, sin_catalogo, categoria, estado_linea) más productos internos por tabs. El plan del proyecto establece que las vistas "dejan de ser módulos aislados" y pasan a ser **diferentes ventanas sobre el mismo problema**: DATA → PEDIDO → SALDO → STOCK → DESPACHABLE → PRIORIDAD → PLAN → CARGA → SNAPSHOT → COMPARACIÓN. Este spec traduce ese circuito a una taxonomía de tipos de vista y a un orden de menú derivado.

Fuente de verdad del Estado de Línea: la lista provista por el negocio de códigos a considerar, documentada en la sección correspondiente.

## ADDED Requirements

### Requirement: Taxonomía de familias de vistas
El sistema SHALL clasificar todas las pantallas en **cuatro familias de tipo de vista**, cada una respondiendo a una pregunta de negocio distinta:

| Familia | Pregunta que responde | Vistas |
|---|---|---|
| **F01 Resumen** | ¿Cuánto debemos enviar y cuál es el estado global? | Dashboard / Inicio con KPIs globales |
| **F02 Jerárquicas de negocio** | ¿A quién / qué producto / con qué concentración de saldo? | Vendedor → Cliente → Pedido; Producto → SKU; Categoría; Estado de Línea |
| **F03 Operativas / Prioridad** | ¿Qué se puede enviar hoy, qué está bloqueado y en qué orden? | Despachable hoy, Bloqueados, Prioridades, Plan de Despacho, Pedidos |
| **F04 Seguimiento** | ¿Qué avanzó o retrocedió desde la última carga? | Snapshots, Comparación, Bitácora |

#### Scenario: Toda pantalla pertenece a una familia
- **WHEN** se cataloga cualquier vista de la aplicación
- **THEN** pertenece exactamente a una de las familias F01–F04, y su lugar en el menú deriva de esa familia

### Requirement: Mapa de pantallas por familia
El sistema SHALL exponer, por cada familia, el mapa jerárquico navegable. Este mapa es la especificación funcional de qué pantallas existen y cómo se desciende entre ellas.

**F01 Resumen**
- Dashboard: KPIs (pedidos, valor total, valor atendido, saldo, unidades pendientes, despachable hoy, bloqueado por stock, anticipos, pedidos aprobados).

**F02 Jerárquicas de negocio** — orden de navegación descendente:
- Vendedores → Clientes → Pedidos → Líneas (KPIs: venta/pedido, atendido, saldo, unidades, despachable, bloqueado; ordenable por **Saldo ↓**).
- Clientes → Pedidos → Productos (métricas: valor total, atendido, saldo, unidades, nº de pedidos, pedidos prioritarios, pedidos bloqueados).
- Pedidos (tabla central con check de prioridad).
- Productos / SKU → líneas.
- Categorías.
- Estado de Línea.

**F03 Operativas / Prioridad**
- Despachable Hoy: `pendiente vs stock disponible` → DESPACHABLE / BLOQUEADO.
- Bloqueados: pendiente sin stock.
- Prioridades: automática (puntuada) + manual (posición asignada por el usuario, sin modificar el pedido original).
- Plan de Despacho: orden operativo resultante.

**F04 Seguimiento**
- Snapshots de carga.
- Comparación entre cargas (avance, retroceso, sin cambio).
- Bitácora de prioridades manuales y motivo.

#### Scenario: Navegación descendente en F02
- **WHEN** el usuario selecciona un vendedor
- **THEN** puede bajar a sus clientes, luego a sus pedidos y luego a sus líneas, conservando el contexto del vendedor

### Requirement: Regla de negocio — Estado de Línea vigente
El sistema SHALL considerar como **línea vigente** (cuenta para saldo, despachable y prioridad) únicamente los pedidos cuyo `ESTADO_LINEA` (aliases: `estado_linea`, `ESTADO_LINEA`) esté dentro del conjunto de códigos vigentes definido por el negocio. Todo código fuera de ese conjunto SHALL excluirse del saldo operativo (puede mostrarse en una vista de "excluidos" para auditoría).

Conjunto de códigos provisto por el negocio (a considerar como vigentes):

```
01, 02, 09, 11, 14, 72, 73, 75, 76, 77, 78, 79, 85,
MA, CA, AD, CB, CC, CD, CE, CF, CG
```

#### Scenario: Filtrar por estado vigente
- **WHEN** se procesa una carga que contiene líneas con `ESTADO_LINEA` en `{01, 02, 09, 11, 14, 72, 73, 75, 76, 77, 78, 79, 85, MA, CA, AD, CB, CC, CD, CE, CF, CG}`
- **THEN** esas líneas se incluyen en el saldo y en el despachable
- **AND** las líneas con cualquier otro `ESTADO_LINEA` se excluyen del saldo operativo

### Requirement: Separación de saldos
El sistema SHALL calcular por separado y mostrar explícitamente:
1. **Saldo comercial** = valor del pedido/compromiso original − valor atendido.
2. **Saldo físico (unidades pendientes)** = `CAN_PEDIDO − CAN_DESPACHO`.
3. **Saldo despachable por stock** = `MIN(unidades pendientes, stock disponible)`.

Resultado operativo por línea: **DESPACHABLE** vs **BLOQUEADO** por stock.

#### Scenario: Cálculo de despachable y bloqueado
- **WHEN** una línea tiene 1,000 pendientes y stock disponible 600
- **THEN** despachable = 600 y bloqueado = 400
- **AND** económicamente se muestran despachable hoy (S/ 12,000) y bloqueado (S/ 8,000) si el saldo pendiente es S/ 20,000

### Requirement: Navegación por tipo (sidebar agrupado)
El sistema SHALL renderizar el menú lateral agrupado por las familias de tipo de vista (F01–F04), con encabezado por grupo, y el orden interno siguiendo el circuito de priorización. La navegación NO SHALL ser una lista plana.

```
── RESUMEN ────────────
   Dashboard
── NEGOCIO ────────────
   Vendedores | Clientes | Pedidos | Productos | Categorias | Estado de Linea
── OPERATIVO ──────────
   Despachable Hoy | Bloqueados | Prioridades | Plan de Despacho
── SEGUIMIENTO ────────
   Snapshots | Comparacion | Bitacora
```

#### Scenario: Sidebar agrupado por tipo
- **WHEN** el usuario abre el menú lateral
- **THEN** los ítems están agrupados bajo encabezados por familia (Resumen, Negocio, Operativo, Seguimiento)
- **AND** la familia activa determina en qué grupo se resalta el ítem actual

### Requirement: Ordenamiento por saldo como criterio por defecto
El sistema SHALL ordenar por defecto las vistas jerárquicas y los pedidos por **Saldo descendente** de modo que el mayor pendiente aparezca primero, respondiendo "¿qué vendedor/cliente tiene más saldo vigente?".

#### Scenario: Orden por defecto de un vendedor
- **WHEN** el usuario abre la vista de vendedores
- **THEN** se muestran ordenados por saldo de mayor a menor

### Requirement: Prioridad no modifica el pedido
El sistema SHALL representar la prioridad (automática o manual) como una **selección operativa separada** del pedido original, con `priority_id`, `pedido_id`, `fecha`, `posición`, `usuario`, `prioridad_manual`, `observación`, `estado`. Marcar un pedido como prioritario SHALL NOT modificar los datos del pedido.

#### Scenario: Prioridad manual sobre pedido
- **WHEN** el usuario marca PED-021 como prioridad 1
- **THEN** se crea un registro de prioridad manual (posición 1, usuario actual, motivo)
- **AND** el pedido original PED-021 no se modifica
- **AND** se conserva la prioridad automática sugerida (p. ej. 8) para comparación

## OUT OF SCOPE (no se implementa en esta spec)

- No se construyen aún las pantallas: este spec define el **mapa** y las **reglas**, no su implementación.
- No se definen aquí los algoritmos de puntuación de prioridad automática (requiere reglas de negocio separadas de Fase 1).
- No se resuelve aquí el modelo de Compromiso / Anticipo / Sustitución (spec de modelo de datos aparte).
- La semántica individual de cada código de Estado de Línea (p. ej. qué significa `AD`, `CB`, `MA`, `CA`) requiere validación con el negocio; este spec fija el **conjunto vigente** pero deja cada significado como pendiente de confirmación.

## Open Questions (a confirmar con negocio)

- ¿Cuál es el significado exacto de cada código: `01, 02, 09, 11, 14, 72, 73, 75, 76, 77, 78, 79, 85, MA, CA, AD, CB, CC, CD, CE, CF, CG`? (Desde la lista se infiere la familia `CB/CC/CD/CE/CF/CG`; falta confirmar si son estados válidos de saldo o de control.)
- ¿El valor pendiente es `cantidad pendiente × precio unitario` o hay consideraciones por descuentos / NC / cambios?
- ¿El stock puede comprometerse entre varios pedidos a la vez?
- ¿La fuente oficial de stock es el API G360 Stock en Render?
- ¿Quiénes pueden modificar la prioridad manual?

## Validation Plan

1. Validar la lista de Estados de Línea contra datos reales: contar el % de líneas que caen fuera del conjunto vigente y revisar si corresponde incluirlas o corregir el conjunto.
2. Confirmar con negocio la semántica de al menos los códigos ambiguos (`AD`, `CA`, `MA`, `CB`–`CG`).
3. Confirmar la definición de valor pendiente (punto anterior) antes de codificar el motor.
4. Aprobar el mapa de familias (F01–F04) y el sidebar agrupado antes de rediseñar la navegación.