from __future__ import annotations

"""Small builders the unit tests share: a throwaway site profile and the HTML
it expects."""

from catalog_watch.site import SiteConfig


def make_config(**overrides) -> SiteConfig:
    """A small profile matching the HTML the unit tests write inline."""
    data = {
        "name": "test site",
        "product": {"selector": ".product"},
        "fields": {
            "sku": {"selector": ".sku"},
            "name": {"selector": ".product-name"},
            "price": {"selector": ".price", "parse": "money"},
            "availability": {"selector": ".stock", "parse": "availability"},
            "url": {"selector": "a.product-link", "attr": "href", "parse": "url"},
        },
        "required": ["sku", "name", "price"],
        "pagination": {"next_selector": "a.next"},
    }
    data.update(overrides)
    return SiteConfig.from_json(data)


def card(sku="A-1", name="Thing", price="$10.00", stock="In stock", link="p/A-1.html"):
    parts = [f'<article class="product">']
    if sku is not None:
        parts.append(f'<span class="sku">{sku}</span>')
    if name is not None:
        parts.append(f'<h2 class="product-name">{name}</h2>')
    if price is not None:
        parts.append(f'<p class="price">{price}</p>')
    if stock is not None:
        parts.append(f'<p class="stock">{stock}</p>')
    if link is not None:
        parts.append(f'<a class="product-link" href="{link}">Details</a>')
    parts.append("</article>")
    return "".join(parts)


def page(*cards_html: str, next_href: str | None = None) -> str:
    nav = f'<a class="next" href="{next_href}">Next</a>' if next_href else ""
    return f"<html><body>{''.join(cards_html)}{nav}</body></html>"
