"""DataUpdateCoordinator for UFC Fight Tracker."""
from __future__ import annotations

import logging
from datetime import timedelta, date, datetime
import asyncio
import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN, 
    BASE_URL, 
    BIO_URL, 
    STATS_URL, 
    HEADSHOT_URL, 
    FULL_BODY_LEFT_URL, 
    FULL_BODY_RIGHT_URL, 
    LEAGUE_LOGO_URL
)

_LOGGER = logging.getLogger(__name__)


async def fetch_scoreboard(session: aiohttp.ClientSession, start: date, end: date) -> dict:
    date_range = f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"
    url = f"{BASE_URL}?dates={date_range}"
    async with session.get(url, timeout=10) as resp:
        resp.raise_for_status()
        return await resp.json()


def find_next_event(events: list, is_default_start: bool) -> dict | None:
    if not events:
        return None

    if not is_default_start:
        return events[0]

    def event_date(event):
        try:
            return date.fromisoformat(event.get("date", "")[:10])
        except ValueError:
            return date.max

    sorted_events = sorted(events, key=event_date)

    # 1. Check for live event
    for e in sorted_events:
        status_state = e.get("status", {}).get("type", {}).get("state", "pre")
        if status_state == "in":
            return e

    # 2. Check for recently finished event
    post_events = [e for e in sorted_events if e.get("status", {}).get("type", {}).get("state", "pre") == "post"]
    if post_events:
        return post_events[-1]

    # 3. Return first upcoming future event
    for e in sorted_events:
        status_state = e.get("status", {}).get("type", {}).get("state", "pre")
        if status_state == "pre":
            return e

    # Fallback
    return sorted_events[0]


async def fetch_athlete_stats(session: aiohttp.ClientSession, athlete_id: str) -> dict:
    stats = {}
    if not athlete_id: 
        return stats

    bio_url = BIO_URL.format(athlete_id=athlete_id)
    stats_url = STATS_URL.format(athlete_id=athlete_id)

    async def fetch_bio():
        try:
            async with session.get(bio_url, timeout=5) as resp:
                if resp.status == 200:
                    bio_data = await resp.json()
                    stats["height"] = bio_data.get("displayHeight")
                    stats["weight"] = bio_data.get("displayWeight")
                    stats["age"] = bio_data.get("age")
                    stats["reach"] = bio_data.get("reach")
                    stance = bio_data.get("stance")
                    if stance: 
                        stats["stance"] = stance.get("text")
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass

    async def fetch_stat():
        try:
            async with session.get(stats_url, timeout=5) as resp:
                if resp.status == 200:
                    stat_data = await resp.json()
                    categories = stat_data.get("splits", {}).get("categories", [])
                    for cat in categories:
                        for stat in cat.get("stats", []):
                            name = stat.get("name")
                            val = stat.get("displayValue")
                            if name == "strikeLPM": stats["sigStrikeLpm"] = val
                            elif name == "strikeAccuracy": stats["sigStrikeAcc"] = val
                            elif name == "takedownAvg": stats["takedownAvg"] = val
                            elif name == "takedownAccuracy": stats["takedownAcc"] = val
                            elif name == "submissionAvg": stats["submissionAvg"] = val
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass

    await asyncio.gather(fetch_bio(), fetch_stat())
    return stats


async def enrich_event(session: aiohttp.ClientSession, event: dict, stats_mode: str) -> dict:
    competitions = event.get("competitions", [])
    if not competitions:
        return event

    unique_starts = sorted(list(set(c.get("startDate", "") for c in competitions if c.get("startDate"))), reverse=True)
    start_date_labels = {}
    if len(unique_starts) >= 1:
        start_date_labels[unique_starts[0]] = "Main Card"
    if len(unique_starts) >= 2:
        start_date_labels[unique_starts[1]] = "Prelims"
    if len(unique_starts) >= 3:
        start_date_labels[unique_starts[2]] = "Early Prelims"
    for j in range(3, len(unique_starts)):
        start_date_labels[unique_starts[j]] = f"Early Prelims {j-1}"

    competitors_list = []
    for comp in competitions:
        start = comp.get("startDate", "")
        if start in start_date_labels:
            comp["cardSegment"] = start_date_labels[start]
            
        for competitor in comp.get("competitors", []):
            competitors_list.append(competitor)

    async def process_competitor(competitor):
        athlete = competitor.get("athlete", {})
        athlete_id = competitor.get("id")
        if athlete_id:
            athlete["headshot"] = HEADSHOT_URL.format(athlete_id=athlete_id)
            athlete["fullBodyLeft"] = FULL_BODY_LEFT_URL.format(athlete_id=athlete_id)
            athlete["fullBodyRight"] = FULL_BODY_RIGHT_URL.format(athlete_id=athlete_id)
            if stats_mode == "Full Stats":
                stats = await fetch_athlete_stats(session, athlete_id)
                athlete.update(stats)

    await asyncio.gather(*(process_competitor(c) for c in competitors_list))

    return event


