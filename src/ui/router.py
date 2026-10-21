"""
Router de vistas tipo paginas para g360-erp-pedido-vigencias.

Mantiene un stack de historial: las rutas registradas son handlers
(funciones que mutan la vista principal). `go()` apila y ejecuta,
`back()` desapila y re-ejecuta la ruta previa con sus mismos parametros.
"""

from __future__ import annotations

import logging

_log = logging.getLogger("g360.pedido_vigencias")


class Router:
    """Router minimo con historial para navegacion entre vistas."""

    def __init__(self, on_change=None) -> None:
        self._routes: dict[str, callable] = {}
        self._history: list[tuple[str, dict]] = []
        self._on_change = on_change

    def register(self, name: str, handler) -> None:
        """Registra un handler: handler(**params) muta la vista."""
        self._routes[name] = handler

    def go(self, name: str, **params) -> None:
        """Navega a una ruta apilandola en el historial."""
        _log.info("[Router] go: name=%s params=%s", name, params)
        handler = self._routes.get(name)
        if handler is None:
            _log.warning("[Router] go: ruta '%s' no registrada", name)
            return
        self._history.append((name, params))
        handler(**params)
        self._notify()

    def back(self) -> None:
        """Retrocede a la ruta anterior del historial."""
        _log.info("[Router] back: can_back=%s history=%d", self.can_back, len(self._history))
        if not self.can_back:
            return
        self._history.pop()
        name, params = self._history[-1]
        self._routes[name](**params)
        self._notify()

    def reset(self, name: str, **params) -> None:
        """Reinicia el historial empezando en la ruta dada (sin ejecutar)."""
        _log.info("[Router] reset: name=%s params=%s", name, params)
        self._history = [(name, params)] if name in self._routes else []
        self._notify()

    @property
    def current(self) -> str | None:
        return self._history[-1][0] if self._history else None

    @property
    def can_back(self) -> bool:
        return len(self._history) > 1

    def _notify(self) -> None:
        if self._on_change:
            self._on_change(self)