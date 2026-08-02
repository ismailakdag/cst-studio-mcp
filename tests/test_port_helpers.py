"""Microstrip waveguide port placement helpers."""

from cst_mcp.execution.port_helpers import feed_line_y_range, microstrip_waveguide_port_vba


def test_feed_y_outer_is_more_negative():
    y0, y1 = feed_line_y_range(ground_y=60.0, patch_length=30.0, inset=8.0, feed_type="inset")
    assert y0 == -30.0
    assert y1 > y0


def test_port_vba_not_on_bound_and_flush_y():
    vba = microstrip_waveguide_port_vba(
        port_number=1,
        y_edge=-30.0,
        feed_width=3.2,
        substrate_height=1.6,
    )
    assert 'PortOnBound "False"' in vba
    assert 'Orientation "ymin"' in vba
    assert 'Yrange "-30", "-30"' in vba or 'Yrange "-30.0", "-30.0"' in vba
    # Z starts at ground bottom, not deep below in free space
    assert 'Zrange "-0.035"' in vba
    assert "PortOnBound \"True\"" not in vba
