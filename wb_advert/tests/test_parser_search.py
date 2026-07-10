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
    DEFAULT_PAUSE_SEC,
    PRODUCTS_PER_PAGE,
    SEARCH_URL,
    WbSearchParser,
    _extract_products,
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
    parser._client = MagicMock()
    parser._client.get.return_value = search_response

    status, products, err = parser._fetch_page("перчатки", 1)

    assert status == 200
    assert err is None
    assert products == [{"id": 42}]
    call = parser._client.get.call_args
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
    parser._client = MagicMock()
    parser._client.get.side_effect = [page1, page2]

    result = parser.find_position("перчатки", PRODUCTS_PER_PAGE + 1)

    assert result["found"] is True
    assert result["position"] == PRODUCTS_PER_PAGE + 1
    assert result["region_key"] == "moscow"
    parser.close()


def test_default_pause_matches_wb_pars_range():
    assert 0.3 <= DEFAULT_PAUSE_SEC <= 0.5
