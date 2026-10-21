"""
Dashboard principal de g360-erp-pedido-vigencias.

Layout: sidebar izquierdo (logo CIPSA, navegacion, filtros, archivos cargados)
+ area principal (header con busqueda y controles, alertas QC, pestañas
segmentadas: General / Por Vendedor / Por Cliente / Por Producto / Stock &
Despacho, y status bar inferior).
"""

from __future__ import annotations

import logging
from datetime import datetime

import flet as ft

from src.config.settings import APP_VERSION
from src.config.theme import get_colors, rgba
from src.core.analytics import PedidosAnalytics

_log = logging.getLogger("g360.pedido_vigencias")
from src.ui.config import (
    ALERT_ITEMS_LIMIT,
    FONT_SIZE_2XL,
    FONT_SIZE_LARGE,
    FONT_SIZE_MEDIUM,
    FONT_SIZE_NORMAL,
    FONT_SIZE_SMALL,
    FONT_SIZE_TINY,
    LOGO_HEIGHT,
    LOGO_PATH,
    LOGO_WIDTH,
    MAX_TABLE_CELL_LENGTH,
    OPACITY_LOW,
    OPACITY_MEDIUM,
    PADDING_2XL,
    PADDING_3XL,
    PADDING_4XL,
    PADDING_LG,
    PADDING_MD,
    PADDING_SM,
    PADDING_XL,
    PADDING_XS,
    RADIUS_LG,
    RADIUS_MD,
    RADIUS_SM,
    SIDEBAR_WIDTH,
    SPACING_2XL,
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
    SPACING_XL,
    SPACING_XS,
)
from src.ui.filters import FiltersPanel
from src.ui.query_bar import QueryBar
from src.ui.tabs_view import TabsView

try:
    from g360_flet.g360_signature import G360Signature
except ImportError:
    G360Signature = None


