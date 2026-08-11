"""静的に同梱するSeason 1 scraper adapter。"""

from .base import ScraperAdapter
from .dummy import DummyKumaAdapter
from .yamagata_csv import YamagataCsvAdapter

__all__ = ["DummyKumaAdapter", "ScraperAdapter", "YamagataCsvAdapter"]
