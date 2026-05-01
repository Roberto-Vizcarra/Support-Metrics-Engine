"""Loader for property_catalog.csv. Single source of truth for KEEP property names."""

from __future__ import annotations

import csv
from functools import lru_cache

from config import PROPERTY_CATALOG_PATH


@lru_cache(maxsize=1)
def keep_properties() -> list[dict[str, str]]:
    with PROPERTY_CATALOG_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [r for r in reader if r["classification"].strip() == "KEEP"]


@lru_cache(maxsize=1)
def keep_names() -> list[str]:
    return [r["name"].strip() for r in keep_properties()]


@lru_cache(maxsize=1)
def keep_types() -> dict[str, str]:
    return {r["name"].strip(): r["type"].strip() for r in keep_properties()}


@lru_cache(maxsize=1)
def excluded_names() -> set[str]:
    with PROPERTY_CATALOG_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {
            r["name"].strip()
            for r in reader
            if r["classification"].strip() == "EXCLUDE"
        }
