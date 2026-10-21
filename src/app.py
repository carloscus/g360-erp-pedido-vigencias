"""
Orquestador de g360-erp-pedido-vigencias.

Carga la configuracion, inicializa el Dashboard, conecta el flujo
UploadView -> Ingester -> Analytics -> Exporters, maneja errores del API de
stock, mantiene un cache local (TTL 15 min) y registra logs rotativos.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime

import flet as ft

from src.config.settings import (
    CACHE_TTL,
    CATALOGO_RUTA,
    DATA_DIR,
    S1_API_KEY,
    S1_API_URL,
    WINDOW_HEIGHT,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
    WINDOW_WIDTH,
    UserConfig,
)
from src.config.theme import get_colors, load_theme_preference, save_theme_preference
from src.core.exporters import export_to_xlsx
from src.core.ingest import Ingester
from src.core.snapshot import SnapshotManager
from src.ui.client_detail import ClientDetailView
from src.ui.config import FONT_SIZE_XL, SPACING_LG
from src.ui.dashboard import Dashboard
from src.ui.monitor_extra import AlertsView, ConfigView, ResumenView
from src.ui.prioridades_view import PrioridadesView
from src.ui.monitor_views import ColaView, GroupsView, HistoryView, SearchView, StatsView
from src.ui.router import Router
from src.ui.upload_view import UploadView

# Logger compartido (configurado en main.py)
_log = logging.getLogger("g360.pedido_vigencias")

_CACHE_FILE = DATA_DIR / "stock_cache.json"


def _log_msg(msg: str) -> None:
    _log.info(msg)


class PedidoVigenciasApp:
    """Aplicacion Flet principal."""

    def __init__(self, page: ft.Page) -> None:
        try:
            self.page = page
            self._theme_mode = load_theme_preference()
            self._setup_page()

            # Estado de datos
            self._df = None
            self._source_names: list[str] = []
            self._api_state = "offline"
            self._last_api_error = ""

            # Componentes de negocio
            self.ingester = Ingester()

            # Configuracion del usuario persistente (.cache/config.json)
            self._user_config = UserConfig()
            self._user_config.load()
            # Sincroniza credenciales del API si el usuario las cambio
            cfg_url = str(self._user_config.get("api_url", "") or "")
            cfg_key = str(self._user_config.get("api_key", "") or "")
            if cfg_url:
                self.ingester.api_url = cfg_url
            if cfg_key:
                self.ingester.api_key = cfg_key
            # Lineas validas configuradas por el usuario (hoja config / defaults)
            cfg_lineas = self._user_config.get("lineas_validas", None)
            if cfg_lineas:
                self.ingester._lineas_validas = [str(v).strip().upper() for v in cfg_lineas if str(v).strip()]

            # Dashboard (shell persistente)
            self.dashboard = Dashboard(
                page,
                get_colors(self._theme_mode),
                self._theme_mode,
                on_refresh_api=self._on_refresh_api,
                on_toggle_theme=self._toggle_theme,
                on_export=self._on_export,
                on_nav=self._on_nav,
                on_open_detail=self.open_cliente_detail,
            )

            # Router de vistas (home -> dashboard -> detalle)
            self._router = Router()
            self._register_routes()
            self.dashboard.set_router(self._router)

            # Vistas del monitor operativo (Resumen/Alertas/Estadisticas/Historico/Buscar/Grupos/Cola/Config)
            colors = get_colors(self._theme_mode)
            self._snap_mgr = SnapshotManager(DATA_DIR)
            self._monitor_views = {
                "resumen": ResumenView(colors),
                "alertas": AlertsView(colors, config=self._user_config),
                "estadisticas": StatsView(colors),
                "historico": HistoryView(colors, snapshot=self._snap_mgr, on_snack=self._snack),
                "buscar": SearchView(colors),
                "grupos": GroupsView(colors, on_snack=self._snack),
                "cola": ColaView(colors, on_snack=self._snack),
                "config": ConfigView(colors, config=self._user_config, on_saved=self._on_config_saved),
                "prioridades": PrioridadesView(colors, on_snack=self._snack),
            }

            # Vista de carga inicial
            self.upload_view = UploadView(
                page,
                get_colors(self._theme_mode),
                self.ingester,
                on_processed=self._on_processed,
                on_api_state=self._on_api_state,
                on_stock_enriched=self._on_stock_enriched,
            )

            self._build()
            # Registrar hook de cierre para persistir cache
            page.on_close = lambda e: self.shutdown()
        except Exception as ex:
            import traceback
            _log.error("[FATAL] PedidoVigenciasApp.__init__: %s\n%s", ex, traceback.format_exc())
            raise

    # ---------------------------------------------------------------
    def _setup_page(self) -> None:
        self.page.title = "Vigencias de Pedidos - CIPSA"
        self.page.theme_mode = ft.ThemeMode.DARK if self._theme_mode == "dark" else ft.ThemeMode.LIGHT
        self.page.bgcolor = get_colors(self._theme_mode)["background"]
        self.page.padding = 0
        self.page.window_width = WINDOW_WIDTH
        self.page.window_height = WINDOW_HEIGHT
        self.page.window_min_width = WINDOW_MIN_WIDTH
        self.page.window_min_height = WINDOW_MIN_HEIGHT
        self.page.window_resizable = True
        try:
            self.page.window_center()
        except AttributeError:
            pass

        # Splash de carga inicial: feedback visual mientras se construye el Dashboard
        colors = get_colors(self._theme_mode)
        self._splash = ft.Container(
            content=ft.Column(
                [
                    ft.ProgressRing(color=colors["accent"]),
                    ft.Text(
                        "Cargando Vigencias de Pedidos...",
                        size=FONT_SIZE_XL,
                        color=colors["text_primary"],
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=SPACING_LG,
            ),
            alignment=ft.alignment.center,
            expand=True,
            bgcolor=colors["background"],
        )
        try:
            self.page.add(self._splash)
            self.page.update()
        except Exception as ex:
            _log_msg(f"Splash no mostrado: {ex}")

    def _build(self) -> None:
        """Programa la construccion real tras renderizar el splash."""
        try:
            self.page.run_task(self._deferred_build)
        except Exception as ex:
            _log_msg(f"run_task no disponible ({ex}); build sincrono")
            self._build_now()

    async def _deferred_build(self) -> None:
        """Espera breve para que el splash se renderice antes del build pesado."""
        await asyncio.sleep(0.15)
        self._build_now()

    def _build_now(self) -> None:
        root = self.dashboard.build()
        # Retirar el splash antes de montar el dashboard
        try:
            self.page.controls.remove(self._splash)
        except Exception:
            pass
        self.page.add(root)
        self.page.update()
        self.dashboard.register_overlay()
        # Estado inicial: bienvenida + zona de carga
        self.dashboard.show_welcome(self.upload_view.build())
        self.page.update()
        self._check_catalogo()
        _log_msg("Aplicacion lista, esperando archivos")

    def _check_catalogo(self) -> None:
        """Avisa (log + SnackBar) si el catalogo de productos no esta disponible."""
        if not CATALOGO_RUTA.exists():
            msg = f"Catalogo de productos no encontrado en {CATALOGO_RUTA}"
            _log_msg(f"AVISO: {msg}. Las lineas quedaran sin categoria.")
            self._snack(f"AVISO: {msg}", "#F59E0B")

    # ---------------------------------------------------------------
    # Flujo de procesamiento
    # ---------------------------------------------------------------
    def _snack(self, text: str, color: str = "#10B981") -> None:
        """Muestra un SnackBar con page.open (API flet 0.28)."""
        try:
            self.page.open(ft.SnackBar(ft.Text(text), bgcolor=color))
        except Exception as ex:
            _log_msg(f"SnackBar no mostrado: {ex}")

    def _on_processed(self, df) -> None:
        """Recibe el DataFrame enriquecido y lo muestra en el dashboard."""
        _log.info("[App] _on_processed recibido: %d filas, columnas=%s", len(df), list(df.columns))
        self._df = df
        self._source_names = sorted(set(df["_fuente"].astype(str).unique())) if "_fuente" in df else []
        _log.info("[App] Mostrando analytics...")
        self.dashboard.show_analytics()
        _log.info("[App] Llamando dashboard.update_data...")
        self.dashboard.update_data(
            df,
            source_names=self._source_names,
            api_state=self._api_state,
            ts=datetime.now().strftime("%H:%M:%S"),
        )
        _log.info("[App] update_data completado")
        # Snapshot automatico de pendientes (seguimiento de atencion)
        self._save_auto_snapshot(df)
        # Nueva carga de datos: el historial de navegacion parte del dashboard
        self._router.reset("dashboard")
        self.dashboard._set_active_nav("dashboard")
        if self._api_state == "offline" and self._last_api_error:
            self._snack(f"API de stock offline: {self._last_api_error}", "#EF4444")
        _log.info("[App] Datos cargados OK: %d filas, fuentes=%s", len(df), self._source_names)

    def _save_auto_snapshot(self, df) -> None:
        """Guarda un snapshot automatico de pendientes y poda el historial."""
        try:
            if not bool(self._user_config.get("snapshot_auto", True)):
                _log.info("[App] Snapshot automatico desactivado (config)")
                return
            label = f"auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            keep = int(self._user_config.get("snapshot_keep", 30))
            self._snap_mgr.save_snapshot(df, label=label)
            self._snap_mgr.prune(keep=max(1, keep))
            _log.info("[App] Snapshot automatico guardado: %s (keep=%d)", label, keep)
        except Exception as ex:
            _log.warning("[App] Error guardando snapshot automatico: %s", ex)

    def _sync_monitor_views(self) -> None:
        """Refresca las vistas del monitor con los datos/colores actuales."""
        try:
            colors = get_colors(self._theme_mode)
            for view in self._monitor_views.values():
                view.set_colors(colors)
                view.set_data(self._df, self._api_state)
        except Exception as ex:
            _log.warning("[App] _sync_monitor_views fallo: %s", ex)

    def _on_api_state(self, state: str) -> None:
        self._api_state = state
        self._last_api_error = self.ingester.api_error_msg

    def _on_config_saved(self) -> None:
        """Configuracion guardada: aplica credenciales del API y refresca vistas."""
        try:
            url = str(self._user_config.get("api_url", "") or "")
            key = str(self._user_config.get("api_key", "") or "")
            if url:
                self.ingester.api_url = url
            if key:
                self.ingester.api_key = key
            cfg_lineas = self._user_config.get("lineas_validas", None)
            if cfg_lineas:
                self.ingester._lineas_validas = [str(v).strip().upper() for v in cfg_lineas if str(v).strip()]
            # Invalida el cache de stock en memoria: el proximo refresh usa el nuevo endpoint
            self.ingester._stock_cache = None
            self._sync_monitor_views()
            self._snack("Configuracion guardada. Refresca el stock si cambiaste el API.")
            _log.info("[App] _on_config_saved: api_url=%s", self.ingester.api_url)
        except Exception as ex:
            _log.warning("[App] _on_config_saved fallo: %s", ex)

    def _on_stock_enriched(self, df, api_state: str) -> None:
        """Actualiza stock sin bloquear la primera vista de saldo pendiente."""
        _log.info("[App] _on_stock_enriched recibido: %d filas, api_state=%s", len(df), api_state)
        self._df = df
        self._on_api_state(api_state)
        self.dashboard.update_data(
            df,
            source_names=self._source_names,
            api_state=self._api_state,
            ts=datetime.now().strftime("%H:%M:%S"),
        )
        _log.info("[App] update_data post-stock-enriched completado")
        self._sync_monitor_views()
        if self._api_state == "offline" and self._last_api_error:
            self._snack(f"Stock local: {self._last_api_error}", "#F59E0B")


    # ---------------------------------------------------------------
    # Acciones del header
    # ---------------------------------------------------------------
    def _on_refresh_api(self) -> None:
        """Actualiza el stock desde el API (con cache TTL)."""
        _log.info("[App] Refresh API solicitado")
        if self._df is None:
            _log.warning("[App] Refresh API cancelado: no hay datos")
            return
        try:
            _log.info("[App] Ejecutando enrich_with_stock_api...")
            self._df = self.ingester.enrich_with_stock_api(self._df)
            self._save_cache()
            self._on_api_state("offline" if self.ingester.api_unavailable else "online")
            _log.info("[App] API state: %s, unavailable=%s", self._api_state, self.ingester.api_unavailable)
            self.dashboard.update_data(
                self._df,
                source_names=self._source_names,
                api_state=self._api_state,
                ts=datetime.now().strftime("%H:%M:%S"),
            )
            _log.info("[App] Dashboard actualizado post-refresh")
            self._sync_monitor_views()
            if self.ingester.api_unavailable:
                self._snack(f"API offline: {self.ingester.api_error_msg}", "#EF4444")
            else:
                self._snack("Stock actualizado correctamente")
        except Exception as ex:
            _log.error("[App] Error refrescando stock: %s", ex, exc_info=True)
            self._snack(f"Error: {ex}", "#EF4444")

    def _on_export(self) -> None:
        """Exporta el DataFrame a XLSX (5 hojas)."""
        _log.info("[App] Export solicitado")
        if self._df is None:
            self._snack("No hay datos para exportar", "#F59E0B")
            return
        try:
            out = export_to_xlsx(self._df)
            self._snack(f"Exportado: {out.name}")
            _log.info("[App] Export XLSX generado: %s", out)
        except Exception as ex:
            _log.error("[App] Error exportando: %s", ex, exc_info=True)
            self._snack(f"Error: {ex}", "#EF4444")

    # ---------------------------------------------------------------
    # Router de vistas
    # ---------------------------------------------------------------
    def _register_routes(self) -> None:
        """Registra las rutas del router: home, dashboard, alertas,
        sin catalogo y detalle de cliente."""
        self._router.register("home", lambda: self._route_home())
        self._router.register("dashboard", lambda: self._route_dashboard())
        self._router.register("alerts", lambda: self._route_alerts())
        self._router.register("categoria", lambda: self._route_grupo("Por Categoria", nav_id="categoria"))
        self._router.register("estado_linea", lambda: self._route_grupo("Por Estado de Linea", nav_id="estado_linea"))
        self._router.register("pedido", lambda: self._route_grupo("Por Pedido", nav_id="pedido"))
        self._router.register("pedido_sku", lambda: self._route_grupo("Estado por Pedido", nav_id="pedido_sku"))
        self._router.register("detalle", lambda: self._route_grupo("Por Linea", nav_id="detalle"))
        self._router.register("vendedor", lambda: self._route_grupo("Por Vendedor", nav_id="vendedor"))
        self._router.register("cliente", lambda: self._route_grupo("Por Cliente", nav_id="cliente"))
        self._router.register("producto", lambda: self._route_grupo("Por Producto", nav_id="producto"))
        self._router.register("almacen", lambda: self._route_grupo("Por Almacen", nav_id="almacen"))
        self._router.register(
            "detalle_cliente",
            lambda cliente="", nombre="": self._route_detalle_cliente(cliente, nombre),
        )
        # Vistas del monitor operativo
        self._router.register("resumen", lambda: self._route_monitor("resumen"))
        self._router.register("alertas", lambda: self._route_monitor("alertas"))
        self._router.register("estadisticas", lambda: self._route_monitor("estadisticas"))
        self._router.register("historico", lambda: self._route_monitor("historico"))
        self._router.register("buscar", lambda: self._route_monitor("buscar"))
        self._router.register("grupos", lambda: self._route_monitor("grupos"))
        self._router.register("cola", lambda: self._route_monitor("cola"))
        self._router.register("config", lambda: self._route_monitor("config"))
        self._router.register("prioridades", lambda: self._route_monitor("prioridades"))

    def _route_home(self) -> None:
        self.dashboard.show_home()
        self.dashboard._set_active_nav(None)
        self.page.update()

    def _route_dashboard(self) -> None:
        self.dashboard.show_analytics()
        self.dashboard.clear_custom_view()
        self.dashboard._tabs_view.update_view("dashboard")
        self.dashboard._set_active_nav("dashboard")
        self.dashboard._filters.set_active("dashboard")
        self.page.update()

    def _route_alerts(self) -> None:
        _log.info("[App] _route_alerts")
        if self._df is None:
            self._route_home()
            return
        self.dashboard.show_analytics()
        self.dashboard._tabs_view.update_view("alerts")
        self.dashboard._set_active_nav("alerts")
        self.dashboard._filters.set_active("alerts")
        self.page.update()

    def _route_grupo(self, titulo: str, nav_id: str = "") -> None:
        """Cambia la dimension de la tabla maestra."""
        _log.info("[App] _route_grupo: titulo=%s nav_id=%s", titulo, nav_id)
        if self._df is None:
            self._route_home()
            return
        self.dashboard.show_analytics()
        self.dashboard._tabs_view.update_view(nav_id or "dashboard")
        self.dashboard._set_active_nav(nav_id or None)
        self.dashboard._filters.set_active(nav_id or None)
        self.page.update()

    def _route_monitor(self, view_id: str) -> None:
        """Muestra una vista del monitor operativo (resumen/alertas/estadisticas/historico/buscar/grupos/cola/config)."""
        _log.info("[App] _route_monitor: view_id=%s", view_id)
        if self._df is None:
            self._route_home()
            return
        view = self._monitor_views.get(view_id)
        if view is None:
            self._route_dashboard()
            return
        view.set_colors(get_colors(self._theme_mode))
        view.set_data(self._df, self._api_state)
        mounted = view._host is not None and getattr(view._host, "page", None) is not None
        ctrl = view._host if mounted else view.build()
        self.dashboard.show_monitor(ctrl)
        self.dashboard._set_active_nav(view_id)
        self.dashboard._filters.set_active(view_id)
        self.page.update()

    def _route_detalle_cliente(self, cliente: str = "", nombre: str = "") -> None:
        _log.info("[App] _route_detalle_cliente: cliente=%s nombre=%s", cliente, nombre)
        if self._df is None or not cliente:
            self._route_home()
            return
        df = self._df
        analytics = self.dashboard._analytics
        cli_col = analytics._cliente_col() if analytics else "COD_CLIENTE"
        if cli_col not in df.columns:
            self._route_dashboard()
            return
        sub = df[df[cli_col].astype(str).str.strip() == str(cliente).strip()]
        detail = ClientDetailView(sub, self.dashboard.c, nombre=nombre)
        self.dashboard.show_detail(detail.build())
        self.dashboard._set_active_nav(None)
        self.page.update()

    def _on_nav(self, nav_id: str) -> None:
        """Callback de navegacion del sidebar (delegado al router)."""
        if self._df is None:
            # Sin datos: cualquier navegacion vuelve a la pantalla de inicio
            self._router.reset("home")
            self._route_home()
            return
        self._router.go(nav_id)
        self.dashboard._set_active_nav(self._router.current)
        self.page.update()

    def open_cliente_detail(self, cliente: str, nombre: str = "") -> None:
        """Abre la pagina de detalle de un cliente via router."""
        _log.info("[App] open_cliente_detail: cliente=%s nombre=%s", cliente, nombre)
        if self._df is None or not cliente:
            _log.warning("[App] open_cliente_detail cancelado: df=None o cliente vacio")
            return
        self._router.go("detalle_cliente", cliente=cliente, nombre=nombre)
        self.page.update()

    # ---------------------------------------------------------------
    # Tema
    # ---------------------------------------------------------------
    def _toggle_theme(self) -> None:
        self._theme_mode = "light" if self._theme_mode == "dark" else "dark"
        save_theme_preference(self._theme_mode)
        self.page.theme_mode = ft.ThemeMode.DARK if self._theme_mode == "dark" else ft.ThemeMode.LIGHT
        self.page.bgcolor = get_colors(self._theme_mode)["background"]
        colors = get_colors(self._theme_mode)
        welcome = self.upload_view.update_theme(colors)
        self.dashboard.update_theme(self._theme_mode, welcome_control=welcome)
        self._sync_monitor_views()
        self.page.update()
        _log_msg(f"Tema cambiado a {self._theme_mode}")

    # ---------------------------------------------------------------
    # Cache local del API (TTL 15 min)
    # ---------------------------------------------------------------
    def _load_cache(self) -> dict | None:
        """Carga el cache de stock si es vigente (dentro del TTL)."""
        if not _CACHE_FILE.exists():
            return None
        try:
            with open(_CACHE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            ts = float(data.get("ts", 0))
            if time.time() - ts <= CACHE_TTL:
                return data
        except Exception:
            pass
        return None

    def _save_cache(self) -> None:
        """Persiste el stock por SKU en .cache/stock_cache.json."""
        try:
            if self._df is None or "stock_api_disponible" not in self._df:
                return
            stock = {}
            for sku, group in self._df.groupby("SKU"):
                stock[str(sku)] = group["stock_api_disponible"].iloc[0]
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            # Preservar catalogo Render ya cacheado (no borrar verdad catalogo)
            catalog = {}
            alias = {}
            try:
                if _CACHE_FILE.exists():
                    with open(_CACHE_FILE, encoding="utf-8") as f:
                        payload = json.load(f)
                        catalog = payload.get("catalog", {}) or {}
                        alias = payload.get("alias", {}) or {}
            except (OSError, ValueError):
                catalog = {}
                alias = {}
            payload = {"ts": time.time(), "stock": stock, "catalog": catalog, "alias": alias}
            with open(_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            _log_msg("Cache de stock guardado")
        except Exception as ex:
            _log_msg(f"Error guardando cache: {ex}")

    # ---------------------------------------------------------------
    # Cierre
    # ---------------------------------------------------------------
    def shutdown(self) -> None:
        """On close: cancela tareas, guarda cache y registra el cierre."""
        _log.info("[App] shutdown: cancelando tareas en background")
        try:
            if self.upload_view is not None and hasattr(self.upload_view, "shutdown"):
                self.upload_view.shutdown()
        except Exception as ex:
            _log.warning("[App] Error cancelando upload_view: %s", ex)
        try:
            self._save_cache()
            _log.info("Aplicacion cerrada correctamente")
        except Exception as ex:
            _log.warning("Error en shutdown: %s", ex)
