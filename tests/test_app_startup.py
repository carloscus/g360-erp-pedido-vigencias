"""Tests de arranque: splash inicial, build diferido y hook de cierre."""

import asyncio
from types import SimpleNamespace

import flet as ft

from src.app import PedidoVigenciasApp
from src.config.theme import get_colors


class _FakePage:
    """Pagina Flet minima para instanciar la app sin servidor."""

    def __init__(self):
        self.overlay = []
        self.controls = []
        self.window = SimpleNamespace(window_center=lambda: None)
        self.on_close = None
        self.pending = None

    def update(self, *args):
        pass

    def add(self, *controls):
        for c in controls:
            self.controls.append(c)
            self._attach(c)

    def run_task(self, coro, *args):
        """Guarda la coroutine pendiente sin crearla (evita never-awaited)."""
        self.pending = (coro, args)
        return None

    def _attach(self, control):
        object.__setattr__(control, "_Control__page", self)
        children = []
        content = getattr(control, "content", None)
        if content is not None:
            children.append(content)
        controls = getattr(control, "controls", None) or []
        if isinstance(controls, (list, tuple)):
            children.extend(controls)
        else:
            children.append(controls)
        for ch in children:
            if isinstance(ch, ft.Control):
                self._attach(ch)


def _make_app():
    page = _FakePage()
    app = PedidoVigenciasApp(page)
    return app, page


def test_startup_registers_on_close_hook():
    app, page = _make_app()
    assert callable(app.shutdown)
    # El hook de cierre debe estar registrado tras __init__
    assert page.on_close is not None


def test_startup_shows_splash():
    app, page = _make_app()
    # El splash debe estar entre los controles de la pagina
    assert app._splash in page.controls


def test_build_now_replaces_splash_with_dashboard():
    app, page = _make_app()
    app._build_now()
    # El splash fue retirado
    assert app._splash not in page.controls
    # El dashboard quedo montado
    assert any(c is not app._splash for c in page.controls)
    assert app.dashboard._root is not None


def test_build_defers_via_run_task():
    app, page = _make_app()
    app._build()
    # El build diferido fue registrado
    assert page.pending is not None
    coro_fn, args = page.pending
    # Y al ejecutarlo monta el dashboard
    asyncio.run(coro_fn(*args))
    assert app._splash not in page.controls
    assert app.dashboard._root is not None