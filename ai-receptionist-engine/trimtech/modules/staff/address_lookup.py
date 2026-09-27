"""Server-side Ideal Postcodes adapter. Never return provider coordinates or keys."""
import os
import re

import requests


class AddressLookupError(Exception):
    pass


def lookup(query=None, address_id=None):
    if os.getenv("STAFF_ADDRESS_LOOKUP_ENVIRONMENT") != "staging":
        raise AddressLookupError("Address search is not enabled here. Enter the address manually.")
    key = os.getenv("STAFF_IDEAL_POSTCODES_API_KEY", "").strip()
    if not key:
        raise AddressLookupError("Address search is not configured. Enter the address manually.")
    path = "/autocomplete/addresses"
    if address_id is not None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", address_id):
            raise ValueError("Choose an address from the search results.")
        path += f"/{address_id}/gbr"
        params = {}
    else:
        query = (query or "").strip()
        if not 3 <= len(query) <= 200:
            raise ValueError("Enter between 3 and 200 characters to search.")
        params = {"query": query, "context": "GBR", "limit": 20}
    try:
        response = requests.get("https://api.ideal-postcodes.co.uk/v1" + path,
            params=params, headers={"Authorization": f'api_key="{key}"'},
            timeout=(3, 8), allow_redirects=False)
        if response.status_code != 200:
            raise AddressLookupError("Address search is unavailable. Try again or enter the address manually.")
        payload = response.json()
        if payload.get("code") != 2000:
            raise AddressLookupError("Address search is unavailable. Try again or enter the address manually.")
        result = payload["result"]
        if address_id is None:
            return {"suggestions": [{"id": hit["id"], "label": hit["suggestion"]}
                for hit in result["hits"][:20]]}
        # Deliberately exclude latitude/longitude, even when supplied by the provider.
        parts = [result.get(field, "").strip() for field in
                 ("line_1", "line_2", "line_3", "post_town", "postcode")]
        if not parts[0] or not parts[-1]:
            raise AddressLookupError("The selected address is incomplete. Enter it manually.")
        return {"address": ", ".join(part for part in parts if part)}
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        # Exceptions may contain the key or provider response: do not expose/log them.
        raise AddressLookupError("Address search is unavailable. Try again or enter the address manually.") from None