class Dashboard:
    """Orquesta el layout completo del dashboard."""

    def __init__(
        self,
        page: ft.Page,
        colors: dict,
        theme_mode: str,
        on_refresh_api=None,
        on_toggle_theme=None,
        on_export=None,
        on_nav=None,
        on_open_detail=None,
    ) -> None:
        self.page = page
        self.c = colors
        self._theme_mode = theme_mode
        self._on_refresh_api = on_refresh_api
        self._on_toggle_theme = on_toggle_theme
        self._on_export = on_export
        self._on_nav = on_nav
        self._router = None
        self._nav_items: dict[str, ft.Container] = {}
        self._active_nav: str | None = None

        # Estado de datos
        self._df = None
        self._view_df = None
        self._analytics: PedidosAnalytics | None = None
        self._source_names: list[str] = []
        self._api_state = "offline"
        self._load_ts: str | None = None

        # Estado de tabla
        self._page_idx = 0
        self._sort_col: str | None = None
        self._sort_desc = False
        self._query_explanation = ""
        self._focus_dimension = "cliente"

        # Subcomponentes
        self._query_bar = QueryBar(colors, on_submit=self._on_query)
        self._filters = FiltersPanel(colors, on_view_change=self._on_view_change)
        self._tabs_view = TabsView(page, colors, on_open_detail=on_open_detail)

        self._init_status_controls()

        # Estado de vista (control de bienvenida mostrado)
        self._welcome_control = None

        self._main_col = ft.Column(spacing=SPACING_XL, expand=True)
        self._sidebar_col = ft.Column(spacing=SPACING_XL, width=SIDEBAR_WIDTH, scroll=ft.ScrollMode.AUTO)
        self._root = None

    def _init_status_controls(self) -> None:
        """Crea los controles de estado/KPIs/tabla (recreados al cambiar tema)."""
        self._status_text = ft.Text(
            "Sin datos cargados", size=FONT_SIZE_NORMAL, color=self.c["text_muted"],
            expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
        )
        self._ts_text = ft.Text("", size=FONT_SIZE_NORMAL, color=self.c["text_muted"])
        self._api_badge = ft.Container(
            content=ft.Text("API: offline", size=FONT_SIZE_SMALL, weight=ft.FontWeight.W_600, color=self.c["text_secondary"]),
            bgcolor=self.c["surface_variant"],
            padding=PADDING_SM,
            border_radius=RADIUS_SM,
        )
        self._qc_badge = ft.Container(
            content=ft.Text("0", size=FONT_SIZE_SMALL, weight=ft.FontWeight.W_700, color=ft.Colors.WHITE),
            bgcolor=self.c["error"],
            padding=ft.Padding(7, 3, 7, 3),
            border_radius=RADIUS_LG,
            visible=False,
        )
        # Badge de filtro "Solo con stock" (Mostrando X/Y)
        self._stock_badge = ft.Container(
            content=ft.Text("", size=FONT_SIZE_SMALL, weight=ft.FontWeight.W_600,
                            color=self.c["text_primary"]),
            bgcolor=self.c["accent"],
            padding=ft.Padding(8, 4, 8, 4),
            border_radius=RADIUS_SM,
            visible=False,
        )
        self._alert_container = ft.Column(spacing=SPACING_SM, visible=False)

        # Boton de navegacion hacia atras (router)
        self._back_btn = ft.IconButton(
            icon=ft.Icons.ARROW_BACK,
            tooltip="Volver",
            icon_color=self.c["text_secondary"],
            visible=False,
            on_click=lambda _: self._router.back() if self._router else None,
        )

        # Controles de tabla
        self._table_container = ft.Container()
        self._page_text = ft.Text("", size=11, color=self.c["text_muted"])
        self._query_result_text = ft.Text("", size=11, color=self.c["info"])

    # ---------------------------------------------------------------
    # Build
    # ---------------------------------------------------------------
    def build(self) -> ft.Container:
        """Construye el layout root: sidebar + main."""
        sidebar = self._build_sidebar()
        main = self._build_main()
        self._root = ft.Container(
            content=ft.Row([sidebar, main], spacing=0, expand=True),
            bgcolor=self.c["background"],
            expand=True,
        )
        return self._root

    def _build_sidebar(self) -> ft.Container:
        logo = ft.Container(
            content=ft.Column([
                ft.Image(
                    src=LOGO_PATH,
                    width=LOGO_WIDTH,
                    height=LOGO_HEIGHT,
                    fit=ft.ImageFit.CONTAIN,
                ),
                ft.Text("Vigencias de Pedidos", size=FONT_SIZE_SMALL, color=self.c["text_muted"]),
            ], spacing=SPACING_XS),
            padding=PADDING_2XL,
        )

        self._sidebar_col.controls.extend([
            logo,
            ft.Divider(height=1, color=self.c["border"]),
            self._filters.build(),
            ft.Divider(height=1, color=self.c["border"]),
            self._build_files_section(),
            ft.Container(expand=True),
            self._build_signature(),
        ])
        self._sidebar_col = ft.Container(
            content=self._sidebar_col,
            width=SIDEBAR_WIDTH,
            bgcolor=self.c["sidebar_bg"],
            border=ft.Border(right=ft.BorderSide(1, self.c["border"])),
            padding=ft.Padding(0, 0, 0, 12),
        )
        return self._sidebar_col

    def _build_signature(self) -> ft.Control:
        """Firma G360 (isotipo) al pie del sidebar."""
        if G360Signature is not None:
            return G360Signature(mode="powered", version=APP_VERSION, opacity=OPACITY_MEDIUM)
        return ft.Text(
            "Powered by G360", size=FONT_SIZE_SMALL,
            color=rgba(self.c["accent"], OPACITY_LOW), weight=ft.FontWeight.W_600,
        )

    def _nav_item(self, label: str, icon, nav_id: str) -> ft.Container:
        is_active = self._active_nav == nav_id
        _log.info("[Dashboard] _nav_item: label=%s nav_id=%s active=%s", label, nav_id, is_active)
        ctrl = ft.Container(
            content=ft.Row([
                ft.Icon(icon, size=FONT_SIZE_LARGE, color=self.c["accent"] if is_active else self.c["text_muted"]),
                ft.Text(label, size=FONT_SIZE_NORMAL, color=self.c["text_primary"] if is_active else self.c["text_muted"]),
            ], spacing=SPACING_MD),
            padding=PADDING_LG,
            bgcolor=self.c["accent"] if is_active else self.c["surface_variant"],
            border_radius=RADIUS_SM,
            on_click=lambda _, n=nav_id: self._on_nav(n),
        )
        self._nav_items[nav_id] = ctrl
        return ctrl

    def set_router(self, router) -> None:
        """Registra el router de vistas y marca la ruta inicial como activa."""
        self._router = router
        if router is not None and router.current:
            self._set_active_nav(router.current)

    def _set_active_nav(self, nav_id: str | None) -> None:
        """Resalta el item de navegacion activo en el sidebar."""
        _log.info("[Dashboard] _set_active_nav: %s", nav_id)
        for nid, ctrl in self._nav_items.items():
            active = nid == nav_id
            ctrl.bgcolor = self.c["surface_variant"] if active else None
            ctrl.content.controls[1].weight = ft.FontWeight.W_700 if active else ft.FontWeight.W_500
            ctrl.content.controls[1].color = self.c["text_primary"] if active else self.c["text_secondary"]
            if getattr(ctrl, "page", None) is not None:
                ctrl.update()

    def _nav_hover(self, e, nav_id: str) -> None:
        if e.data == "true":
            e.control.bgcolor = self.c["surface_variant"]
        else:
            e.control.bgcolor = None
        e.control.update()

    def _nav_click(self, nav_id: str) -> None:
        if self._router is not None:
            self._router.go(nav_id)
        elif self._on_nav:
            self._on_nav(nav_id)

    def _build_files_section(self) -> ft.Container:
        self._files_list = ft.Column(spacing=SPACING_SM)
        return ft.Container(
            content=ft.Column([
                ft.Text("Archivos cargados", size=FONT_SIZE_NORMAL, weight=ft.FontWeight.W_600, color=self.c["text_secondary"]),
                self._files_list,
            ], spacing=SPACING_MD),
            padding=PADDING_MD,
        )

    def _build_main(self) -> ft.Container:
        header = self._build_header()
        alerts = self._build_alerts()
        tabs = self._tabs_view.build()
        status = self._build_status_bar()

        self._analytics_controls = [
            header,
            alerts,
            self._query_result_text,
            tabs,
            status,
        ]
        self._main_col.controls.extend(self._analytics_controls)
        return ft.Container(
            content=self._main_col,
            padding=PADDING_4XL,
            expand=True,
        )

    def show_welcome(self, control: ft.Control) -> None:
        """Muestra el control de bienvenida/carga en el area principal."""
        _log.info("[Dashboard] show_welcome")
        self._welcome_control = control
        self._main_col.controls = [control]
        self._sync_back_btn()
        self._safe_root_update()

    def show_home(self) -> None:
        """Vuelve a la pantalla de inicio (carga de archivos)."""
        _log.info("[Dashboard] show_home")
        if self._welcome_control is not None:
            self.show_welcome(self._welcome_control)

    def show_detail(self, control: ft.Control) -> None:
        """Muestra una pagina de detalle (con boton de volver)."""
        _log.info("[Dashboard] show_detail")
        self._main_col.controls = [control]
        self._sync_back_btn()
        self._safe_root_update()

    def show_monitor(self, control: ft.Control) -> None:
        """Muestra una vista del monitor operativo (con boton de volver)."""
        _log.info("[Dashboard] show_monitor")
        self._main_col.controls = [control]
        self._sync_back_btn()
        self._safe_root_update()

    def _sync_back_btn(self) -> None:
        """Sincroniza la visibilidad del boton volver con el historial."""
        if self._back_btn is not None:
            visible = bool(self._router is not None and self._router.can_back)
            if self._back_btn.visible != visible:
                self._back_btn.visible = visible

    def show_analytics(self) -> None:
        """Restaura el contenido de analisis (KPIs, alertas, tabla, status)."""
        _log.info("[Dashboard] show_analytics: main_col controls=%d", len(self._analytics_controls))
        self._main_col.controls = self._analytics_controls
        self._sync_back_btn()
        self._safe_root_update()
        try:
            self.page.update()
            _log.info("[Dashboard] page.update() OK en show_analytics")
        except Exception as ex:
            _log.error("[Dashboard] page.update() fallo en show_analytics: %s", ex)

    def _safe_root_update(self) -> None:
        """Actualiza la vista solo si el root esta montado en la pagina."""
        if self._root is not None and getattr(self._root, "page", None) is not None:
            self._root.update()

    def _build_header(self) -> ft.Container:
        refresh_btn = ft.IconButton(
            icon=ft.Icons.REFRESH,
            tooltip="Actualizar stock API",
            icon_color=self.c["text_secondary"],
            on_click=lambda _: self._on_refresh_api() if self._on_refresh_api else None,
        )
        theme_btn = ft.IconButton(
            icon=ft.Icons.LIGHT_MODE if self._theme_mode == "dark" else ft.Icons.DARK_MODE,
            tooltip="Cambiar tema",
            icon_color=self.c["text_secondary"],
            on_click=lambda _: self._on_toggle_theme() if self._on_toggle_theme else None,
        )
        export_btn = ft.ElevatedButton(
            "Exportar XLSX",
            icon=ft.Icons.DOWNLOAD,
            style=ft.ButtonStyle(
                bgcolor=self.c["accent_dark"],
                color=ft.Colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
                padding=PADDING_XL,
            ),
            on_click=lambda _: self._on_export() if self._on_export else None,
        )
        return ft.Container(
            content=ft.Row([
                self._back_btn,
                self._query_bar.build(),
                refresh_btn,
                theme_btn,
                export_btn,
            ], spacing=SPACING_LG),
        )

    def _build_alerts(self) -> ft.Container:
        header = ft.Row([
            ft.Icon(ft.Icons.WARNING_AMBER, size=FONT_SIZE_2XL, color=self.c["warning"]),
            ft.Text("Alertas QC (saldo > 5000 en VES)", size=FONT_SIZE_MEDIUM, weight=ft.FontWeight.W_700, color=self.c["text_secondary"]),
            self._qc_badge,
        ], spacing=SPACING_LG)
        container = ft.Container(
            content=ft.Column([
                ft.Container(content=header, on_click=self._toggle_alerts),
                self._alert_container,
            ], spacing=SPACING_MD),
            padding=PADDING_LG,
            bgcolor=self.c["surface"],
            border_radius=RADIUS_LG,
            border=ft.BorderSide(1, self.c["border"]),
            visible=False,
        )
        self._alerts_parent = container
        return container

    def _toggle_alerts(self, _) -> None:
        _log.info("[Dashboard] _toggle_alerts: visible=%s", self._alert_container.visible)
        self._alert_container.visible = not self._alert_container.visible
        self._alert_container.update()

    def _build_status_bar(self) -> ft.Container:
        return ft.Container(
                        content=ft.Row([
                self._status_text,
                self._stock_badge,
                self._ts_text,
                self._api_badge,
            ], spacing=SPACING_XL),
            padding=ft.Padding(2, 6, 2, 6),
            border=ft.Border(top=ft.BorderSide(1, self.c["border"])),
        )

    # ---------------------------------------------------------------
    # Data updates
    # ---------------------------------------------------------------
    def update_data(self, df, source_names=None, api_state="offline", ts=None) -> None:
        """Recibe el DataFrame enriquecido y reconstruye la vista."""
        _log.info("[Dashboard] update_data recibido: %d filas, api_state=%s, source_names=%s", len(df) if df is not None else 0, api_state, source_names)
        self._df = df
        self._source_names = source_names or []
        self._api_state = api_state
        self._load_ts = ts or datetime.now().strftime("%H:%M:%S")
        self._analytics = PedidosAnalytics(df)
        self._page_idx = 0
        self._query_explanation = ""
        self._query_bar.clear()

        self._apply_filters()
        _log.info("[Dashboard] _apply_filters OK: view_df=%d filas", len(self._view_df) if self._view_df is not None else 0)
        # Si el filtro activo dejo la vista vacia, degradar a universo completo
        # para que el dashboard no quede en blanco.
        if self._view_df is not None and self._view_df.empty and self._df is not None and not self._df.empty:
            _log.warning("[Dashboard] view_df vacio tras filtros, fallback a universo completo")
            self._view_df = self._df.reset_index(drop=True)
            self._analytics = PedidosAnalytics(self._view_df)
        self._tabs_view.update_data(self._view_df, api_state)
        _log.info("[Dashboard] tabs_view.update_data OK")
        self._rebuild_all()
        _log.info("[Dashboard] _rebuild_all OK")

    def _populate_filter_options(self, df=None) -> None:
        """No-op de compatibilidad: ya no hay dropdowns de filtro."""
        pass

    # ---------------------------------------------------------------
    # Filtros y busqueda
    # ---------------------------------------------------------------
    def _on_view_change(self, nav_id: str) -> None:
        """Callback del sidebar: cambia el tipo de vista (dimension/filtro).

        Delega al router para que la ruta maneje el cambio de dimension
        y el rebuild de la tabla. Esto evita doble-rebuild.
        """
        _log.info("[Dashboard] _on_view_change: %s", nav_id)
        self._page_idx = 0
        if self._router is not None:
            self._router.go(nav_id)
        else:
            self._apply_filters()
            self._rebuild_all()
        self.page.update()

    def _on_query(self, text: str) -> None:
        if not self._analytics:
            return
        filtered, explanation = self._analytics.query_natural(text)
        self._view_df = filtered
        self._query_explanation = explanation
        self._page_idx = 0
        if filtered.empty:
            self._query_result_text.value = explanation
            self._query_result_text.color = self.c["warning"]
        else:
            self._query_result_text.value = f"Query aplicada: {explanation}"
            self._query_result_text.color = self.c["info"]
        self._rebuild_all()

    def _apply_filters(self) -> None:
        """Aplica el filtro principal (solo filas con stock relevante)."""
        if self._df is None:
            self._view_df = None
            return
        df = self._df
        if "es_relevante" in df.columns:
            df = df[df["es_relevante"]]
        self._view_df = df.reset_index(drop=True)

    # ---------------------------------------------------------------
    # Rebuild
    # ---------------------------------------------------------------
    def _rebuild_all(self) -> None:
        _log.info("[Dashboard] _rebuild_all: view_df=%d filas", len(self._view_df) if self._view_df is not None else 0)
        self._update_alerts()
        self._update_status()
        self._tabs_view.update_data(self._view_df, self._api_state)
        self._sync_back_btn()
        self.page.update()
        _log.info("[Dashboard] _rebuild_all: page.update() OK")

    def _update_alerts(self) -> None:
        if not self._analytics:
            _log.info("[Dashboard] _update_alerts: sin analytics")
            return
        alerts = self._analytics.get_qc_alerts()
        container_parent = self._find_alerts_parent()
        if alerts.empty:
            self._qc_badge.visible = False
            if container_parent is not None:
                container_parent.visible = False
            _log.info("[Dashboard] _update_alerts: sin alertas QC")
            return
        self._qc_badge.value = str(len(alerts))
        self._qc_badge.visible = True
        self._alert_container.controls.clear()
        for _, row in alerts.head(ALERT_ITEMS_LIMIT).iterrows():
            self._alert_container.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Text(str(row.get("SKU", "")), size=FONT_SIZE_NORMAL, weight=ft.FontWeight.W_600, color=self.c["text_primary"], width=60),
                        ft.Text(str(row.get("NOM_ARTICULO", ""))[:MAX_TABLE_CELL_LENGTH], size=FONT_SIZE_NORMAL, color=self.c["text_secondary"], expand=True),
                        ft.Text(f"{row.get('saldo', 0):,.0f}", size=FONT_SIZE_NORMAL, color=self.c["error"]),
                        ft.Text(f"{row.get('cajas', 0):,.0f} cj", size=FONT_SIZE_NORMAL, color=self.c["text_muted"]),
                    ], spacing=SPACING_MD),
                    padding=PADDING_SM,
                    bgcolor=self.c["surface_sunken"],
                    border_radius=RADIUS_SM,
                )
            )
        if container_parent is not None:
            container_parent.visible = True
        _log.info("[Dashboard] _update_alerts: %d alertas QC mostradas", len(alerts))

    def _find_alerts_parent(self):
        return getattr(self, "_alerts_parent", None)

    def _update_status(self) -> None:
        if self._view_df is None or self._df is None:
            self._status_text.value = "Sin datos cargados"
            self._ts_text.value = ""
            self._stock_badge.visible = False
            _log.info("[Dashboard] _update_status: sin datos")
        else:
            n_files = len(self._source_names)
            shown = len(self._view_df)
            total = len(self._df)
            self._status_text.value = f"{shown:,} registros · {n_files} archivo(s)"
            self._ts_text.value = f"Ultima carga: {self._load_ts}"
            # Badge: visible solo cuando el filtro es_relevante redujo filas
            filtrado = "es_relevante" in self._df.columns and shown < total
            if filtrado:
                self._stock_badge.value = f"Mostrando {shown:,}/{total:,}"
                self._stock_badge.tooltip = "Filtrando solo productos con stock (es_relevante)"
                self._stock_badge.visible = True
            else:
                self._stock_badge.visible = False
            _log.info("[Dashboard] _update_status: %d/%d registros, %d archivos", shown, total, n_files)
        if self._api_state == "online":
            api_label, api_color = "API: online", self.c["success"]
        elif self._api_state == "loading":
            api_label, api_color = "API: actualizando stock...", self.c["info"]
        else:
            api_label, api_color = "API: offline (datos locales)", self.c["warning"]
        self._api_badge.content.value = api_label
        self._api_badge.content.color = api_color

    # ---------------------------------------------------------------
    # Vistas personalizadas (navegacion sidebar)
    # ---------------------------------------------------------------
    def register_overlay(self) -> None:
        """No-op: los overlays (FilePickers) los registra UploadView."""

    def set_custom_view(self, df, label: str) -> None:
        """Reemplaza la vista actual por un DataFrame pre-filtrado."""
        if df is None or df.empty:
            self._view_df = df
            self._query_explanation = label
        else:
            self._view_df = df.reset_index(drop=True)
            self._query_explanation = label
        self._page_idx = 0
        self._query_result_text.value = label
        self._query_result_text.color = self.c["info"]
        self._rebuild_all()

    def clear_custom_view(self) -> None:
        """Restaura la vista filtrada por el panel de filtros."""
        self._query_explanation = ""
        self._query_result_text.value = ""
        self._page_idx = 0
        self._apply_filters()
        self._rebuild_all()

    # ---------------------------------------------------------------
    # Theme
    # ---------------------------------------------------------------
    def update_theme(self, mode: str, welcome_control=None) -> None:
        """Reconstruye colores y layout completo al cambiar de tema."""
        self._theme_mode = mode
        self.c = get_colors(mode)
        self._tabs_view.update_theme(self.c)
        if self._root is None:
            return
        self._init_status_controls()
        # Rebuild sidebar + main con los nuevos colores
        self._sidebar_col = ft.Column(spacing=SPACING_XL, width=SIDEBAR_WIDTH, scroll=ft.ScrollMode.AUTO)
        self._main_col.controls = []
        sidebar = self._build_sidebar()
        main = self._build_main()
        self._root.content = ft.Row([sidebar, main], spacing=0, expand=True)
        self._root.bgcolor = self.c["background"]
        if self._df is not None:
            self._main_col.controls = self._analytics_controls
            self._rebuild_all()
        else:
            if welcome_control is not None:
                self._welcome_control = welcome_control
            if self._welcome_control is not None:
                self._main_col.controls = [self._welcome_control]
            else:
                self._main_col.controls = self._analytics_controls
        self._root.update()
