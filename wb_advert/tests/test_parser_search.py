"""Unit tests for WB parser regions and search."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from wb_advert.parser.regions import (
    clear_dest_cache,
    normalize_region_key,
    resolve_dest,
    resolve_dest_via_geo,
)
from wb_advert.parser.search import (
    COMPETITORS_SLICE_SIZE,
    DEFAULT_PAUSE_SEC,
    PRODUCTS_PER_PAGE,
    SEARCH_URL,
    WbSearchParser,
    _extract_products,
    _price_rub_from_product,
    build_competitors_slice,
)


@pytest.fixture(autouse=True)
def _clear_dest_cache():
    clear_dest_cache()
    yield
    clear_dest_cache()


def test_normalize_region_key_defaults_to_moscow():
    assert normalize_region_key(None) == "moscow"
    assert normalize_region_key("") == "moscow"
    assert normalize_region_key("Moscow") == "moscow"
    assert normalize_region_key("Краснодар") == "krasnodar"


def test_resolve_dest_explicit_override():
    assert resolve_dest("moscow", "999") == "999"


def test_resolve_dest_via_geo_parses_xinfo():
    response = httpx.Response(
        200,
        json={"xinfo": "curr=rub&dest=1259570991&locale=ru"},
        request=httpx.Request("GET", "https://example.test"),
    )
    client = MagicMock()
    client.get.return_value = response
    assert resolve_dest_via_geo("moscow", client=client) == "1259570991"


def test_resolve_dest_uses_geo_then_caches():
    response = httpx.Response(
        200,
        json={"destinations": [1259570991]},
        request=httpx.Request("GET", "https://example.test"),
    )
    client = MagicMock()
    client.get.return_value = response

    with patch("wb_advert.parser.regions.resolve_dest_via_geo", return_value="1259570991"):
        first = resolve_dest("moscow")
        second = resolve_dest("moscow")
    assert first == "1259570991"
    assert second == "1259570991"


def test_resolve_dest_falls_back_to_legacy_on_geo_failure():
    with patch("wb_advert.parser.regions.resolve_dest_via_geo", return_value=None):
        assert resolve_dest("krasnodar") == "-1059500"


def test_extract_products_nested_data():
    payload = {"data": {"products": [{"id": 1}]}}
    assert _extract_products(payload) == [{"id": 1}]


def test_fetch_page_uses_v18_and_limit_100():
    parser = WbSearchParser(region="moscow", dest="1259570991", pause_sec=0.01)
    search_response = httpx.Response(
        200,
        json={"products": [{"id": 42}]},
        request=httpx.Request("GET", SEARCH_URL),
    )
    parser._session = MagicMock()
    parser._session.get.return_value = search_response

    status, products, err = parser._fetch_page("перчатки", 1)

    assert status == 200
    assert err is None
    assert products == [{"id": 42}]
    call = parser._session.get.call_args
    assert call.args[0] == SEARCH_URL
    assert call.kwargs["params"]["limit"] == "100"
    assert call.kwargs["params"]["dest"] == "1259570991"
    parser.close()


def test_find_position_calculates_page_offset():
    parser = WbSearchParser(region="moscow", dest="1259570991", pause_sec=0.01, max_pages=2)

    page1 = httpx.Response(
        200,
        json={"products": [{"id": i} for i in range(1, PRODUCTS_PER_PAGE + 1)]},
        request=httpx.Request("GET", SEARCH_URL),
    )
    page2 = httpx.Response(
        200,
        json={"products": [{"id": PRODUCTS_PER_PAGE + 1}]},
        request=httpx.Request("GET", SEARCH_URL),
    )
    parser._session = MagicMock()
    parser._session.get.side_effect = [page1, page2]

    result = parser.find_position("перчатки", PRODUCTS_PER_PAGE + 1)

    assert result["found"] is True
    assert result["position"] == PRODUCTS_PER_PAGE + 1
    assert result["region_key"] == "moscow"
    parser.close()


def test_default_pause_matches_wb_pars_range():
    assert 0.3 <= DEFAULT_PAUSE_SEC <= 0.5


def _product(
    nm_id: int,
    *,
    brand: str | None = "Brand",
    price_kopecks: int | None = 11500,
    rating: float = 4.9,
    feedbacks: int = 10,
    with_sizes: bool = True,
) -> dict:
    product: dict = {
        "id": nm_id,
        "brand": brand,
        "reviewRating": rating,
        "feedbacks": feedbacks,
    }
    if with_sizes and price_kopecks is not None:
        product["sizes"] = [{"price": {"product": price_kopecks}}]
    return product


def test_price_rub_from_product_converts_kopecks():
    assert _price_rub_from_product(_product(1, price_kopecks=11500)) == 115.0
    assert _price_rub_from_product(_product(1, price_kopecks=8600)) == 86.0


def test_price_rub_from_product_handles_missing_sizes():
    assert _price_rub_from_product({"id": 1}) is None
    assert _price_rub_from_product({"id": 1, "sizes": []}) is None
    assert _price_rub_from_product({"id": 1, "sizes": [{}]}) is None
    assert _price_rub_from_product({"id": 1, "sizes": [{"price": {}}]}) is None


def test_build_competitors_slice_marks_our_card():
    products = [
        _product(907517204, brand=None, price_kopecks=11500, feedbacks=55),
        _product(390432547, brand="BIG City", price_kopecks=8600, feedbacks=324),
        _product(624468743, brand="Dora", price_kopecks=13600, feedbacks=2236),
    ]
    result = build_competitors_slice(products, 624468743)

    assert result["our_in_slice"] is True
    assert len(result["competitors_slice"]) == 3
    ours = result["competitors_slice"][2]
    assert ours["nm_id"] == 624468743
    assert ours["position"] == 3
    assert ours["brand"] == "Dora"
    assert ours["price_rub"] == 136.0
    assert ours["rating"] == 4.9
    assert ours["feedbacks"] == 2236
    assert ours["is_ours"] is True
    assert result["competitors_slice"][0]["is_ours"] is False


def test_build_competitors_slice_limits_to_top_n():
    products = [_product(i, price_kopecks=10000 + i) for i in range(1, 25)]
    result = build_competitors_slice(products, 999)

    assert len(result["competitors_slice"]) == COMPETITORS_SLICE_SIZE
    assert result["our_in_slice"] is False


def test_find_position_attaches_competitors_slice_without_extra_requests():
    parser = WbSearchParser(region="moscow", dest="1259570991", pause_sec=0.01, max_pages=2)
    page1_products = [
        _product(907517204, brand=None, price_kopecks=11500),
        _product(390432547, brand="BIG City", price_kopecks=8600),
        _product(624468743, brand="Dora", price_kopecks=13600),
    ] + [_product(i, price_kopecks=10000) for i in range(4, PRODUCTS_PER_PAGE + 1)]

    page1 = httpx.Response(
        200,
        json={"products": page1_products},
        request=httpx.Request("GET", SEARCH_URL),
    )
    page2 = httpx.Response(
        200,
        json={"products": [{"id": PRODUCTS_PER_PAGE + 1}]},
        request=httpx.Request("GET", SEARCH_URL),
    )
    parser._session = MagicMock()
    parser._session.get.side_effect = [page1, page2]

    result = parser.find_position("перчатки", 624468743)

    assert parser._session.get.call_count == 1
    assert result["found"] is True
    assert result["position"] == 3
    assert result["our_in_slice"] is True
    assert len(result["competitors_slice"]) == COMPETITORS_SLICE_SIZE
    assert result["competitors_slice"][2]["is_ours"] is True
    parser.close()


def test_find_position_saves_slice_when_our_card_not_in_results():
    parser = WbSearchParser(region="moscow", dest="1259570991", pause_sec=0.01, max_pages=1)
    products = [
        _product(907517204, price_kopecks=11500),
        _product(390432547, price_kopecks=8600),
    ]
    page1 = httpx.Response(
        200,
        json={"products": products},
        request=httpx.Request("GET", SEARCH_URL),
    )
    parser._session = MagicMock()
    parser._session.get.return_value = page1

    result = parser.find_position("перчатки", 624468743)

    assert parser._session.get.call_count == 1
    assert result["found"] is False
    assert result["our_in_slice"] is False
    assert len(result["competitors_slice"]) == 2
    assert all(not row["is_ours"] for row in result["competitors_slice"])
    parser.close()
