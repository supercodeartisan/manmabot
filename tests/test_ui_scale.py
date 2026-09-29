from manmabot_v1.ui.design_system import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    DESIGN_WIDTH,
    compute_ui_scale,
)


def test_default_window_size():
    assert DEFAULT_WIDTH == 1187
    assert DEFAULT_HEIGHT == 806


def test_compact_window_uses_minimum_scale():
    assert compute_ui_scale(800, 600) == 0.55
    assert compute_ui_scale(1, 1) == DEFAULT_WIDTH / DESIGN_WIDTH


def test_default_window_scale_matches_width():
    assert abs(compute_ui_scale(1187, 806) - (1187 / 1760)) < 1e-6


def test_design_window_is_full_scale():
    assert compute_ui_scale(1760, 1000) == 1.0
    assert 0.55 < compute_ui_scale(1200, 800) < 1.0
