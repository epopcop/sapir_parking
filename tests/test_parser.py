"""Tests for the Sapir Parking HTML parser (no Home Assistant needed)."""

import importlib.util
from pathlib import Path

import pytest

API_PATH = Path(__file__).parents[1] / "custom_components" / "sapir_parking" / "api.py"
_spec = importlib.util.spec_from_file_location("sapir_parking_api", API_PATH)
api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api)


def _floor(floor: int, spots: dict[int, int]) -> str:
    buttons = "".join(
        f'<div class="parking-button" data-parking-id="{pid}" '
        f'data-date="2025-12-25"> {spot} </div>'
        for spot, pid in spots.items()
    )
    return (
        '<li class="accordion-item">'
        f'<div class="item-title"><span>{floor}</span></div>{buttons}</li>'
    )


AVAILABLE_PAGE = (
    '<html><body><div class="list"><ul>'
    + _floor(-4, {12: 101, 13: 102})
    + _floor(-3, {})
    + _floor(-2, {7: 201})
    + "</ul></div></body></html>"
)

RESERVED_PAGE = """
<html><body>
<div class="company-parking-booked">
  <div class="item-title"><div class="chip">-4</div><div class="chip">12</div></div>
  <button class="schedule-delete" data-schedule-id="555" data-date="2025-12-25"></button>
</div>
<div class="list"><ul></ul></div>
</body></html>
"""

LOGIN_PAGE = """
<html><body><form>
<input name="Phone"><input name="License"><button>Login</button>
</form></body></html>
"""


def test_available_spots_skip_empty_floors():
    parser = api.SapirParkingResponseParser(AVAILABLE_PAGE)
    assert not parser.reserved
    assert parser.get_reserved_spot() is None
    spots = parser.get_available_spots()
    assert set(spots) == {-4, -2}
    assert spots[-4][0] == api.AvailableParkingSpot(
        floor=-4, spot=12, date="2025-12-25", parking_id=101
    )


def test_reserved_spot():
    parser = api.SapirParkingResponseParser(RESERVED_PAGE)
    assert parser.reserved
    assert parser.get_reserved_spot() == api.ReservedParkingSpot(
        floor=-4, spot=12, date="2025-12-25", schedule_id=555
    )
    assert parser.get_available_spots() == {}


def test_status_as_dict_is_json_safe():
    parser = api.SapirParkingResponseParser(AVAILABLE_PAGE)
    status = api.ParkingSpotStatus(
        parser.reserved, parser.get_reserved_spot(), parser.get_available_spots()
    )
    data = status.as_dict()
    assert data["parking_info"] is None
    assert set(data["available_spots"]) == {"-4", "-2"}
    assert len(status.all_available_spots) == 3


def test_login_page_raises_auth_error():
    with pytest.raises(api.SapirParkingAuthError):
        api.SapirParkingResponseParser(LOGIN_PAGE)


def test_unexpected_page_raises_parse_error():
    parser = api.SapirParkingResponseParser("<html><body>oops</body></html>")
    with pytest.raises(api.SapirParkingParseError):
        parser.get_available_spots()


@pytest.mark.parametrize(
    ("status", "headers", "text", "expected"),
    [
        (403, {"cf-mitigated": "challenge"}, "", True),
        (503, {}, "<title>Just a moment...</title>", True),
        (403, {}, "Forbidden", False),
        (200, {"cf-mitigated": "challenge"}, "Just a moment...", False),
    ],
)
def test_cloudflare_challenge_detection(status, headers, text, expected):
    assert api.is_cloudflare_challenge(status, headers, text) is expected
