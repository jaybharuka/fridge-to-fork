"""
Saved-address management and "your usual items" for Instamart (POST mcp.swiggy.com/im).

Written against Swiggy's reference docs:
  get_addresses(page, pageSize<=10)  -> data.addresses[] (WITHOUT coordinates) + pagination.hasMore
  create_address(...)                -> data.addressId ONLY. Required: fullAddress, addressLine, addressLine2,
                                        city, postalCode, addressCategory, userName, userPhone. Optional
                                        latitude/longitude are "auto-resolved if omitted" but the response
                                        never says what was resolved, so real coordinates can only come from
                                        the caller supplying them.
  delete_address(addressId)          -> permanent; the UI confirms first
  your_go_to_items(addressId)        -> data.products[] (same SearchProduct shape as search_products)

Name/phone/address text is personal data: it is passed to Swiggy and never logged here.
"""

from . import instamart
from .instamart import InstamartError, _call, _options, _pick_address, _public_address, _same_address_id, _saved_addresses

MAX_GO_TO_ITEMS = 12

# Accounts with a create/delete running. Stops a double-click from creating (or deleting) twice.
_busy: set[str] = set()

_OPTIONAL_CREATE_FIELDS = {"locality": "locality", "address_tag": "addressTag", "latitude": "latitude", "longitude": "longitude"}


def _listing(saved: list[dict]) -> dict:
    return {
        "addresses": [_public_address(a) for a in saved],
        "defaultId": _pick_address(saved)["id"] if saved else None,
    }


async def list_addresses(token: str) -> dict:
    async with instamart._session(token) as session:
        return _listing(await _saved_addresses(session))


async def create_address(token: str, fields: dict) -> dict:
    """Create a saved address on the user's Swiggy account, then return the refreshed list."""
    account = instamart._account(token)
    if account in _busy:
        raise InstamartError("address_in_progress", "An address change is already in progress. Give it a moment.")
    _busy.add(account)
    try:
        args = {
            "fullAddress": fields["full_address"],
            "addressLine": fields["address_line"],
            "addressLine2": fields["address_line2"],
            "city": fields["city"],
            "postalCode": fields["postal_code"],
            "addressCategory": fields["address_category"],
            "userName": fields["user_name"],
            "userPhone": fields["user_phone"],
            **{camel: fields[snake] for snake, camel in _OPTIONAL_CREATE_FIELDS.items() if fields.get(snake) not in (None, "")},
        }
        async with instamart._session(token) as session:
            created = await _call(session, "create_address", **args)
            address_id = created.get("addressId")
            if not address_id:
                raise InstamartError("tool_error", "Swiggy didn't confirm the new address. Check your saved addresses and try again.")
            saved = await _saved_addresses(session)
            # create_address may report only the base of the compound id get_addresses uses; everything else
            # (orders, tracking coordinates, the picker) is keyed by the get_addresses form.
            canonical = next((a["id"] for a in saved if _same_address_id(a["id"], address_id)), address_id)
            return {"addressId": str(canonical), **_listing(saved)}
    finally:
        _busy.discard(account)


async def delete_address(token: str, address_id: str) -> dict:
    """Permanently delete a saved address (verified to be one of the user's own first)."""
    account = instamart._account(token)
    if account in _busy:
        raise InstamartError("address_in_progress", "An address change is already in progress. Give it a moment.")
    _busy.add(account)
    try:
        async with instamart._session(token) as session:
            if not any(a["id"] == address_id for a in await _saved_addresses(session)):
                raise InstamartError("address_not_found", "That address isn't saved on your Swiggy account.")
            await _call(session, "delete_address", addressId=address_id)
            return _listing(await _saved_addresses(session))
    finally:
        _busy.discard(account)


async def go_to_items(token: str, address_id: str) -> dict:
    """The user's frequently/recently ordered products at this address, shaped like search results so
    they drop straight into the order sheet as picked rows. Never fails the sheet: unavailable -> empty."""
    async with instamart._session(token) as session:
        try:
            data = await _call(session, "your_go_to_items", addressId=address_id)
        except InstamartError as exc:
            if exc.code == "auth_required":
                raise
            return {"results": []}
    results = []
    for product in data.get("products") or []:
        options = [o for o in _options(product) if o["available"]]
        if options:
            results.append({"ingredient": product.get("displayName") or options[0]["name"], "options": options, "note": None})
        if len(results) >= MAX_GO_TO_ITEMS:
            break
    return {"results": results}
