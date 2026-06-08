"""Constants for the UFC Fight Tracker integration."""

from homeassistant.const import Platform

DOMAIN = "ufc_fight_tracker"
PLATFORMS: list[Platform] = [Platform.SENSOR]

DEFAULT_NAME = "UFC Fight Tracker"

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard"
BIO_URL = "http://sports.core.api.espn.com/v2/sports/mma/athletes/{athlete_id}?lang=en&region=us"
STATS_URL = "http://sports.core.api.espn.com/v2/sports/mma/athletes/{athlete_id}/statistics"
HEADSHOT_URL = "https://a.espncdn.com/i/headshots/mma/players/full/{athlete_id}.png"
FULL_BODY_LEFT_URL = "https://a.espncdn.com/i/headshots/mma/players/stance/left/{athlete_id}.png"
FULL_BODY_RIGHT_URL = "https://a.espncdn.com/i/headshots/mma/players/stance/right/{athlete_id}.png"
LEAGUE_LOGO_URL = "https://a.espncdn.com/i/teamlogos/leagues/500/ufc.png"
