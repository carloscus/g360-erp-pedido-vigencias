"""Centralized UI constants and styling configuration."""

import flet as ft

# =============================================================================
# Layout Dimensions
# =============================================================================
SIDEBAR_WIDTH = 250
TABS_HEIGHT = 600
PROGRESS_BAR_WIDTH = 300
PROGRESS_BAR_HEIGHT = 16
DROPDOWN_WIDTH = 300
DROPDOWN_WIDTH_NARROW = 280

# =============================================================================
# Page Sizes
# =============================================================================
TABLE_PAGE_SIZE = 50

# =============================================================================
# Font Sizes — interfaz limpia, jerarquia legible (vendedor→cliente tree)
# =============================================================================
FONT_SIZE_TINY = 11
FONT_SIZE_SMALL = 12
FONT_SIZE_NORMAL = 13
FONT_SIZE_MEDIUM = 14
FONT_SIZE_LARGE = 15
FONT_SIZE_XL = 16
FONT_SIZE_2XL = 18
FONT_SIZE_3XL = 20
FONT_SIZE_TITLE = 34
FONT_SIZE_ICON_LARGE = 36
FONT_SIZE_ICON_XL = 48

# =============================================================================
# Spacing
# =============================================================================
SPACING_XS = 2
SPACING_SM = 4
SPACING_MD = 6
SPACING_LG = 8
SPACING_XL = 10
SPACING_2XL = 12
SPACING_3XL = 16

# =============================================================================
# Padding
# =============================================================================
PADDING_XS = ft.Padding(4, 2, 4, 2)
PADDING_SM = ft.Padding(8, 4, 8, 4)
PADDING_MD = ft.Padding(12, 8, 12, 8)
PADDING_LG = ft.Padding(12, 10, 12, 10)
PADDING_XL = ft.Padding(14, 10, 14, 10)
PADDING_2XL = ft.Padding(16, 12, 16, 12)
PADDING_3XL = ft.Padding(20, 12, 20, 12)
PADDING_4XL = ft.Padding(20, 14, 20, 10)
PADDING_5XL = ft.Padding(28, 20, 28, 20)
PADDING_6XL = ft.Padding(40, 32, 40, 32)

# =============================================================================
# Border Radius
# =============================================================================
RADIUS_SM = 6
RADIUS_MD = 8
RADIUS_LG = 10
RADIUS_XL = 12

# =============================================================================
# Animation
# =============================================================================
TAB_ANIMATION_DURATION = 150

# =============================================================================
# Limits
# =============================================================================
TOP_SKUS_LIMIT = 20
TOP_PAYMENT_CONDITIONS = 8
ALERT_ITEMS_LIMIT = 5
MAX_TABLE_CELL_LENGTH = 40
MAX_VENDOR_NAME_LENGTH = 25
MAX_ARTICLE_NAME_LENGTH = 30
MAX_SHORT_NAME_LENGTH = 20
SIMPLE_TABLE_ROW_LIMIT = 50

# =============================================================================
# Coverage Statuses
# =============================================================================
COVERAGE_COBERTO = "Cubierto"
COVERAGE_PARCIAL = "Parcial"
COVERAGE_SIN_STOCK = "Sin Stock"

# =============================================================================
# File Extensions
# =============================================================================
ALLOWED_EXTENSIONS = ["xlsx", "xls"]

# =============================================================================
# Opacity
# =============================================================================
OPACITY_LOW = 0.45
OPACITY_MEDIUM = 0.7

# =============================================================================
# Dialog Dimensions
# =============================================================================
DIALOG_WIDTH = 300
DIALOG_HEIGHT = 200

# =============================================================================
# Logo
# =============================================================================
LOGO_PATH = "assets/images/Logo_cipsa_solid.png"
LOGO_WIDTH = 112
LOGO_HEIGHT = 48

# =============================================================================
# Common UI Strings
# =============================================================================
SEARCH_HINT = "Buscar: OC, cliente, SKU, producto, condicion de pago..."
SELECT_FILES_TITLE = "Seleccionar archivos de vigencias"
FILTER_TODAS = "Todas"
FILTER_SIN_ESTADO = "(sin estado)"


def kpi_card_style():
    """Returns a dict with KPI card styling properties."""
    return {
        "spacing": SPACING_XS,
        "padding": PADDING_XL,
        "border_radius": RADIUS_LG,
    }


def table_style():
    """Returns a dict with common table styling properties."""
    return {
        "border_radius": RADIUS_MD,
        "column_spacing": SPACING_3XL,
    }


def progress_bar_style():
    """Returns a dict with progress bar styling properties."""
    return {
        "spacing": SPACING_SM,
        "padding": PADDING_XL,
        "border_radius": RADIUS_LG,
        "width": PROGRESS_BAR_WIDTH,
        "height": PROGRESS_BAR_HEIGHT,
    }
