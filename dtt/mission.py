"""Test missions and test sites."""
import math

# Test sites: (lat, lon, ground altitude m AMSL, heading deg). Week 1 uses the Delhi baseline only.
SITES = {
    "delhi": (28.6139, 77.2090, 216.0, 0.0),
}

PATROL_ALT_M = 50.0      # above take-off point
PATROL_HALF_SIDE_M = 187.5  # square of 375 m sides -> 1.5 km loop
FENCE_RADIUS_M = 600.0
FENCE_ALT_MAX_M = 120.0


def offset(lat, lon, north_m, east_m):
    """Moves a lat/lon by metres north/east (flat-earth, fine for a few km)."""
    dlat = north_m / 6378137.0
    dlon = east_m / (6378137.0 * math.cos(math.radians(lat)))
    return lat + math.degrees(dlat), lon + math.degrees(dlon)


def patrol_square(home):
    """Mission items for: take off, fly the square loop, return to launch.

    Returns a list of dicts. Index in the list == mission sequence number.
    seq 0 is the home placeholder ArduPilot expects.
    """
    lat, lon, alt, _ = home
    h = PATROL_HALF_SIDE_M
    corners = [(h, h), (h, -h), (-h, -h), (-h, h), (h, h)]  # closes the loop
    items = [dict(cmd="WAYPOINT", lat=lat, lon=lon, alt=0.0, frame="GLOBAL")]
    items.append(dict(cmd="TAKEOFF", lat=0.0, lon=0.0, alt=PATROL_ALT_M, frame="RELATIVE"))
    for n, e in corners:
        clat, clon = offset(lat, lon, n, e)
        items.append(dict(cmd="WAYPOINT", lat=clat, lon=clon, alt=PATROL_ALT_M, frame="RELATIVE"))
    items.append(dict(cmd="RTL", lat=0.0, lon=0.0, alt=0.0, frame="RELATIVE"))
    return items


# The fault is switched on when the drone starts flying toward this mission item:
# seq 4 = leaving the second corner, about 265 m from home.
FAULT_AT_SEQ = 4

# Geofence and other parameters applied before every flight.
BASE_PARAMS = {
    "FENCE_ENABLE": 1,
    "FENCE_TYPE": 3,          # max altitude + circle around home
    "FENCE_RADIUS": FENCE_RADIUS_M,
    "FENCE_ALT_MAX": FENCE_ALT_MAX_M,
    "FENCE_ACTION": 1,        # RTL, or land if RTL is not possible
    "LOG_DISARMED": 0,
}