def generate_ha_json(event: dict) -> list:
    competitions = event.get("competitions", [])
    if not competitions:
        return []

    event_state = event.get("status", {}).get("type", {}).get("state", "pre").upper()
    if event_state not in ["PRE", "IN", "POST"]:
        event_state = "PRE"

    ordered = list(reversed(competitions))
    venue = event.get("venues", [{}])[0] if event.get("venues") else {}
    location = ", ".join(filter(None, [venue.get("address", {}).get("city"), venue.get("address", {}).get("country")]))
    
    sensors = []
    segment_counters = {}

    for i in range(15):
        has_fight = i < len(ordered) and len(ordered[i].get("competitors", [])) >= 2
        fight = ordered[i] if has_fight else {}
        
        f1, f2 = sorted(fight.get("competitors", []), key=lambda c: c.get("order", 99))[:2] if has_fight else ({}, {})
        
        record1 = next((r["summary"] for r in f1.get("records", []) if r.get("name") == "overall"), "?") if has_fight else None
        record2 = next((r["summary"] for r in f2.get("records", []) if r.get("name") == "overall"), "?") if has_fight else None
        
        f1_winner = f1.get("winner", False)
        f2_winner = f2.get("winner", False)
        
        segment = fight.get("cardSegment", "Unknown") if has_fight else None
        event_type = None
        if has_fight:
            segment_counters[segment] = segment_counters.get(segment, 0) + 1
            counter = segment_counters[segment]
            if segment == "Main Card":
                if counter == 1: event_type = "Main Event"
                elif counter == 2: event_type = "Co-Main Event"
                else: event_type = f"Event {counter}"
            else:
                event_type = f"Event {counter}"

        weight_class = fight.get("type", {}).get("abbreviation")
        round_info = fight.get("format", {}).get("regulation", {}).get("periods")

        last_play_str = None
        win_type_str = None
        score_card_str = None
        if has_fight and event_state == "POST":
            name1 = f1.get("athlete", {}).get("displayName", "Fighter 1").split(" ")[-1]
            name2 = f2.get("athlete", {}).get("displayName", "Fighter 2").split(" ")[-1]
            winner_name = name1 if f1_winner else (name2 if f2_winner else "Draw")

            details_text = ""
            for detail in fight.get("details", []):
                text = detail.get("type", {}).get("text", "")
                if "Unofficial Winner" in text:
                    if "Kotko" in text: details_text = "KO/TKO"
                    elif "Submission" in text: details_text = "Submission"
                    elif "Decision" in text: details_text = "Decision"
                    break

            ls1 = f1.get("linescores", [{}])[0].get("linescores", [])
            ls2 = f2.get("linescores", [{}])[0].get("linescores", [])
            
            if ls1 and ls2 and len(ls1) == len(ls2):
                f1_score, f2_score, draw_score = 0, 0, 0
                scores_string = []
                for k in range(len(ls1)):
                    v1 = ls1[k].get("value", 0)
                    v2 = ls2[k].get("value", 0)
                    if v1 > v2: f1_score += 1
                    elif v1 < v2: f2_score += 1
                    else: draw_score += 1
                    
                    max_score = int(max(v1, v2))
                    min_score = int(min(v1, v2))
                    scores_string.append(f"{max_score}-{min_score}")
                    
                decision_type = "Decision"
                if f1_score == 3 or f2_score == 3: decision_type = "Unanimous Decision"
                elif (f1_score == 2 and f2_score == 1) or (f2_score == 2 and f1_score == 1): decision_type = "Split Decision"
                elif (f1_score == 2 and draw_score == 1) or (f2_score == 2 and draw_score == 1): decision_type = "Majority Decision"
                elif draw_score == 3: decision_type = "Unanimous Draw"
                elif draw_score == 2 and (f1_score == 1 or f2_score == 1): decision_type = "Majority Draw"
                elif draw_score == 1 and f1_score == 1 and f2_score == 1: decision_type = "Split Draw"
                else: decision_type = "Draw"
                
                win_type_str = decision_type
                score_card_str = f"{', '.join(scores_string)}"
                result_details = f"({score_card_str})"
                last_play_str = f"{win_type_str} {result_details}"
            else:
                finish_type = details_text if details_text else "KO/TKO/Sub"
                win_type_str = finish_type
                last_play_str = win_type_str

        sensor_dict = {
            "attribution": "Data provided by ESPN",
            "state": event_state if has_fight else "Unknown",
            "sport": "mma",
            "sport_path": "mma",
            "league": "UFC",
            "league_path": "ufc",
            "league_logo": LEAGUE_LOGO_URL,
            "league_name": "Ultimate Fighting Championship",
            "season": "regular-season",
            "team_abbr": "*" if has_fight else None,
            "opponent_abbr": None,
            "event_name": event.get("name") if has_fight else None,
            "event_id": event.get("id") if has_fight else None,
            "event_type": event_type,
            "weight_class": weight_class,
            "round_info": round_info,
            "event_url": (event.get("links", [{}])[0].get("href", "") if event.get("links") else None) if has_fight else None,
            "event_stream": None,
            "date": fight.get("startDate"),
            "kickoff_in": "in a day" if has_fight else None,
            "series_summary": None,
            "venue": venue.get("fullName") if has_fight else None,
            "location": location if has_fight else None,
            "tv_network": (fight.get("broadcasts", [{}])[0].get("names", [""])[0] if fight.get("broadcasts") else None) if has_fight else None,
            "odds": None,
            "overunder": None,
            
            "team_name": f1.get("athlete", {}).get("displayName"),
            "team_long_name": f1.get("athlete", {}).get("fullName"),
            "team_id": f1.get("id"),
            "team_record": record1,
            "team_rank": None,
            "team_conference_id": None,
            "team_homeaway": None,
            "team_logo": f1.get("athlete", {}).get("flag", {}).get("href"),
            "team_country": f1.get("athlete", {}).get("flag", {}).get("alt"),
            "team_url": None,
            "team_stream": None,
            "team_colors": None,
            "team_score": f1.get("score"),
            "team_win_probability": None,
            "team_winner": bool(f1_winner) if has_fight else None,
            "team_timeouts": None,
            
            "team_headshot": f1.get("athlete", {}).get("headshot"),
            "team_fullBodyLeft": f1.get("athlete", {}).get("fullBodyLeft"),
            "team_fullBodyRight": f1.get("athlete", {}).get("fullBodyRight"),
            "team_height": f1.get("athlete", {}).get("height"),
            "team_weight": f1.get("athlete", {}).get("weight"),
            "team_age": f1.get("athlete", {}).get("age"),
            "team_reach": f1.get("athlete", {}).get("reach"),
            "team_stance": f1.get("athlete", {}).get("stance"),
            "team_sigStrikeLpm": f1.get("athlete", {}).get("sigStrikeLpm"),
            "team_sigStrikeAcc": f1.get("athlete", {}).get("sigStrikeAcc"),
            "team_takedownAvg": f1.get("athlete", {}).get("takedownAvg"),
            "team_takedownAcc": f1.get("athlete", {}).get("takedownAcc"),
            "team_submissionAvg": f1.get("athlete", {}).get("submissionAvg"),
            
            "opponent_name": f2.get("athlete", {}).get("displayName"),
            "opponent_long_name": f2.get("athlete", {}).get("fullName"),
            "opponent_id": f2.get("id"),
            "opponent_record": record2,
            "opponent_rank": None,
            "opponent_conference_id": None,
            "opponent_homeaway": None,
            "opponent_logo": f2.get("athlete", {}).get("flag", {}).get("href"),
            "opponent_country": f2.get("athlete", {}).get("flag", {}).get("alt"),
            "opponent_url": None,
            "opponent_stream": None,
            "opponent_colors": None,
            "opponent_score": f2.get("score"),
            "opponent_win_probability": None,
            "opponent_winner": bool(f2_winner) if has_fight else None,
            "opponent_timeouts": None,

            "opponent_headshot": f2.get("athlete", {}).get("headshot"),
            "opponent_fullBodyLeft": f2.get("athlete", {}).get("fullBodyLeft"),
            "opponent_fullBodyRight": f2.get("athlete", {}).get("fullBodyRight"),
            "opponent_height": f2.get("athlete", {}).get("height"),
            "opponent_weight": f2.get("athlete", {}).get("weight"),
            "opponent_age": f2.get("athlete", {}).get("age"),
            "opponent_reach": f2.get("athlete", {}).get("reach"),
            "opponent_stance": f2.get("athlete", {}).get("stance"),
            "opponent_sigStrikeLpm": f2.get("athlete", {}).get("sigStrikeLpm"),
            "opponent_sigStrikeAcc": f2.get("athlete", {}).get("sigStrikeAcc"),
            "opponent_takedownAvg": f2.get("athlete", {}).get("takedownAvg"),
            "opponent_takedownAcc": f2.get("athlete", {}).get("takedownAcc"),
            "opponent_submissionAvg": f2.get("athlete", {}).get("submissionAvg"),
            
            "cardSegment": fight.get("cardSegment"),
            "quarter": fight.get("status", {}).get("period") if has_fight else None,
            "clock": fight.get("status", {}).get("displayClock") if has_fight else None,
            "period": fight.get("status", {}).get("period") if has_fight else None,
            "displayClock": fight.get("status", {}).get("displayClock") if has_fight else None,
            "possession": None,
            "last_play": last_play_str,
            "win_type": win_type_str,
            "score_card": score_card_str,
            "down_distance_text": None,
            "outs": None,
            "balls": None,
            "strikes": None,
            "on_first": None,
            "on_second": None,
            "on_third": None,
            "team_shots_on_target": None,
            "team_total_shots": None,
            "opponent_shots_on_target": None,
            "opponent_total_shots": None,
            "team_sets_won": None,
            "opponent_sets_won": None,
            "last_update": dt_util.now().strftime("%Y-%m-%d %H:%M:%S%z"),
            "api_message": None,
            "api_url": BASE_URL,
            "private_fast_refresh": False,
            "icon": "mdi:karate",
            "friendly_name": f"UFC Fight Tracker {i:02d}"
        }
        sensors.append(sensor_dict)

    return sensors


