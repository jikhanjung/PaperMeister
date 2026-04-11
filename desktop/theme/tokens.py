"""Design tokens.

Defined per devlog/20260411_P09_New_Desktop_UI_Design.md.
Dark theme first. Light theme is a token swap target for later.
"""

COLORS_DARK = {
    # Surfaces
    'bg.app':        '#0F1115',
    'bg.panel':      '#151820',
    'bg.elevated':   '#1B1F2A',
    'bg.hover':      '#222634',
    'bg.selected':   '#2A3044',

    # Borders
    'border.subtle': '#1F2230',
    'border.default':'#2B2F3D',
    'border.strong': '#3A3F52',

    # Text
    'text.primary':  '#E6E8EF',
    'text.secondary':'#A0A5B4',
    'text.muted':    '#6B7080',
    'text.inverse':  '#0F1115',

    # Accent
    'accent.primary':'#6D8EFF',
    'accent.hover':  '#8BA4FF',
    'accent.muted':  '#2D3654',

    # Status
    'status.ok':     '#4ADE80',
    'status.warn':   '#FBBF24',
    'status.error':  '#F87171',
    'status.info':   '#60A5FA',
    'status.pending':'#6B7080',
}

SPACING = {
    'xxs': 2, 'xs': 4, 'sm': 8, 'md': 12,
    'lg': 16, 'xl': 24, 'xxl': 32, 'xxxl': 48,
}

RADIUS = {'sm': 4, 'md': 6, 'lg': 10, 'xl': 14}

FONT = {
    'family.ui':   'Inter, -apple-system, Segoe UI, sans-serif',
    'family.mono': 'JetBrains Mono, SF Mono, Consolas, monospace',
    'size.xs':   11,
    'size.sm':   12,
    'size.md':   13,
    'size.lg':   14,
    'size.xl':   16,
    'size.xxl':  20,
    'weight.normal': 400,
    'weight.medium': 500,
    'weight.bold':   600,
}

# Layout constants
LAYOUT = {
    'rail.width':         44,
    'sourcenav.min':      220,
    'sourcenav.default':  260,
    'detail.min':         340,
    'detail.default':     420,
    'topbar.height':      48,
    'statusbar.height':   24,
    'row.height':         32,
    'window.min.width':   1100,
    'window.min.height':  700,
}
