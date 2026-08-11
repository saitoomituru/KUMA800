"""静的に同梱するSeason 1 scraper adapter。"""

from .base import ScraperAdapter
from .dummy import DummyKumaAdapter

__all__ = ["DummyKumaAdapter", "ScraperAdapter"]
