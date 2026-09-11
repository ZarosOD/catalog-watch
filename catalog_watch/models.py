"""The three things this tool moves around: a Product, a Snapshot, a Change.

Nothing here touches the network or the filesystem, so it is cheap to test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

# Availability is normalised to one of these, or left None and flagged. A
# storefront that prints something we do not recognise is a fact worth
# reporting, not a value worth guessing at.
IN_STOCK = "in_stock"
OUT_OF_STOCK = "out_of_stock"
BACKORDER = "backorder"
PREORDER = "preorder"
DISCONTINUED = "discontinued"

AVAILABILITY_VALUES = (IN_STOCK, OUT_OF_STOCK, BACKORDER, PREORDER, DISCONTINUED)

# Fields compared between runs, in the order they appear in the summary.
TRACKED_FIELDS = ("price", "availability", "name")


@dataclass
class Product:
    """One product card as it was read off the page.

    A field that could not be read is None and has a matching line in
    ``issues``. It is never filled in from a default, from the previous run,
    or from another field.
    """

    sku: str
    name: str | None = None
    price: Decimal | None = None
    currency: str | None = None
    availability: str | None = None
    url: str | None = None
    issues: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return bool(self.issues)

    def flag(self, issue: str) -> None:
        if issue not in self.issues:
            self.issues.append(issue)

    def to_json(self) -> dict:
        return {
            "sku": self.sku,
            "name": self.name,
            "price": None if self.price is None else str(self.price),
            "currency": self.currency,
            "availability": self.availability,
            "url": self.url,
            "issues": list(self.issues),
        }

    @classmethod
    def from_json(cls, data: dict) -> Product:
        price = data.get("price")
        return cls(
            sku=data["sku"],
            name=data.get("name"),
            price=None if price is None else Decimal(price),
            currency=data.get("currency"),
            availability=data.get("availability"),
            url=data.get("url"),
            issues=list(data.get("issues") or []),
        )


@dataclass
class Snapshot:
    """Everything one run saw, plus where and when it saw it."""

    url: str
    scraped_at: str
    products: list[Product] = field(default_factory=list)
    pages: int = 0

    def by_sku(self) -> dict[str, Product]:
        return {p.sku: p for p in self.products}

    @property
    def clean_count(self) -> int:
        return sum(1 for p in self.products if not p.needs_review)

    @property
    def review_count(self) -> int:
        return sum(1 for p in self.products if p.needs_review)

    def to_json(self) -> dict:
        return {
            "version": 1,
            "url": self.url,
            "scraped_at": self.scraped_at,
            "pages": self.pages,
            "products": [p.to_json() for p in self.products],
        }

    @classmethod
    def from_json(cls, data: dict) -> Snapshot:
        return cls(
            url=data.get("url", ""),
            scraped_at=data.get("scraped_at", ""),
            pages=data.get("pages", 0),
            products=[Product.from_json(p) for p in data.get("products", [])],
        )


# Change kinds. "unreadable" and "first_read" exist so that a field we simply
# could not read this run never masquerades as a price move or a restock.
NEW = "new"
DELISTED = "delisted"
UNREADABLE = "unreadable"
FIRST_READ = "first_read"

KIND_ORDER = ("price", "availability", "name", NEW, DELISTED, UNREADABLE, FIRST_READ)


@dataclass(frozen=True)
class Change:
    kind: str
    sku: str
    name: str | None = None
    before: str | None = None
    after: str | None = None
    note: str = ""

    @property
    def sort_key(self) -> tuple[int, str]:
        try:
            rank = KIND_ORDER.index(self.kind)
        except ValueError:
            rank = len(KIND_ORDER)
        return (rank, self.sku)

    def to_json(self) -> dict:
        return {
            "kind": self.kind,
            "sku": self.sku,
            "name": self.name,
            "before": self.before,
            "after": self.after,
            "note": self.note,
        }
