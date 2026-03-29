"""Look up player ranked data from Slippi's GraphQL API."""

from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

SLIPPI_GQL_URL = "https://internal.slippi.gg"

PROFILE_QUERY = """
query UserProfilePageQuery($cc: String, $uid: String) {
  getUser(connectCode: $cc, fbUid: $uid) {
    displayName
    connectCode { code }
    rankedNetplayProfile {
      ratingOrdinal
      ratingUpdateCount
      wins
      losses
      dailyGlobalPlacement
      dailyRegionalPlacement
      continent
      characters { character gameCount }
    }
  }
}
"""

# Slippi rank tiers by rating threshold (descending)
# Grandmaster is Master 1+ with top-300 daily global placement (checked separately)
RANK_TIERS = [
    (2350.00, "Master 3"),
    (2275.00, "Master 2"),
    (2191.75, "Master 1"),
    (2136.28, "Diamond 3"),
    (2073.67, "Diamond 2"),
    (2003.92, "Diamond 1"),
    (1927.03, "Platinum 3"),
    (1843.00, "Platinum 2"),
    (1751.83, "Platinum 1"),
    (1653.52, "Gold 3"),
    (1548.07, "Gold 2"),
    (1435.48, "Gold 1"),
    (1315.75, "Silver 3"),
    (1188.88, "Silver 2"),
    (1054.87, "Silver 1"),
    (913.72, "Bronze 3"),
    (765.43, "Bronze 2"),
    (0, "Bronze 1"),
]


def rating_to_tier(rating: float | None, global_placement: int | None = None) -> str:
    if rating is None:
        return "Unrated"
    # Grandmaster = Master 1+ rating with top-300 daily global placement
    if rating >= 2191.75 and global_placement is not None and global_placement <= 300:
        return "Grandmaster"
    for threshold, tier in RANK_TIERS:
        if rating >= threshold:
            return tier
    return "Bronze 1"


def _normalize_code_for_api(code: str) -> str:
    """Convert connect code to API format: standard #, uppercase."""
    code = code.replace("\uFF03", "#")  # full-width → standard
    code = code.replace("-", "#", 1)
    return code.upper()


def lookup_player(connect_code: str) -> dict | None:
    """Look up a player's ranked data by connect code.

    Returns a dict with rating, tier, wins, losses, etc.
    Returns None if the player doesn't exist or has no ranked profile.
    """
    code = _normalize_code_for_api(connect_code)

    try:
        resp = requests.post(
            SLIPPI_GQL_URL,
            json={
                "operationName": "UserProfilePageQuery",
                "query": PROFILE_QUERY,
                "variables": {"cc": code, "uid": code},
            },
            headers={"content-type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"Warning: Slippi API request failed for {code}: {e}")
        return None

    data = resp.json()
    user = data.get("data", {}).get("getUser")
    if not user:
        return None

    profile = user.get("rankedNetplayProfile")
    if not profile:
        return {"display_name": user.get("displayName"), "rating": None, "tier": None}

    rating = profile.get("ratingOrdinal")
    update_count = profile.get("ratingUpdateCount") or 0

    # Slippi returns ~1100 as a default rating even for unplaced players
    if update_count == 0:
        rating = None

    return {
        "display_name": user.get("displayName"),
        "rating": rating,
        "tier": rating_to_tier(rating, profile.get("dailyGlobalPlacement")),
        "ranked_wins": profile.get("wins"),
        "ranked_losses": profile.get("losses"),
        "global_placement": profile.get("dailyGlobalPlacement"),
        "regional_placement": profile.get("dailyRegionalPlacement"),
    }


class RankCache:
    """Cache ranked lookups by connect code for a single run."""

    def __init__(self):
        self._cache: dict[str, dict | None] = {}

    def get(self, connect_code: str) -> dict | None:
        key = _normalize_code_for_api(connect_code)
        if key not in self._cache:
            self._cache[key] = lookup_player(connect_code)
        return self._cache[key]

    def prefetch(self, connect_codes: set[str]) -> None:
        """Look up multiple players concurrently."""
        codes_to_fetch = {
            c for c in connect_codes
            if _normalize_code_for_api(c) not in self._cache
        }
        if not codes_to_fetch:
            return
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(lookup_player, c): c for c in codes_to_fetch}
            for future in as_completed(futures):
                code = futures[future]
                key = _normalize_code_for_api(code)
                self._cache[key] = future.result()

    @property
    def api_calls_made(self) -> int:
        return len(self._cache)
