"""
Address management, address choice and "your usual items" (fridge_to_fork/instamart_addresses.py and
the address handling in instamart.py). Fixtures follow Swiggy's reference docs for get_addresses
(paged, no coordinates), create_address (response is only {addressId}), delete_address and
your_go_to_items (SearchProduct[]). Run: python -m unittest tests.test_instamart_addresses
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import app as a
from fridge_to_fork import instamart, instamart_addresses
from fridge_to_fork.instamart import InstamartError
from tests.test_instamart import ADDRESSES, TOMATO_SEARCH, FakeSession, envelope, signed_bearer, using

WORK = {"id": "addr-work", "addressLine": "Tower B, Whitefield", "phoneNumber": "9000000001", "addressCategory": "WORK"}
HOME = {"id": "addr-home", "addressLine": "12 MG Road, Bengaluru", "phoneNumber": "9876543210", "addressTag": "Home", "addressCategory": "HOME"}
NEW = {"id": "addr-new", "addressLine": "5 Park Street, Kolkata", "phoneNumber": "9876543210", "addressTag": "Parents", "addressCategory": "FRIENDS_AND_FAMILY"}


def page(rows, *, page_no=1, has_more=False):
    return envelope({"addresses": rows, "pagination": {"page": page_no, "pageSize": 10, "total": len(rows), "totalPages": 1, "hasMore": has_more}})


CREATE_FIELDS = {
    "full_address": "5 Park Street, Kolkata 700016", "address_line": "5 Park Street", "address_line2": "Flat 2B", "city": "Kolkata",
    "postal_code": "700016", "address_category": "FRIENDS_AND_FAMILY", "user_name": "Asha Rao", "user_phone": "9876543210",
}


class AddressListTests(unittest.IsolatedAsyncioTestCase):
    async def test_listing_hides_phone_numbers_and_marks_the_home_default(self):
        with using(FakeSession({"get_addresses": page([WORK, HOME])})):
            out = await instamart_addresses.list_addresses("tok")
        self.assertEqual(out["defaultId"], "addr-home")
        self.assertEqual([a["id"] for a in out["addresses"]], ["addr-work", "addr-home"])
        self.assertNotIn("phone", json.dumps(out).lower())
        self.assertNotIn("9876543210", json.dumps(out))

    async def test_pagination_is_followed(self):
        s = FakeSession({"get_addresses": [page([WORK], has_more=True), page([HOME], page_no=2)]})
        with using(s):
            out = await instamart_addresses.list_addresses("tok")
        self.assertEqual([a["id"] for a in out["addresses"]], ["addr-work", "addr-home"])
        self.assertEqual([args["page"] for n, args in s.calls if n == "get_addresses"], [1, 2])

    async def test_no_addresses_is_an_empty_list_not_an_error(self):
        with using(FakeSession({"get_addresses": page([])})):
            out = await instamart_addresses.list_addresses("tok")
        self.assertEqual(out, {"addresses": [], "defaultId": None})


class AddressChoiceTests(unittest.IsolatedAsyncioTestCase):
    def search_session(self, **over):
        return FakeSession({"get_addresses": envelope(ADDRESSES), "search_products": envelope(TOMATO_SEARCH), **over})

    async def test_a_chosen_saved_address_is_used_for_search(self):
        s = self.search_session()
        with using(s):
            out = await instamart.search_ingredients("tok", ["tomato"], "addr-work")
        self.assertEqual(out["address"]["id"], "addr-work")
        self.assertEqual(s.args("search_products")["addressId"], "addr-work")

    async def test_an_address_that_is_not_saved_is_refused_before_searching(self):
        s = self.search_session()
        with using(s), self.assertRaises(InstamartError) as ctx:
            await instamart.search_ingredients("tok", ["tomato"], "addr-someone-elses")
        self.assertEqual(ctx.exception.code, "address_not_found")
        self.assertNotIn("search_products", s.names())

    async def test_no_choice_falls_back_to_home(self):
        with using(self.search_session()):
            out = await instamart.search_ingredients("tok", ["tomato"])
        self.assertEqual(out["address"]["id"], "addr-home")


class CreateAddressTests(unittest.IsolatedAsyncioTestCase):
    def session(self, **over):
        return FakeSession({"create_address": envelope({"addressId": "addr-new"}), "get_addresses": page([HOME, NEW]), **over})

    async def test_required_fields_are_mapped_to_swiggys_names_and_optionals_omitted(self):
        s = self.session()
        with using(s):
            await instamart_addresses.create_address("tok", CREATE_FIELDS)
        self.assertEqual(s.args("create_address"), {
            "fullAddress": "5 Park Street, Kolkata 700016", "addressLine": "5 Park Street", "addressLine2": "Flat 2B", "city": "Kolkata",
            "postalCode": "700016", "addressCategory": "FRIENDS_AND_FAMILY", "userName": "Asha Rao", "userPhone": "9876543210",
        })  # no latitude/longitude/locality/addressTag keys: Swiggy resolves coordinates itself

    async def test_real_coordinates_and_optional_fields_are_passed_through_when_given(self):
        s = self.session()
        fields = {**CREATE_FIELDS, "latitude": 22.55, "longitude": 88.35, "locality": "Park Street", "address_tag": "Parents"}
        with using(s):
            await instamart_addresses.create_address("tok", fields)
        args = s.args("create_address")
        self.assertEqual((args["latitude"], args["longitude"], args["locality"], args["addressTag"]), (22.55, 88.35, "Park Street", "Parents"))

    async def test_the_response_only_has_an_id_so_the_list_is_refetched(self):
        s = self.session()
        with using(s):
            out = await instamart_addresses.create_address("tok", CREATE_FIELDS)
        self.assertEqual(out["addressId"], "addr-new")
        self.assertEqual([a["id"] for a in out["addresses"]], ["addr-home", "addr-new"])
        self.assertEqual(s.names(), ["create_address", "get_addresses"])
        self.assertNotIn("9876543210", json.dumps(out))

    async def test_swiggy_not_returning_an_id_is_an_error_not_a_silent_success(self):
        with using(self.session(create_address=envelope({}))), self.assertRaises(InstamartError):
            await instamart_addresses.create_address("tok", CREATE_FIELDS)

    async def test_swiggy_rejecting_the_address_surfaces_its_message(self):
        with using(self.session(create_address=envelope(success=False, error="Invalid postal code"))), self.assertRaises(InstamartError) as ctx:
            await instamart_addresses.create_address("tok", CREATE_FIELDS)
        self.assertEqual(ctx.exception.message, "Invalid postal code")

    async def test_a_second_create_while_one_is_running_is_refused(self):
        gate = asyncio.Event()

        async def slow(_args):
            await gate.wait()
            return envelope({"addressId": "addr-new"})

        s = self.session(create_address=slow)
        with using(s):
            first = asyncio.create_task(instamart_addresses.create_address("tok", CREATE_FIELDS))
            await asyncio.sleep(0.05)
            with self.assertRaises(InstamartError) as ctx:
                await instamart_addresses.create_address("tok", CREATE_FIELDS)
            gate.set()
            await first
        self.assertEqual(ctx.exception.code, "address_in_progress")
        self.assertEqual(s.names().count("create_address"), 1)
        self.assertNotIn(instamart._account("tok"), instamart_addresses._busy)  # lock released


class DeleteAddressTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_verifies_ownership_then_deletes_then_relists(self):
        s = FakeSession({"get_addresses": [page([HOME, NEW]), page([HOME])], "delete_address": envelope({"statusCode": 200, "statusMessage": "ok"})})
        with using(s):
            out = await instamart_addresses.delete_address("tok", "addr-new")
        self.assertEqual(s.names(), ["get_addresses", "delete_address", "get_addresses"])
        self.assertEqual(s.args("delete_address"), {"addressId": "addr-new"})
        self.assertEqual([a["id"] for a in out["addresses"]], ["addr-home"])

    async def test_an_id_that_is_not_the_users_is_never_sent_to_delete(self):
        s = FakeSession({"get_addresses": page([HOME])})
        with using(s), self.assertRaises(InstamartError) as ctx:
            await instamart_addresses.delete_address("tok", "addr-not-mine")
        self.assertEqual(ctx.exception.code, "address_not_found")
        self.assertNotIn("delete_address", s.names())

    async def test_swiggy_refusing_the_delete_surfaces_its_message_and_releases_the_lock(self):
        s = FakeSession({"get_addresses": page([HOME]), "delete_address": envelope(success=False, error="Address is in use")})
        with using(s), self.assertRaises(InstamartError) as ctx:
            await instamart_addresses.delete_address("tok", "addr-home")
        self.assertEqual(ctx.exception.message, "Address is in use")
        self.assertNotIn(instamart._account("tok"), instamart_addresses._busy)


class GoToItemsTests(unittest.IsolatedAsyncioTestCase):
    async def test_go_to_products_become_pickable_rows_with_only_available_variations(self):
        s = FakeSession({"your_go_to_items": envelope(TOMATO_SEARCH)})
        with using(s):
            out = await instamart_addresses.go_to_items("tok", "addr-home")
        self.assertEqual(s.args("your_go_to_items"), {"addressId": "addr-home"})
        (row,) = out["results"]  # the OOS puree product contributes nothing
        self.assertEqual(row["ingredient"], "Fresh Tomato (Hybrid)")
        self.assertEqual([o["spinId"] for o in row["options"]], ["spin-t500"])
        self.assertEqual((row["options"][0]["skuId"], row["options"][0]["price"]), ("sku-t500", 32.0))

    async def test_only_a_bounded_number_are_returned(self):
        many = {"products": [{"displayName": f"P{i}", "variations": [{"spinId": f"s{i}", "skuId": f"k{i}", "price": {}, "isInStockAndAvailable": True}]} for i in range(30)]}
        with using(FakeSession({"your_go_to_items": envelope(many)})):
            out = await instamart_addresses.go_to_items("tok", "addr-home")
        self.assertEqual(len(out["results"]), instamart_addresses.MAX_GO_TO_ITEMS)

    async def test_an_unavailable_tool_never_breaks_the_sheet(self):
        with using(FakeSession({"your_go_to_items": envelope(success=False, error="unknown tool")})):
            self.assertEqual(await instamart_addresses.go_to_items("tok", "addr-home"), {"results": []})

    async def test_auth_expiry_still_propagates(self):
        with using(FakeSession({"your_go_to_items": envelope(success=False, error="TOKEN_EXPIRED")})), self.assertRaises(InstamartError):
            await instamart_addresses.go_to_items("tok", "addr-home")


class AddressRouteTests(unittest.TestCase):
    BODY = {
        "full_address": "5 Park Street, Kolkata 700016", "address_line": "5 Park Street", "address_line2": "Flat 2B", "city": "Kolkata",
        "postal_code": "700016", "address_category": "OTHER", "user_name": "Asha Rao", "user_phone": "+919876543210",
    }

    def setUp(self):
        self.client = TestClient(a.app)

    def test_every_route_requires_auth(self):
        for path, body in (("addresses", {}), ("address", self.BODY), ("address-delete", {"address_id": "x"}), ("go-to-items", {"address_id": "x"})):
            r = self.client.post(f"/api/instamart/{path}", json=body)
            self.assertEqual((r.status_code, r.json()["error"]["code"]), (401, "auth_required"), path)

    def test_create_route_passes_only_provided_fields(self):
        with patch.object(instamart_addresses, "create_address", AsyncMock(return_value={"addressId": "n", "addresses": [], "defaultId": None})) as fn:
            r = self.client.post("/api/instamart/address", json=self.BODY, headers=signed_bearer())
        self.assertTrue(r.json()["ok"])
        token, fields = fn.await_args.args
        self.assertEqual(token, "swiggy-tok")
        self.assertEqual(fields["user_phone"], "+919876543210")
        self.assertNotIn("latitude", fields)
        self.assertNotIn("locality", fields)

    def test_create_route_validation(self):
        h = signed_bearer()
        bad = {
            "short pin": {**self.BODY, "postal_code": "7000"},
            "letters in phone": {**self.BODY, "user_phone": "call me"},
            "unknown category": {**self.BODY, "address_category": "CASTLE"},
            "empty name": {**self.BODY, "user_name": "  "},
            "lat without lng": {**self.BODY, "latitude": 22.5},
            "lat out of range": {**self.BODY, "latitude": 99, "longitude": 88},
        }
        for label, body in bad.items():
            self.assertEqual(self.client.post("/api/instamart/address", json=body, headers=h).status_code, 422, label)
        missing = {k: v for k, v in self.BODY.items() if k != "user_phone"}
        self.assertEqual(self.client.post("/api/instamart/address", json=missing, headers=h).status_code, 422)

    def test_search_route_accepts_an_address_choice(self):
        with patch.object(instamart, "search_ingredients", AsyncMock(return_value={"address": {}, "results": []})) as fn:
            self.client.post("/api/instamart/search", json={"items": ["tomato"], "address_id": "addr-work"}, headers=signed_bearer())
        self.assertEqual(fn.await_args.args, ("swiggy-tok", ["tomato"], "addr-work"))


if __name__ == "__main__":
    unittest.main()
