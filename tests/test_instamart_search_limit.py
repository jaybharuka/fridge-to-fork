"""The Instamart search box asks for the whole first page of `search_products` (about 20 products / up to ~46 variations) through the
optional `max_options`; the checklist's batch searches keep the old cap of 5. (Live probe, 2026-09-22: `offset` does not return new
products, so there is no pagination: the first page is all there is.)"""
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import app as a
from fridge_to_fork import instamart
from tests.test_instamart import ADDRESSES, FakeSession, InstamartCase, envelope, signed_bearer, using


def product(n: int, sizes: int = 2, in_stock: bool = True) -> dict:
    return {
        "displayName": f"Product {n}", "brand": f"Brand {n}", "productId": f"P{n}", "inStock": in_stock, "isAvail": in_stock,
        "variations": [
            {"spinId": f"spin-{n}-{s}", "skuId": f"sku-{n}-{s}", "quantityDescription": f"{(s + 1) * 100} g", "displayName": f"Product {n}",
             "price": {"mrp": 60 + s, "offerPrice": 50 + s}, "isInStockAndAvailable": in_stock}
            for s in range(sizes)
        ],
    }


def page(products: list[dict]) -> dict:
    return {"products": products, "nextOffset": "1"}


class LimitTests(InstamartCase):
    def session(self, products) -> FakeSession:
        return FakeSession({"get_addresses": envelope(ADDRESSES), "search_products": envelope(page(products))})

    async def search(self, products, **kw):
        s = self.session(products)
        with using(s):
            out = await instamart.search_ingredients("tok", ["butter"], **kw)
        return s, out["results"][0]

    async def test_the_default_is_still_five_options(self):
        _, result = await self.search([product(i) for i in range(10)])  # 20 variations
        self.assertEqual(len(result["options"]), 5)

    async def test_a_larger_limit_returns_the_whole_first_page(self):
        _, result = await self.search([product(i) for i in range(10)], max_options=40)
        self.assertEqual(len(result["options"]), 20)

    async def test_the_limit_is_a_ceiling_and_swiggys_order_is_kept(self):
        _, result = await self.search([product(i, sizes=3) for i in range(20)], max_options=40)  # 60 variations available
        self.assertEqual(len(result["options"]), 40)
        # variants of one product stay side by side, in Swiggy's ranking
        self.assertEqual([o["spinId"] for o in result["options"][:6]], ["spin-0-0", "spin-0-1", "spin-0-2", "spin-1-0", "spin-1-1", "spin-1-2"])

    async def test_in_stock_options_come_first_within_the_page(self):
        _, result = await self.search([product(0, in_stock=False), product(1), product(2)], max_options=40)
        self.assertEqual([o["available"] for o in result["options"]], [True, True, True, True, False, False])
        self.assertEqual([o["spinId"] for o in result["options"][:2]], ["spin-1-0", "spin-1-1"])

    async def test_only_one_search_call_is_made_and_no_offset_is_sent(self):
        s, _ = await self.search([product(i) for i in range(3)], max_options=40)
        self.assertEqual(s.args("search_products"), {"addressId": "addr-home", "query": "butter"})
        self.assertEqual(s.names().count("search_products"), 1)

    async def test_notes_are_unchanged(self):
        s = FakeSession({"get_addresses": envelope(ADDRESSES), "search_products": envelope({"products": []})})
        with using(s):
            out = await instamart.search_ingredients("tok", ["unobtainium"], max_options=40)
        self.assertEqual(out["results"][0]["note"], "No match on Instamart")

    async def test_the_limit_applies_to_every_item_in_the_request(self):
        s = FakeSession({"get_addresses": envelope(ADDRESSES), "search_products": [envelope(page([product(i) for i in range(6)])), envelope(page([product(i) for i in range(6)]))]})
        with using(s):
            out = await instamart.search_ingredients("tok", ["a", "b"], max_options=8)
        self.assertEqual([len(r["options"]) for r in out["results"]], [8, 8])


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(a.app)

    def post(self, body):
        return self.client.post("/api/instamart/search", json=body, headers=signed_bearer())

    def test_max_options_is_passed_through_as_a_keyword(self):
        with patch.object(instamart, "search_ingredients", AsyncMock(return_value={"address": {}, "results": []})) as fn:
            r = self.post({"items": ["butter"], "max_options": 40})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(fn.await_args.args, ("swiggy-tok", ["butter"], None))
        self.assertEqual(fn.await_args.kwargs, {"max_options": 40})

    def test_omitted_means_none_so_the_default_cap_applies(self):
        with patch.object(instamart, "search_ingredients", AsyncMock(return_value={"address": {}, "results": []})) as fn:
            self.post({"items": ["butter"]})
        self.assertEqual(fn.await_args.kwargs, {"max_options": None})

    def test_out_of_range_values_are_rejected(self):
        for bad in (0, -1, 61, "lots"):
            self.assertEqual(self.post({"items": ["butter"], "max_options": bad}).status_code, 422, bad)


if __name__ == "__main__":
    unittest.main()
