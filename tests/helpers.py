from __future__ import annotations

"""Small builders the unit tests share: a throwaway site profile and the HTML
it expects."""

from catalog_watch.site import SiteConfig


#: The four selectable fields every profile in this suite has had since the
#: piece was written. Named so a test about the two added on THE-452 does not
#: have to restate the four it is not about — a restated fixture is how a
#: helper ends up pinning the field it is being used to measure.
BASE_FIELDS = {
    "sku": {"selector": ".sku"},
    "name": {"selector": ".product-name"},
    "price": {"selector": ".price", "parse": "money"},
    "availability": {"selector": ".stock", "parse": "availability"},
    "url": {"selector": "a.product-link", "attr": "href", "parse": "url"},
}


def make_config(**overrides) -> SiteConfig:
    """A small profile matching the HTML the unit tests write inline."""
    data = {
        "name": "test site",
        "product": {"selector": ".product"},
        "fields": dict(BASE_FIELDS),
        "required": ["sku", "name", "price"],
        "pagination": {"next_selector": "a.next"},
    }
    data.update(overrides)
    return SiteConfig.from_json(data)


def make_config_with_extras(**overrides) -> SiteConfig:
    """`make_config`'s profile with `category` and `description` declared too."""
    fields = {**BASE_FIELDS, **EXTRA_FIELDS}
    return make_config(fields=fields, **overrides)


#: The two fields a profile may declare on top of `make_config`'s four, with
#: the selectors `card()` below emits for them. One pair, so the scrape, diff,
#: report and end-to-end tests cannot drift apart on what a profile looks like.
#: `make_config()` does *not* include these: a profile that declares no
#: category is the common case and stays the default here.
EXTRA_FIELDS = {
    "category": {"selector": ".category"},
    "description": {"selector": ".blurb"},
}


def card(
    sku="A-1",
    name="Thing",
    price="$10.00",
    stock="In stock",
    link="p/A-1.html",
    category=None,
    description=None,
):
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
    if category is not None:
        parts.append(f'<p class="category">{category}</p>')
    if description is not None:
        parts.append(f'<p class="blurb">{description}</p>')
    parts.append("</article>")
    return "".join(parts)


def page(*cards_html: str, next_href: str | None = None) -> str:
    nav = f'<a class="next" href="{next_href}">Next</a>' if next_href else ""
    return f"<html><body>{''.join(cards_html)}{nav}</body></html>"
