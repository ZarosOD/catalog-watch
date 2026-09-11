"""What to scrape, as data rather than as code.

A site profile is a small JSON file: one CSS selector for a product card, one
per field, one for the "next page" link. Pointing this tool at a different
storefront is writing one of these, not editing Python. ``sites/fixture.json``
is the profile for the bundled demo site.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .models import (
    AVAILABILITY_VALUES,
    BACKORDER,
    DISCONTINUED,
    IN_STOCK,
    OUT_OF_STOCK,
    PREORDER,
)

# Text a storefront prints, mapped to the value we store. A profile can add to
# this; anything still unmatched is reported rather than assumed in stock.
DEFAULT_AVAILABILITY_MAP: dict[str, str] = {
    "in stock": IN_STOCK,
    "instock": IN_STOCK,
    "available": IN_STOCK,
    "ships today": IN_STOCK,
    "out of stock": OUT_OF_STOCK,
    "outofstock": OUT_OF_STOCK,
    "sold out": OUT_OF_STOCK,
    "unavailable": OUT_OF_STOCK,
    "backorder": BACKORDER,
    "back-order": BACKORDER,
    "on backorder": BACKORDER,
    "preorder": PREORDER,
    "pre-order": PREORDER,
    "discontinued": DISCONTINUED,
}

VALID_PARSERS = ("text", "money", "availability", "url")

# A profile can only fill in fields a Product actually has. Catching a typo
# here beats scraping 40 pages and finding the column empty.
KNOWN_FIELDS = ("sku", "name", "price", "availability", "url")


class SiteConfigError(ValueError):
    """The profile is malformed. Raised at load time, not mid-crawl."""


@dataclass(frozen=True)
class FieldSpec:
    """How to get one field out of a product card."""

    selector: str
    attr: str | None = None  # read this attribute instead of the text
    parse: str = "text"

    @classmethod
    def from_json(cls, name: str, data: dict) -> FieldSpec:
        if not isinstance(data, dict):
            raise SiteConfigError(f"field {name!r}: expected an object")
        if "selector" not in data:
            raise SiteConfigError(f"field {name!r}: missing 'selector'")
        parse = data.get("parse", "text")
        if parse not in VALID_PARSERS:
            raise SiteConfigError(
                f"field {name!r}: unknown parse {parse!r}; "
                f"expected one of {', '.join(VALID_PARSERS)}"
            )
        return cls(selector=data["selector"], attr=data.get("attr"), parse=parse)


@dataclass(frozen=True)
class SiteConfig:
    name: str
    product_selector: str
    fields: dict[str, FieldSpec]
    required: tuple[str, ...] = ("sku",)
    next_selector: str | None = None
    max_pages: int = 25
    availability_map: dict[str, str] = field(default_factory=dict)

    def normalise_availability(self, text: str) -> str | None:
        """None means "this storefront printed something we do not recognise"."""
        key = " ".join(text.lower().split())
        merged = {**DEFAULT_AVAILABILITY_MAP, **self.availability_map}
        if key in merged:
            return merged[key]
        if key in AVAILABILITY_VALUES:
            return key
        return None

    @classmethod
    def from_json(cls, data: dict) -> SiteConfig:
        if not isinstance(data, dict):
            raise SiteConfigError("a site profile must be a JSON object")
        product = data.get("product") or {}
        selector = product.get("selector")
        if not selector:
            raise SiteConfigError("missing 'product.selector'")

        raw_fields = data.get("fields") or {}
        if "sku" not in raw_fields:
            raise SiteConfigError(
                "missing field 'sku'. Products are matched between runs by sku, "
                "so there has to be one."
            )
        stray = [n for n in raw_fields if n not in KNOWN_FIELDS]
        if stray:
            raise SiteConfigError(
                f"unknown field(s) {', '.join(sorted(stray))}; "
                f"this tool tracks {', '.join(KNOWN_FIELDS)}"
            )
        fields = {n: FieldSpec.from_json(n, f) for n, f in raw_fields.items()}

        required = tuple(data.get("required") or ("sku",))
        unknown = [r for r in required if r not in fields]
        if unknown:
            raise SiteConfigError(
                f"'required' names fields that are not defined: {', '.join(unknown)}"
            )

        pagination = data.get("pagination") or {}
        return cls(
            name=data.get("name", "unnamed site"),
            product_selector=selector,
            fields=fields,
            required=required,
            next_selector=pagination.get("next_selector"),
            max_pages=int(pagination.get("max_pages", 25)),
            availability_map=dict(data.get("availability_map") or {}),
        )

    @classmethod
    def load(cls, path: str | Path) -> SiteConfig:
        path = Path(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise SiteConfigError(f"no site profile at {path}") from None
        except json.JSONDecodeError as exc:
            raise SiteConfigError(f"{path} is not valid JSON: {exc}") from None
        return cls.from_json(raw)
