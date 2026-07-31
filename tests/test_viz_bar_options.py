import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.constants import VisualizerSettings
from core.settings import normalize_settings


def test_viz_bar_options_match_supported_renderer_range():
    assert VisualizerSettings.BAR_OPTIONS == [
        4,
        8,
        16,
        32,
        48,
        64,
        128,
    ]


def test_viz_bar_count_normalization_accepts_only_supported_options():
    for value in VisualizerSettings.BAR_OPTIONS:
        normalized = normalize_settings(
            {
                "settings_version": 7,
                "viz_bar_count": value,
            }
        )
        assert normalized["viz_bar_count"] == value

    for unsupported in (96, 256, 512):
        normalized = normalize_settings(
            {
                "settings_version": 7,
                "viz_bar_count": unsupported,
            }
        )
        assert normalized["viz_bar_count"] == 32
