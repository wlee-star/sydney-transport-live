"""Install static assets (map markers) into HA's /local www folder."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_MARKER_FILENAME = "marker_311.svg"


def install_map_assets(hass: HomeAssistant) -> str:
    """Copy marker SVG to config/www and return the /local URL path."""
    src = Path(__file__).parent / "assets" / _MARKER_FILENAME
    dest_dir = Path(hass.config.path("www", DOMAIN))
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / _MARKER_FILENAME
    if src.exists():
        shutil.copyfile(src, dest)
        _LOGGER.debug("Installed map marker asset to %s", dest)
    else:
        _LOGGER.warning("Map marker asset missing: %s", src)
    return f"/local/{DOMAIN}/{_MARKER_FILENAME}"
