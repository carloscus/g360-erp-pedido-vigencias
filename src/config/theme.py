"""
Paleta de colores CIPSA para g360-erp-pedido-vigencias (skill G360 "cipsa").

Modo oscuro (default): fondo #0D1117, superficie #161B22, accent #008F5D.
Modo claro: fondo #F3F5F9, superficie #FFFFFF, accent #008F5D.

Tokens segun skill.json de la skill "cipsa": accent #008F5D,
accentStrong #0B6B47, accentBright #34D399, info #0369A1.
"""

from __future__ import annotations

import json
from pathlib import Path

# Color accent principal CIPSA (skill "cipsa")
ACCENT = "#008F5D"
ACCENT_DARK = "#0B6B47"

# Colores del modo oscuro (default)
DARK_COLORS: dict = {
    "accent": "#008F5D",
    "accent_dark": "#0B6B47",
    "success": "#34D399",
    "warning": "#F59E0B",
    "error": "#EF4444",
    "info": "#3B82F6",
    "violet": "#8B5CF6",
    "pink": "#EC4899",
    "cyan": "#06B6D4",
    "orange": "#F97316",
    "kpis": {
        "items": "#06B6D4",      # cian
        "saldo": "#8B5CF6",      # violeta
        "valor": "#34D399",      # verde brand bright
        "cajas": "#F59E0B",      # ambar
        "porcentaje": "#0EA5E9", # azul cielo
    },
    "surface": "#161B22",
    "surface_variant": "#1E242C",
    "surface_sunken": "#090E14",
    "background": "#0D1117",
    "sidebar_bg": "#0E1319",
    "border": "#FFFFFF1A",
    "border_soft": "#21262D",
    "text_muted": "#8B949E",
    "text_primary": "#F0F6FC",
    "text_secondary": "#C4CDD8",
    "glass_bg": "rgba(22, 27, 34, 0.85)",
    "glass_border": "#FFFFFF1A",
}

# Colores del modo claro
LIGHT_COLORS: dict = {
    "accent": "#008F5D",
    "accent_dark": "#0B6B47",
    "success": "#0E9F6E",
    "warning": "#B45309",
    "error": "#DC2626",
    "info": "#0369A1",
    "violet": "#7C3AED",
    "pink": "#DB2777",
    "cyan": "#0891B2",
    "orange": "#EA580C",
    "kpis": {
        "items": "#0891B2",
        "saldo": "#7C3AED",
        "valor": "#0E9F6E",
        "cajas": "#B45309",
        "porcentaje": "#0284C7",
    },
    "surface": "#FFFFFF",
    "surface_variant": "#F1F6F3",
    "surface_sunken": "#EAEFEB",
    "background": "#F3F5F9",
    "sidebar_bg": "#ffffff",
    "border": "#E3E8F0",
    "border_soft": "#f1f5f9",
    "text_muted": "#64748B",
    "text_primary": "#0F172A",
    "text_secondary": "#334155",
    "glass_bg": "rgba(255, 255, 255, 0.90)",
    "glass_border": "#e2e8f0",
}


def get_colors(mode: str) -> dict:
    """Retorna el diccionario de colores segun el modo (dark/light)."""
    return dict(DARK_COLORS if mode == "dark" else LIGHT_COLORS)


def rgba(color: str, opacity: float) -> str:
    """Convierte un color hex (#RRGGBB) a formato con canal alpha (#AARRGGBB)."""
    if color.startswith("#") and len(color) == 9:
        return color  # ya trae alpha
    if color.startswith("#") and len(color) == 7:
        hex_color = color[1:]
        alpha = int(max(0.0, min(1.0, opacity)) * 255)
        return f"#{alpha:02x}{hex_color}"
    # colores con nombre o malformados: se devuelven tal cual
    return color


def get_theme_file() -> Path:
    """Ruta del archivo de preferencia de tema del usuario."""
    return Path.home() / ".g360" / "pedido_vigencias_config.json"


def load_theme_preference() -> str:
    """Carga la preferencia de tema guardada (dark/light). Default: dark."""
    try:
        config_file = get_theme_file()
        if config_file.exists():
            with open(config_file, encoding="utf-8") as f:
                config = json.load(f)
                return config.get("theme_mode", "dark")
    except Exception:
        pass
    return "dark"


def save_theme_preference(mode: str) -> None:
    """Guarda la preferencia de tema del usuario."""
    try:
        config_file = get_theme_file()
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config = {"theme_mode": mode}
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f)
    except Exception:
        pass