async def fetch_all_data(session: aiohttp.ClientSession, keep_days: int, stats_mode: str):
    today = date.today()
    start = today - timedelta(days=keep_days)
    end = today + timedelta(days=30)
    data = await fetch_scoreboard(session, start, end)
    event = find_next_event(data.get("events", []), True)
    
    if not event:
        return None, None
        
    enriched_event = await enrich_event(session, event, stats_mode)
    sensors_json = generate_ha_json(enriched_event)
    return sensors_json, enriched_event


class UFCDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching UFC data."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry):
        """Initialize."""
        self.config_entry = config_entry
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(days=1),
        )

    async def _async_update_data(self):
        """Fetch data from API."""
        try:
            session = async_get_clientsession(self.hass)
            
            options = self.config_entry.options or self.config_entry.data
            keep_days = options.get("keep_days", 3)
            stats_mode = options.get("stats_mode", "Lite")

            sensors_json, event = await fetch_all_data(session, keep_days, stats_mode)
            if sensors_json is None:
                self.update_interval = timedelta(days=1)
                return []
            
            self._update_interval_based_on_event(event)
            return sensors_json
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"Error communicating with API: {err}")
        except Exception as err:
            raise UpdateFailed(f"Unexpected error: {err}")

    def _update_interval_based_on_event(self, event):
        """Dynamically set the update interval based on event timing."""
        try:
            event_state = event.get("status", {}).get("type", {}).get("state", "pre").upper()
            if event_state == "POST":
                self.update_interval = timedelta(days=1)
                return

            competitions = event.get("competitions", [])
            if not competitions:
                self.update_interval = timedelta(days=1)
                return

            starts = []
            for comp in competitions:
                st = comp.get("startDate")
                if st:
                    try:
                        dt = dt_util.parse_datetime(st)
                        if dt:
                            starts.append(dt)
                    except Exception:
                        pass
            
            if not starts:
                self.update_interval = timedelta(days=1)
                return

            first_fight_time = min(starts)
            
            main_card_time = first_fight_time
            main_card_starts = []
            for comp in competitions:
                if comp.get("cardSegment") == "Main Card":
                    st = comp.get("startDate")
                    if st:
                        dt = dt_util.parse_datetime(st)
                        if dt:
                            main_card_starts.append(dt)
            if main_card_starts:
                main_card_time = min(main_card_starts)

            now = dt_util.utcnow()

            if now < first_fight_time - timedelta(hours=6):
                self.update_interval = timedelta(days=1)
            elif first_fight_time - timedelta(hours=6) <= now < first_fight_time:
                self.update_interval = timedelta(hours=1)
            elif now >= first_fight_time and now < main_card_time:
                prelims_active = False
                for comp in competitions:
                    if comp.get("cardSegment") != "Main Card":
                        state = comp.get("status", {}).get("type", {}).get("state", "pre").upper()
                        if state in ("PRE", "IN"):
                            prelims_active = True
                            break
                
                if prelims_active:
                    self.update_interval = timedelta(seconds=30)
                else:
                    wait_time = main_card_time - now
                    wait_seconds = wait_time.total_seconds()
                    if wait_seconds > 60:
                        self.update_interval = timedelta(seconds=wait_seconds)
                    else:
                        self.update_interval = timedelta(seconds=30)
            else:
                self.update_interval = timedelta(seconds=30)

            _LOGGER.debug(f"UFC Fight Tracker interval set to {self.update_interval}")

        except Exception as e:
            _LOGGER.error(f"Error calculating update interval: {e}")
            self.update_interval = timedelta(minutes=15)
