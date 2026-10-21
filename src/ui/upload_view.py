"""
Vista de carga de archivos XLS/XLSX de vigencias del ERP.

Permite seleccionar (FilePicker) o arrastrar (drag-drop) multiples reportes,
listarlos y procesarlos en un hilo separado con barra de progreso. Al terminar
emite el callback on_processed con el DataFrame enriquecido.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import flet as ft

from src.core.ingest import Ingester

_log = logging.getLogger("g360.pedido_vigencias")
from src.ui.config import (
    ALLOWED_EXTENSIONS,
    FONT_SIZE_2XL,
    FONT_SIZE_LARGE,
    FONT_SIZE_MEDIUM,
    FONT_SIZE_NORMAL,
    FONT_SIZE_SMALL,
    FONT_SIZE_TITLE,
    FONT_SIZE_XL,
    FONT_SIZE_ICON_XL,
    PADDING_LG,
    PADDING_MD,
    PADDING_SM,
    PADDING_XL,
    PADDING_3XL,
    PADDING_5XL,
    PADDING_6XL,
    RADIUS_SM,
    RADIUS_MD,
    RADIUS_LG,
    RADIUS_XL,
    SELECT_FILES_TITLE,
    SPACING_2XL,
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
    SPACING_XL,
    SPACING_3XL,
)


class UploadView:
    """Vista de carga masiva de archivos de vigencias."""

    def __init__(
        self,
        page: ft.Page,
        colors: dict,
        ingester: Ingester,
        on_processed,
        on_api_state=None,
        on_stock_enriched=None,
    ) -> None:
        self.page = page
        self.c = colors
        self._ingester = ingester
        self._on_processed = on_processed
        self._on_api_state = on_api_state
        self._on_stock_enriched = on_stock_enriched
        self._archivos: list[str] = []
        self._file_picker_ref = ft.Ref[ft.FilePicker]()
        self._running = True
        _log.info("[UploadView] Inicializada")

        self._progress = ft.ProgressBar(
            height=SPACING_SM, color=self.c["accent"], bgcolor=self.c["border"], visible=False
        )
        self._status = ft.Text("", size=FONT_SIZE_MEDIUM, color=self.c["text_muted"])
        self._file_list = ft.Column(spacing=SPACING_MD)
        self._file_list_container = None
        self._btn_procesar = None

        picker = ft.FilePicker(
            ref=self._file_picker_ref,
            on_result=self._on_file_picker_result,
        )
        self.page.overlay.append(picker)
        self.page.update()

    # ---------------------------------------------------------------
    def build(self) -> ft.Container:
        """Construye la vista de carga completa."""
        drop_zone = _DropZone(self.c, on_click=self._pick_files_dialog)
        self._btn_procesar = _ActionBtn(
            icon=ft.Icons.PLAY_ARROW,
            label="PROCESAR ARCHIVOS",
            colors=self.c,
            enabled=len(self._archivos) > 0,
            on_click=self._procesar,
        )
        return ft.Container(
            content=ft.Column(
                [
                    self._build_welcome(),
                    ft.Divider(height=SPACING_2XL, color="transparent"),
                    drop_zone,
                    ft.Divider(height=SPACING_XL, color="transparent"),
                    self._build_file_list_container(),
                    ft.Divider(height=SPACING_XL, color="transparent"),
                    ft.Row(
                        [self._btn_procesar.ctrl, self._progress],
                        spacing=SPACING_3XL,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._status,
                ],
                spacing=0,
                expand=True,
            ),
            padding=PADDING_5XL,
        )

    def _build_welcome(self) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Icon(
                        ft.Icons.RECEIPT_LONG,
                        size=FONT_SIZE_TITLE,
                        color=self.c["accent"],
                        opacity=0.7,
                    ),
                    ft.Text(
                        "Vigencias de Pedidos - CIPSA",
                        size=FONT_SIZE_2XL,
                        weight=ft.FontWeight.W_700,
                        color=self.c["text_primary"],
                    ),
                    ft.Text(
                        "Importa tus reportes ERP (XLS/XLSX) para analizar saldos pendientes, cajas por entregar y alertas de prioridad",
                        size=FONT_SIZE_MEDIUM,
                        color=self.c["text_muted"],
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=SPACING_MD,
            ),
            padding=ft.Padding(0, 0, 0, SPACING_SM),
        )

    def _build_file_list_container(self) -> ft.Container:
        self._file_list_container = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Archivos cargados",
                        size=FONT_SIZE_NORMAL,
                        weight=ft.FontWeight.W_600,
                        color=self.c["text_secondary"],
                    ),
                    ft.Divider(height=1, color=self.c["border"]),
                    self._file_list,
                ],
                spacing=0,
            ),
            bgcolor=self.c["surface"],
            border_radius=RADIUS_LG,
            border=ft.BorderSide(1, self.c["border"]),
            padding=PADDING_LG,
            visible=bool(self._archivos),
        )
        return self._file_list_container

    def update_theme(self, colors: dict) -> ft.Container:
        """Reconstruye la vista de carga con nuevos colores (conserva archivos)."""
        self.c = colors
        self._progress = ft.ProgressBar(
            height=SPACING_SM,
            color=self.c["accent"],
            bgcolor=self.c["border"],
            visible=self._progress.visible if hasattr(self, "_progress") else False,
        )
        self._status = ft.Text(
            self._status.value if hasattr(self, "_status") else "",
            size=FONT_SIZE_MEDIUM,
            color=self.c["text_muted"],
        )
        self._file_list = ft.Column(spacing=SPACING_MD)
        for path in self._archivos:
            self._file_list.controls.append(_FileItem(Path(path).name, self.c))
        return self.build()

    # ---------------------------------------------------------------
    def _on_file_picker_result(self, e) -> None:
        if e.files:
            self._add_files([f.path for f in e.files])

    def _pick_files_dialog(self, e=None) -> None:
        fp = self._file_picker_ref.current
        if fp:
            fp.pick_files(
                dialog_title=SELECT_FILES_TITLE,
                allowed_extensions=ALLOWED_EXTENSIONS,
                allow_multiple=True,
            )

    def _add_files(self, paths: list[str]) -> None:
        for path in paths:
            name = Path(path).name
            if path not in self._archivos:
                self._archivos.append(path)
                self._file_list.controls.append(_FileItem(name, self.c))
        _log.info("[UploadView] Archivos agregados: %s", [Path(p).name for p in paths])
        self._file_list.update()
        self._refresh_file_list_container()
        if self._btn_procesar:
            self._btn_procesar.set_enabled(len(self._archivos) > 0)
        self._status.value = f"{len(self._archivos)} archivo(s) listo(s)"
        self._status.color = self.c["text_secondary"]
        self.page.update()

    def _refresh_file_list_container(self) -> None:
        if self._file_list_container is not None:
            self._file_list_container.visible = bool(self._archivos)
            self._file_list_container.update()

    # ---------------------------------------------------------------
    def _procesar(self) -> None:
        """Procesa los archivos en un hilo separado con ProgressBar."""
        if not self._archivos:
            _log.warning("[UploadView] _procesar llamado sin archivos")
            return
        _log.info("[UploadView] Iniciando procesamiento de %d archivo(s)", len(self._archivos))
        self._btn_procesar.set_enabled(False)
        self._progress.visible = True
        self._status.value = "Procesando y enriqueciendo..."
        self._status.color = self.c["accent"]
        self.page.update()

        def task():
            try:
                if not self._running:
                    _log.info("[UploadView] task cancelado: app cerrada")
                    return
                ing = self._ingester
                _log.info("[UploadView] Cargando archivos...")
                df = ing.load_multiple(self._archivos)
                _log.info(
                    "[UploadView] load_multiple OK: %d filas, fuentes=%s",
                    len(df),
                    sorted(df["_fuente"].unique()) if "_fuente" in df.columns else "n/a",
                )
                df = ing.enrich_with_catalog(df)
                _log.info(
                    "[UploadView] enrich_with_catalog OK: %d filas, categorias=%s",
                    len(df),
                    sorted(df["categoria"].dropna().unique())
                    if "categoria" in df.columns
                    else "n/a",
                )
                df = ing.enrich_with_db_lines(df)
                _log.info(
                    "[UploadView] enrich_with_db_lines (catalogo unico) OK: %d filas, maestro_no_disponible=%s",
                    len(df),
                    ing.db_error_msg or "no",
                )
                # Maestro de productos del ERP: peso, EAN y taxonomia por nombre
                try:
                    from src.core.catalogo_productos import detectar_catalogo_productos
                    from src.core.rutas import escritorio

                    _ruta_cat = detectar_catalogo_productos(escritorio())
                    if _ruta_cat:
                        df = ing.enrich_with_catalogo_productos(df, _ruta_cat)
                        _log.info("[UploadView] catalogo de productos ERP OK: %s", _ruta_cat.name)
                except Exception as exc:  # noqa: BLE001
                    _log.warning("[UploadView] catalogo de productos ERP no aplicado: %s", exc)
                df = ing.compute_derived(df)
                _log.info(
                    "[UploadView] compute_derived OK: %d filas, saldo_total=%s",
                    len(df),
                    df["saldo"].sum() if "saldo" in df.columns else "n/a",
                )
                if not self._running:
                    return
                if self._on_api_state:
                    _log.info("[UploadView] Emitiendo on_api_state(loading)")
                    try:
                        self._on_api_state("loading")
                    except RuntimeError:
                        return
                if self._on_processed:
                    _log.info("[UploadView] Emitiendo on_processed con %d filas", len(df))
                    try:
                        self._on_processed(df)
                    except RuntimeError:
                        return
                enriched = ing.enrich_with_stock_api(df)
                api_state = "offline" if ing.api_unavailable else "online"
                _log.info(
                    "[UploadView] enrich_with_stock_api OK: api_state=%s, api_unavailable=%s",
                    api_state,
                    ing.api_unavailable,
                )
                ing.registrar_importaciones(self._archivos, enriched, api_state=api_state)
                if not self._running:
                    return
                if self._on_stock_enriched:
                    _log.info(
                        "[UploadView] Emitiendo on_stock_enriched con %d filas, api_state=%s",
                        len(enriched),
                        api_state,
                    )
                    try:
                        self._on_stock_enriched(enriched, api_state)
                    except RuntimeError as re:
                        _log.warning(
                            "[UploadView] Event loop cerrado durante on_stock_enriched: %s", re
                        )
                        return
                elif self._on_api_state:
                    _log.info("[UploadView] Emitiendo on_api_state(%s)", api_state)
                    try:
                        self._on_api_state(api_state)
                    except RuntimeError:
                        return
                if not self._running:
                    return
                self._finish_processing(api_state)
            except Exception as ex:
                if "Event loop is closed" in str(ex) or isinstance(ex, RuntimeError):
                    _log.warning("[UploadView] Event loop cerrado durante task: %s", ex)
                    return
                _log.error("[UploadView] Error en task: %s", ex, exc_info=True)
                try:
                    self._ingester.registrar_importaciones(
                        self._archivos,
                        api_state="offline"
                        if getattr(self._ingester, "api_unavailable", True)
                        else "online",
                        resultado="error",
                        mensaje=str(ex)[:500],
                    )
                except Exception:
                    pass
                try:
                    self._processing_error(str(ex))
                except RuntimeError:
                    pass

        run_thread = getattr(self.page, "run_thread", None)
        if run_thread is not None:
            run_thread(task)
        else:
            threading.Thread(target=task, daemon=True).start()

    def _finish_processing(self, api_state: str) -> None:
        _log.info("[UploadView] Procesamiento finalizado: api_state=%s", api_state)
        self._progress.visible = False
        self._btn_procesar.set_enabled(True)
        self._status.value = f"Listo ({api_state})"
        self._status.color = self.c["success"]
        self.page.update()

    def _processing_error(self, message: str) -> None:
        _log.error("[UploadView] Error de procesamiento: %s", message)
        self._status.value = f"Error: {message}"
        self._status.color = self.c["error"]
        self._progress.visible = False
        self._btn_procesar.set_enabled(True)
        self.page.update()


class _DropZone(ft.Container):
    """Zona de carga con drag & drop y boton de explorar."""

    def __init__(self, colors: dict, on_click) -> None:
        self.c = colors
        self._on_click_cb = on_click
        super().__init__(
            content=ft.Column(
                [
                    ft.Icon(
                        ft.Icons.CLOUD_UPLOAD_OUTLINED,
                        size=FONT_SIZE_ICON_XL,
                        color=self.c["accent"],
                        opacity=0.85,
                    ),
                    ft.Text(
                        "Arrastra archivos aqui o haz clic para explorar",
                        size=FONT_SIZE_LARGE,
                        color=self.c["text_secondary"],
                    ),
                    ft.Text(
                        "Formatos soportados: XLSX, XLS",
                        size=FONT_SIZE_NORMAL,
                        color=self.c["text_muted"],
                    ),
                    ft.ElevatedButton(
                        "Explorar archivos",
                        icon=ft.Icons.FOLDER_OPEN,
                        style=ft.ButtonStyle(
                            bgcolor=self.c["surface_variant"],
                            color=self.c["text_primary"],
                            shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
                            padding=PADDING_XL,
                        ),
                        on_click=on_click,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=SPACING_MD,
            ),
            padding=PADDING_6XL,
            bgcolor=self.c["surface"],
            border_radius=RADIUS_XL,
            border=ft.BorderSide(2, self.c["border"]),
            on_hover=self._on_hover,
            on_click=self._on_click,
        )

    def _on_click(self, e) -> None:
        if self._on_click_cb:
            self._on_click_cb(e)

    def _on_hover(self, e) -> None:
        if e.data == "true":
            self.border = ft.BorderSide(2, self.c["accent"])
            self.bgcolor = self.c["surface_variant"]
        else:
            self.border = ft.BorderSide(2, self.c["border"])
            self.bgcolor = self.c["surface"]
        self.update()


class _FileItem(ft.Container):
    """Item de archivo en la lista de cargados."""

    def __init__(self, nombre: str, colors: dict) -> None:
        self.c = colors
        super().__init__(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.DESCRIPTION, size=FONT_SIZE_2XL, color=self.c["accent"]),
                    ft.Text(
                        nombre, size=FONT_SIZE_MEDIUM, color=self.c["text_primary"], expand=True
                    ),
                    ft.Icon(ft.Icons.CHECK_CIRCLE, size=FONT_SIZE_XL, color=self.c["success"]),
                ],
                spacing=SPACING_LG,
            ),
            padding=PADDING_SM,
            border_radius=RADIUS_SM,
            bgcolor=self.c["surface_variant"],
        )

    def shutdown(self) -> None:
        """Marca la vista como cerrada para que el background task no intente
        actualizar controles despues de que la UI se haya destruido."""
        _log.info("[UploadView] shutdown: cancelando task en background")
        self._running = False


class _ActionBtn:
    """Boton de accion principal con estado enabled/disabled."""

    def __init__(self, icon, label, colors: dict, enabled: bool, on_click) -> None:
        self.c = colors
        self._enabled = enabled
        self._on_click = on_click
        self.ctrl = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        icon,
                        size=FONT_SIZE_LARGE,
                        color=ft.Colors.WHITE if enabled else self.c["text_muted"],
                    ),
                    ft.Text(
                        label,
                        size=FONT_SIZE_LARGE,
                        weight=ft.FontWeight.W_600,
                        color=ft.Colors.WHITE if enabled else self.c["text_muted"],
                    ),
                ],
                spacing=SPACING_LG,
            ),
            padding=PADDING_3XL,
            bgcolor=self._accent_bg(enabled),
            border_radius=RADIUS_MD,
            on_click=self._click if enabled else None,
        )

    def _accent_bg(self, enabled: bool) -> str:
        return self.c["accent_dark"] if enabled else self.c["border"]

    def _click(self, _) -> None:
        self._on_click()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.ctrl.bgcolor = self._accent_bg(enabled)
        icon = self.ctrl.content.controls[0]
        label = self.ctrl.content.controls[1]
        icon.color = ft.Colors.WHITE if enabled else self.c["text_muted"]
        label.color = ft.Colors.WHITE if enabled else self.c["text_muted"]
        self.ctrl.on_click = self._click if enabled else None
        # La vista puede haber sido removida tras procesar: solo update si esta adjunta
        if getattr(self.ctrl, "_Control__page", None) is not None:
            self.ctrl.update()
