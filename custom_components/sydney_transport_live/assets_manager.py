"""Install static assets (map markers) into HA's /local www folder."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TypedDict

from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    MARKER_CENTRAL_FILENAME,
    MARKER_CITY_FILENAME,
    MARKER_DEFAULT_FILENAME,
)

_LOGGER = logging.getLogger(__name__)


class MarkerUrls(TypedDict):
    """Public /local URLs for direction-coded map markers."""

    city: str
    central: str
    default: str


def install_map_assets(hass: HomeAssistant) -> MarkerUrls:
    """Copy marker SVGs to config/www and return their /local URL paths."""
    assets_dir = Path(__file__).parent / "assets"
    dest_dir = Path(hass.config.path("www", DOMAIN))
    dest_dir.mkdir(parents=True, exist_ok=True)

    urls: MarkerUrls = {
        "city": "",
        "central": "",
        "default": "",
    }
    for key, filename in (
        ("city", MARKER_CITY_FILENAME),
        ("central", MARKER_CENTRAL_FILENAME),
        ("default", MARKER_DEFAULT_FILENAME),
    ):
        src = assets_dir / filename
        dest = dest_dir / filename
        if src.exists():
            shutil.copyfile(src, dest)
            urls[key] = f"/local/{DOMAIN}/{filename}"
            _LOGGER.debug("Installed map marker asset to %s", dest)
        else:
            _LOGGER.warning("Map marker asset missing: %s", src)

    return urls
