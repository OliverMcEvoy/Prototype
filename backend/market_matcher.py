"""
Cross-platform event matching for arbitrage detection.

Matches Betfair events against Polymarket markets using:
  - Team name alias dictionary
  - Token-level partial matching
  - Sport-scoped pre-filtering
  - Date proximity window (±36h)
"""

import unicodedata
from typing import List, Optional, Tuple, Dict
from difflib import SequenceMatcher
import re
from datetime import datetime, timedelta, timezone

from backend.models import Event, PolymarketEvent, Outcome
from backend.config import Config

# ---------------------------------------------------------------------------
# Region / country vocabulary for politics cross-platform conflict detection.
# Each key is the canonical region name; the set is all tokens that identify it.
# A BF market and PM market mentioning DIFFERENT regions are rejected.
# ---------------------------------------------------------------------------
_REGION_MAP: Dict[str, set] = {
    "us": {"us", "usa", "united states", "american", "america", "u.s."},
    "uk": {
        "uk",
        "united kingdom",
        "britain",
        "british",
        "england",
        "english",
        "scotland",
        "scottish",
        "wales",
        "welsh",
        "u.k.",
    },
    "hungary": {"hungary", "hungarian"},
    "france": {"france", "french"},
    "germany": {"germany", "german", "deutschland"},
    "australia": {"australia", "australian"},
    "canada": {"canada", "canadian"},
    "italy": {"italy", "italian"},
    "spain": {"spain", "spanish"},
    "ireland": {"ireland", "irish"},
    "poland": {"poland", "polish"},
    "brazil": {"brazil", "brazilian"},
    "india": {"india", "indian"},
    "turkey": {"turkey", "turkish"},
    "israel": {"israel", "israeli"},
    "ukraine": {"ukraine", "ukrainian"},
    "russia": {"russia", "russian"},
    "china": {"china", "chinese"},
    "japan": {"japan", "japanese"},
    "south korea": {"south korea", "korean"},
    "mexico": {"mexico", "mexican"},
    "argentina": {"argentina", "argentinian", "argentinean"},
    "sweden": {"sweden", "swedish"},
    "norway": {"norway", "norwegian"},
    "denmark": {"denmark", "danish"},
    "finland": {"finland", "finnish"},
    "netherlands": {"netherlands", "dutch", "holland"},
    "belgium": {"belgium", "belgian"},
    "switzerland": {"switzerland", "swiss"},
    "austria": {"austria", "austrian"},
    "portugal": {"portugal", "portuguese"},
    "greece": {"greece", "greek"},
    "romania": {"romania", "romanian"},
    "new zealand": {"new zealand"},
    "south africa": {"south africa"},
    "pakistan": {"pakistan", "pakistani"},
    "indonesia": {"indonesia", "indonesian"},
    "philippines": {"philippines", "philippine"},
    "taiwan": {"taiwan", "taiwanese"},
    "slovakia": {"slovakia", "slovak"},
    "czechia": {"czechia", "czech republic", "czech"},
}


def _extract_regions(text: str) -> set:
    """Return set of canonical region keys mentioned in *text*."""
    t = text.lower()
    found = set()
    for region, aliases in _REGION_MAP.items():
        if any(a in t for a in aliases):
            found.add(region)
    return found


# Team name alias table. Maps variant → canonical for fuzzy matching.
# Add entries here when match_debug.txt shows missed matches.
TEAM_ALIASES: Dict[str, List[str]] = {
    # English football
    "manchester united": ["man utd", "man united", "manchester utd", "mufc"],
    "manchester city": ["man city", "man c", "mcfc"],
    "tottenham hotspur": ["spurs", "tottenham", "thfc"],
    "wolverhampton": ["wolves", "wolverhampton wanderers"],
    "nottingham forest": [
        "nott'm forest",
        "notts forest",
        "nffc",
        "nottm forest",
        "nottm forest fc",
        "nottingham forest fc",
    ],
    "west bromwich": ["west brom", "wba"],
    "queens park rangers": ["qpr"],
    "sheffield united": ["sheff utd", "sheffield utd"],
    "sheffield wednesday": ["sheff wed", "sheffield wed"],
    "bournemouth": ["afc bournemouth", "afcb"],
    "brighton": ["brighton & hove albion", "brighton hove"],
    "newcastle": ["newcastle united", "nufc"],
    "west ham": ["west ham united", "whu"],
    "leicester": ["leicester city", "lcfc"],
    "ipswich": ["ipswich town", "ipswich town fc"],
    "luton": ["luton town", "luton town fc"],
    "hull": ["hull city", "hull city fc", "hull city afc"],
    "wolverhampton wanderers": [
        "wolves",
        "wolverhampton",
        "wolverhampton wanderers fc",
    ],
    "newcastle united": ["newcastle", "nufc", "newcastle united fc"],
    "brighton": [
        "brighton & hove albion",
        "brighton hove",
        "brighton & hove albion fc",
    ],
    # Spanish football
    "real madrid": ["real madrid cf", "real madrid fc"],
    "atletico madrid": [
        "atletico de madrid",
        "atl madrid",
        "atletico madrid cf",
        "club atletico de madrid",
    ],
    "barcelona": ["fc barcelona", "barca"],
    "real betis": ["real betis balompie", "betis"],
    "celta vigo": ["celta", "rc celta de vigo"],
    "valencia": ["valencia cf"],
    "villarreal": ["villarreal cf"],
    "sevilla": ["sevilla fc"],
    "real betis": ["real betis balompie"],
    "athletic bilbao": ["athletic club"],
    "deportivo alaves": ["alaves"],
    "real sociedad": ["r sociedad"],
    # Italian football
    "napoli": ["ssc napoli", "napoli calcio"],
    "ac milan": ["milan", "ac milan fc"],
    "inter milan": [
        "inter",
        "internazionale",
        "fc internazionale",
        "fc internazionale milano",
    ],
    "juventus": ["juve", "juventus fc"],
    "as roma": ["roma", "as roma fc"],
    "ss lazio": ["lazio", "ss lazio fc"],
    "atalanta": ["atalanta bc"],
    "fiorentina": ["acf fiorentina"],
    # German football
    "borussia dortmund": ["bvb", "dortmund", "bv borussia 09 dortmund"],
    "borussia mgladbach": [
        "b. monchengladbach",
        "mgladbach",
        "gladbach",
        "borussia monchengladbach",
        "borussia monchengladbach fc",
    ],
    "rb leipzig": ["rbl", "rasenball", "rb leipzig fc"],
    "bayer leverkusen": ["leverkusen", "bayer 04 leverkusen", "b04"],
    "eintracht frankfurt": ["frankfurt", "eintracht frankfurt fc"],
    "werder bremen": ["werder", "sv werder bremen"],
    "vfl wolfsburg": ["wolfsburg"],
    "vfb stuttgart": ["stuttgart"],
    "sc freiburg": ["freiburg"],
    "fc koln": ["koln", "1. fc koln", "fc koln fc"],
    "mainz": ["1. fsv mainz 05", "1. fsv mainz", "mainz 05"],
    "union berlin": ["1. fc union berlin", "fc union berlin"],
    "st. pauli": ["fc st. pauli", "fc st pauli", "st pauli"],
    "hoffenheim": ["tsg hoffenheim", "tsg 1899 hoffenheim"],
    "heidenheim": ["1. fc heidenheim", "1. fc heidenheim 1846"],
    # French football
    "paris saint-germain": [
        "psg",
        "paris sg",
        "paris saint germain",
        "paris saint-germain fc",
    ],
    "olympique lyonnais": ["lyon", "ol", "olympique lyonnais fc"],
    "olympique marseille": ["marseille", "om", "olympique de marseille"],
    "stade rennais": ["rennes", "stade rennais fc"],
    "monaco": ["as monaco", "as monaco fc"],
    "lille": ["losc", "losc lille", "lille osc"],
    "nice": ["ogc nice"],
    "lens": ["rc lens"],
    "strasbourg": ["rc strasbourg", "rc strasbourg alsace"],
    "nantes": ["fc nantes"],
    "reims": ["stade de reims"],
    "brest": ["stade brestois", "stade brestois 29"],
    "toulouse": ["toulouse fc"],
    "clermont": ["clermont foot", "asm clermont auvergne"],
    # Portuguese football
    "sl benfica": ["benfica", "sport lisboa e benfica", "slb"],
    "fc porto": ["porto"],
    "sporting cp": ["sporting lisbon", "sporting", "sporting cp fc"],
    "sc braga": ["braga", "sporting braga"],
    # Dutch football
    "ajax": ["afc ajax", "ajax amsterdam"],
    "psv": ["psv eindhoven"],
    "feyenoord": ["feyenoord rotterdam"],
    # US sports
    "los angeles lakers": ["lakers", "la lakers"],
    "golden state warriors": ["warriors", "gsw"],
    "boston celtics": ["celtics"],
    "new york knicks": ["knicks"],
    "chicago bulls": ["bulls"],
    "dallas mavericks": ["mavs", "mavericks"],
    "miami heat": ["heat"],
    "phoenix suns": ["suns"],
    # Tennis (players sometimes listed differently)
    "novak djokovic": ["djokovic"],
    "carlos alcaraz": ["alcaraz"],
    "jannik sinner": ["sinner"],
    # Cricket
    "india": ["team india", "ind"],
    "england": ["eng", "england cricket"],
    "australia": ["aus", "australia cricket"],
    "west indies": ["windies", "wi"],
    "south africa": ["sa", "proteas"],
    "new zealand": ["nz", "black caps"],
    "pakistan": ["pak"],
    "sri lanka": ["sl", "lanka"],
    "bangladesh": ["ban"],
    # Draw / tie
    "draw": ["the draw", "tie", "drawn", "x"],
    # ── Political parties & entities ──────────────────────────────────────────
    # US parties
    "republican party": ["republican", "republicans", "gop", "rep", "reds"],
    "democratic party": ["democrat", "democrats", "democratic", "dem", "dems", "blue"],
    "green party": ["greens", "green"],
    "libertarian party": ["libertarian", "libertarians"],
    # UK parties
    "labour party": ["labour", "labor"],
    "conservative party": ["conservative", "conservatives", "tory", "tories", "con"],
    "liberal democrats": ["lib dems", "libdems", "lib dem", "ld"],
    "reform uk": ["reform"],
    "snp": ["scottish national party", "scotland"],
    # Outcomes / generic political result names
    "no majority": ["no overall majority", "hung parliament", "split", "no winner"],
    "other": ["field", "others", "all others", "third party"],
    # Basketball — NBA (Polymarket uses nickname only; Betfair uses full city+name)
    "atlanta hawks": ["hawks"],
    "brooklyn nets": ["nets"],
    "charlotte hornets": ["hornets"],
    "cleveland cavaliers": ["cavaliers", "cavs"],
    "denver nuggets": ["nuggets"],
    "detroit pistons": ["pistons"],
    "houston rockets": ["rockets"],
    "indiana pacers": ["pacers"],
    "los angeles clippers": ["clippers", "la clippers"],
    "memphis grizzlies": ["grizzlies"],
    "milwaukee bucks": ["bucks"],
    "minnesota timberwolves": ["timberwolves"],
    "new orleans pelicans": ["pelicans"],
    "oklahoma city thunder": ["thunder", "okc"],
    "orlando magic": ["magic"],
    "philadelphia 76ers": ["76ers", "sixers"],
    "portland trail blazers": ["trail blazers", "blazers"],
    "toronto raptors": ["raptors"],
    "utah jazz": ["jazz"],
    "washington wizards": ["wizards"],
    "sacramento kings": ["kings", "sac kings"],
    "san antonio spurs": ["spurs"],
    # Ice Hockey — NHL (same pattern)
    "anaheim ducks": ["ducks"],
    "boston bruins": ["bruins"],
    "buffalo sabres": ["sabres"],
    "calgary flames": ["flames"],
    "carolina hurricanes": ["hurricanes"],
    "chicago blackhawks": ["blackhawks"],
    "colorado avalanche": ["avalanche"],
    "columbus blue jackets": ["blue jackets"],
    "dallas stars": ["stars"],
    "detroit red wings": ["red wings", "wings"],
    "edmonton oilers": ["oilers"],
    "florida panthers": ["panthers"],
    "los angeles kings": ["kings", "la kings"],
    "minnesota wild": ["wild"],
    "montreal canadiens": ["canadiens"],
    "nashville predators": ["predators"],
    "new jersey devils": ["devils"],
    "new york islanders": ["islanders"],
    "new york rangers": ["rangers"],
    "ottawa senators": ["senators"],
    "philadelphia flyers": ["flyers"],
    "pittsburgh penguins": ["penguins"],
    "san jose sharks": ["sharks"],
    "seattle kraken": ["kraken"],
    "st. louis blues": ["blues"],
    "tampa bay lightning": ["lightning"],
    "toronto maple leafs": ["maple leafs"],
    "utah hockey club": ["utah hc"],
    "vancouver canucks": ["canucks"],
    "vegas golden knights": ["golden knights"],
    "washington capitals": ["capitals"],
    "winnipeg jets": ["jets"],
}

# Build reverse lookup: variant → canonical
_ALIAS_LOOKUP: Dict[str, str] = {}
for canonical, variants in TEAM_ALIASES.items():
    _ALIAS_LOOKUP[canonical] = canonical
    for v in variants:
        _ALIAS_LOOKUP[v] = canonical


# Club-type suffixes that Polymarket appends but Betfair omits (or vice versa).
# Stripped before alias lookup so "Arsenal FC" and "Arsenal" both resolve to "arsenal".
_CLUB_SUFFIXES = (
    " fc",
    " afc",
    " cf",
    " sc",
    " fk",
    " bsc",
    " ac",
    " sk",
    " hk",
    " as",
    " sd",
)


# Generic tokens shared across many team names — not reliable alone for matching.
# When checking whether a BF team name appears in Polymarket text, we require ALL
# distinctive (non-generic) tokens to be present, not just any single one.
_GENERIC_NAME_TOKENS: frozenset = frozenset(
    {
        "real",
        "city",
        "united",
        "new",
        "south",
        "north",
        "east",
        "west",
        "club",
        "the",
        "san",
        "los",
        "las",
        "de",
        "da",
        "st",
        "saint",
        "fc",
        "afc",
        "sc",
        "cf",
        "sk",
        "ac",
        "as",
    }
)


def _canonicalise(name: str) -> str:
    """Return the canonical form of a team/player name, or the original if unknown."""
    n = unicodedata.normalize("NFD", name).encode("ascii", "ignore").decode("ascii")
    n = n.lower().strip()
    for suffix in _CLUB_SUFFIXES:
        if n.endswith(suffix):
            n = n[: -len(suffix)].strip()
            break
    return _ALIAS_LOOKUP.get(n, n)


class MarketMatcher:
    """Matches events across different platforms for arbitrage opportunities."""

    DEFAULT_THRESHOLD = 0.35

    def __init__(self, similarity_threshold: float = None):
        self.similarity_threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else getattr(Config, "FUZZY_MATCH_THRESHOLD", self.DEFAULT_THRESHOLD)
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_matches(
        self, traditional_events: List[Event], polymarket_events: List[PolymarketEvent]
    ) -> List[Tuple[Event, PolymarketEvent, float]]:
        """
        Find matching events between Betfair and Polymarket.

        Uses a global 1:1 greedy assignment so each Polymarket event can be
        claimed by at most one Betfair event (eliminates false duplicates):
          1. Score every (BF, PM) pair that exceeds the threshold.
          2. Sort all scored pairs descending.
          3. Greedily assign highest-scoring pairs, skipping any BF or PM
             event that has already been matched.

        Returns list of (betfair_event, polymarket_event, score) tuples.
        """
        print(
            f"\n[MATCHING] {len(traditional_events)} Betfair vs "
            f"{len(polymarket_events)} Polymarket  (threshold={self.similarity_threshold})"
        )

        # Pre-group Polymarket events by sport category for fast lookup
        poly_by_sport: Dict[str, List[PolymarketEvent]] = {}
        for pe in polymarket_events:
            key = getattr(pe, "sport_category", "").lower()
            poly_by_sport.setdefault(key, []).append(pe)

        # Step 1 — score every candidate pair above threshold
        all_pairs: List[Tuple[Event, PolymarketEvent, float]] = []
        for trad_event in traditional_events:
            sport_key = trad_event.category.lower() if trad_event.category else ""
            # Use sport-scoped candidates when available, else full list
            candidates = poly_by_sport.get(sport_key) or polymarket_events

            # Date pre-filter: PM end_date within ±3 days of BF commence_time
            # Politics events are exempt from the date filter (elections are months
            # away but still need to be matched).
            is_politics = sport_key == "politics"
            if trad_event.commence_time and not is_politics:
                bf_time = trad_event.commence_time
                if bf_time.tzinfo is None:
                    bf_time = bf_time.replace(tzinfo=timezone.utc)
                candidates = [
                    pe
                    for pe in candidates
                    if pe.end_date is None
                    or abs(
                        (
                            (
                                pe.end_date.replace(tzinfo=timezone.utc)
                                if pe.end_date.tzinfo is None
                                else pe.end_date
                            )
                            - bf_time
                        ).total_seconds()
                    )
                    <= 3 * 86400
                ]

            for pe in candidates:
                score = self._calculate_similarity(trad_event, pe)
                if score >= self.similarity_threshold:
                    all_pairs.append((trad_event, pe, score))

        # Step 2 — sort by score descending
        all_pairs.sort(key=lambda x: x[2], reverse=True)

        # Step 3 — greedy 1:1 assignment
        used_bf: set = set()
        used_pm: set = set()
        matches: List[Tuple[Event, PolymarketEvent, float]] = []
        for bf_ev, pm_ev, score in all_pairs:
            if bf_ev.id not in used_bf and pm_ev.id not in used_pm:
                matches.append((bf_ev, pm_ev, score))
                used_bf.add(bf_ev.id)
                used_pm.add(pm_ev.id)

        matched_bfids = {bf.id for bf, _, _ in matches}
        print(
            f"[MATCHING] {len(matches)} matches  "
            f"({len(matched_bfids)} unique Betfair events)"
        )
        return matches

    def find_politics_matches(
        self,
        bf_events: List[Event],
        pm_events: List[PolymarketEvent],
    ) -> List[Tuple[Event, PolymarketEvent, float]]:
        """
        Match political prediction markets across Betfair and Polymarket.

        Key differences from sports matching:
          - No date filter (elections can be months away)
          - Scored by keyword + candidate/party name overlap, not team presence
          - Lower default threshold (0.30) since political text is noisier
        """
        POLITICS_THRESHOLD = 0.30

        all_pairs: List[Tuple[Event, PolymarketEvent, float]] = []
        for bf_ev in bf_events:
            for pm_ev in pm_events:
                score = self._calculate_politics_similarity(bf_ev, pm_ev)
                if score >= POLITICS_THRESHOLD:
                    all_pairs.append((bf_ev, pm_ev, score))

        all_pairs.sort(key=lambda x: x[2], reverse=True)

        used_bf: set = set()
        used_pm: set = set()
        matches: List[Tuple[Event, PolymarketEvent, float]] = []
        for bf_ev, pm_ev, score in all_pairs:
            if bf_ev.id not in used_bf and pm_ev.id not in used_pm:
                matches.append((bf_ev, pm_ev, score))
                used_bf.add(bf_ev.id)
                used_pm.add(pm_ev.id)

        print(f"[POLITICS MATCHING] {len(matches)} political pairs matched")
        return matches

    def _calculate_politics_similarity(
        self, bf_ev: Event, pm_ev: PolymarketEvent
    ) -> float:
        """
        Score a Betfair political market against a Polymarket political event.

        Signals:
          1. Candidate/party overlap: fraction of BF runner names found in PM text
          2. Keyword overlap (Jaccard): topic words like 'house', 'senate',
             'president', '2026' shared between both platforms
          3. Outcome name match: PM outcome names found in BF runner list
        """
        # Build searchable text from each platform
        bf_runner_names = [
            o.name for o in bf_ev.outcomes if o.bookmaker == "Betfair Exchange"
        ]
        # Include the Betfair market/event name (description) so district codes
        # like "CA-22" captured from the market name are available for matching.
        bf_all_text = self._normalise(
            f"{bf_ev.description or ''} {bf_ev.sport} "
            f"{bf_ev.home_team} {bf_ev.away_team} " + " ".join(bf_runner_names)
        )

        pm_all_text = self._normalise(
            pm_ev.question + " " + " ".join(pm_ev.outcomes or [])
        )

        if not bf_all_text or not pm_all_text:
            return 0.0

        # ---- Signal 0: US congressional district code match ----
        # Extracts patterns like "CA-22", "CA 22", "TX 3" from raw text.
        # A matching district code is extremely high-confidence (same race).
        _DIST_RE = re.compile(r"\b([A-Z]{2})[\s\-]?(\d{1,2})\b")

        def _districts(raw: str) -> set:
            return {
                (m.group(1), m.group(2).lstrip("0") or "0")
                for m in _DIST_RE.finditer(raw)
            }

        bf_raw = (
            f"{bf_ev.description or ''} {bf_ev.home_team} {bf_ev.away_team} "
            + " ".join(bf_runner_names)
        )
        pm_raw = pm_ev.question or ""
        bf_dists = _districts(bf_raw)
        pm_dists = _districts(pm_raw)
        district_match = bool(bf_dists and pm_dists and bf_dists & pm_dists)

        # ---- Signal 1: candidate / party name overlap ----
        # How many BF runners appear (by canonical form or alias) in PM text?
        runners_matched = 0
        for r in bf_runner_names:
            r_can = _canonicalise(r)
            # Direct or alias match
            if r.lower() in pm_all_text or r_can in pm_all_text:
                runners_matched += 1
                continue
            # Alias check
            for alias in TEAM_ALIASES.get(r_can, []):
                if alias in pm_all_text:
                    runners_matched += 1
                    break
            else:
                # Partial token match (e.g. 'republican' in 'republican party')
                tokens = [t for t in re.split(r"[\s\-/]+", r.lower()) if len(t) > 3]
                if tokens and all(t in pm_all_text for t in tokens):
                    runners_matched += 1

        runner_ratio = (
            runners_matched / len(bf_runner_names) if bf_runner_names else 0.0
        )

        # ---- Signal 2: keyword (Jaccard) overlap ----
        _POL_STOP = {
            "will",
            "the",
            "who",
            "win",
            "wins",
            "which",
            "party",
            "candidate",
            "election",
            "next",
            "get",
            "control",
            "majority",
            "seat",
            "seats",
            "yes",
            "no",
            "and",
            "or",
            "in",
            "of",
            "for",
            "be",
            "at",
            "to",
        }
        bf_tokens = {
            w for w in bf_all_text.split() if len(w) > 2 and w not in _POL_STOP
        }
        pm_tokens = {
            w for w in pm_all_text.split() if len(w) > 2 and w not in _POL_STOP
        }
        jaccard = (
            len(bf_tokens & pm_tokens) / len(bf_tokens | pm_tokens)
            if bf_tokens and pm_tokens
            else 0.0
        )

        # ---- Signal 3: PM outcome names found in BF runner list ----
        pm_outcomes_matched = 0
        for pm_out in pm_ev.outcomes or []:
            pm_can = _canonicalise(pm_out)
            if pm_out.lower() in {"yes", "no"}:
                continue  # skip Yes/No — not informative
            if pm_out.lower() in bf_all_text or pm_can in bf_all_text:
                pm_outcomes_matched += 1
                continue
            for alias in TEAM_ALIASES.get(pm_can, []):
                if alias in bf_all_text:
                    pm_outcomes_matched += 1
                    break
        pm_outcomes = [
            o for o in (pm_ev.outcomes or []) if o.lower() not in {"yes", "no"}
        ]
        outcome_ratio = pm_outcomes_matched / len(pm_outcomes) if pm_outcomes else 0.0

        # ---- Region / country conflict check ----
        # If BF and PM unambiguously identify DIFFERENT countries, they cannot
        # be the same market (e.g. US house race vs Hungarian prime minister).
        bf_regions = _extract_regions(bf_raw + " " + bf_all_text)
        pm_regions = _extract_regions(pm_raw + " " + pm_all_text)
        if bf_regions and pm_regions and not (bf_regions & pm_regions):
            return 0.0

        score = runner_ratio * 0.45 + jaccard * 0.30 + outcome_ratio * 0.25

        # District match is near-certain proof of the same race — boost to at
        # least 0.75 so it clears the 0.30 threshold even when runner names
        # differ between platforms (e.g. Betfair has candidate names,
        # Polymarket has party names).
        if district_match:
            score = max(score, 0.75)

        return min(score, 1.0)

    def find_candidate_binary_matches(
        self,
        bf_events: List[Event],
        pm_events: List[PolymarketEvent],
    ) -> List[Tuple[Event, str, PolymarketEvent, float]]:
        """
        For Betfair politics markets with MORE than 2 runners (multi-candidate
        primaries / elections), match each individual runner against a Polymarket
        binary YES/NO market that specifically asks about THAT candidate.

        Only triggered when:
          - The BF market has >2 distinct runners  (binary races use standard system)
          - The PM market has exactly 2 outcomes, both in {"Yes", "No"}

        Returns: [(bf_event, runner_name, pm_event, score), ...]
        Each tuple means: runner_name in bf_event ↔ the YES outcome of pm_event.
        """
        _BINARY = {"yes", "no"}
        _DIST_RE = re.compile(r"\b([A-Z]{2})[\s\-]?(\d{1,2})\b")
        _KSTOP = {
            "will",
            "the",
            "win",
            "wins",
            "who",
            "which",
            "seat",
            "party",
            "race",
            "election",
            "for",
            "and",
            "run",
            "primary",
            "general",
        }

        def _dist_codes(text: str) -> set:
            return {
                (m.group(1), m.group(2).lstrip("0") or "0")
                for m in _DIST_RE.finditer(text)
            }

        # Pre-filter: only pure YES/NO binary Polymarket markets
        binary_pm = [
            pm
            for pm in pm_events
            if len(pm.outcomes or []) == 2
            and all(o.lower() in _BINARY for o in (pm.outcomes or []))
        ]

        used_pm: set = set()
        results: List[Tuple[Event, str, PolymarketEvent, float]] = []

        for bf_ev in bf_events:
            bf_runners = list(
                {o.name for o in bf_ev.outcomes if o.bookmaker == "Betfair Exchange"}
            )
            # Only multi-candidate races (>2 runners) — binary races use standard system
            if len(bf_runners) <= 2:
                continue

            bf_ctx_raw = (
                f"{bf_ev.description or ''} {bf_ev.home_team} {bf_ev.away_team}"
            )
            bf_dists = _dist_codes(bf_ctx_raw)
            bf_ctx_norm = self._normalise(bf_ctx_raw)
            bf_kw = {w for w in bf_ctx_norm.split() if len(w) > 3 and w not in _KSTOP}
            bf_regions = _extract_regions(bf_ctx_raw)

            for runner in bf_runners:
                runner_can = _canonicalise(runner)
                runner_tokens = [
                    t for t in re.split(r"[\s\-/]+", runner.lower()) if len(t) > 2
                ]

                # Gate: require at least £2 available on BOTH back and lay for this runner
                back_vol = next(
                    (
                        o.volume
                        for o in bf_ev.outcomes
                        if o.bookmaker == "Betfair Exchange" and o.name == runner
                    ),
                    0.0,
                )
                lay_vol = next(
                    (
                        o.volume
                        for o in bf_ev.outcomes
                        if o.bookmaker == "Betfair Lay" and o.name == runner
                    ),
                    0.0,
                )
                if back_vol < 2.0 or lay_vol < 2.0:
                    continue

                best_pm: Optional[PolymarketEvent] = None
                best_score = 0.0

                for pm_ev in binary_pm:
                    if pm_ev.id in used_pm:
                        continue

                    pm_q = pm_ev.question or ""
                    pm_q_norm = self._normalise(pm_q)

                    # Region / country conflict — skip immediately if unambiguous mismatch
                    pm_regions = _extract_regions(pm_q)
                    if bf_regions and pm_regions and not (bf_regions & pm_regions):
                        continue

                    # Primary: runner name must appear in the PM question
                    score = 0.0
                    if runner.lower() in pm_q_norm or runner_can in pm_q_norm:
                        score += 0.6
                    elif runner_tokens and all(t in pm_q_norm for t in runner_tokens):
                        score += 0.4
                    else:
                        for alias in TEAM_ALIASES.get(runner_can, []):
                            if alias in pm_q_norm:
                                score += 0.4
                                break

                    if score == 0.0:
                        continue  # candidate not mentioned — skip

                    # Bonus: matching district/constituency code
                    pm_dists = _dist_codes(pm_q)
                    if bf_dists and pm_dists and bf_dists & pm_dists:
                        score += 0.4

                    # Bonus: shared election context keywords (state, year, etc.)
                    pm_kw = {
                        w for w in pm_q_norm.split() if len(w) > 3 and w not in _KSTOP
                    }
                    score += min(0.2, len(bf_kw & pm_kw) * 0.05)

                    score = min(score, 1.0)
                    if score > best_score:
                        best_score = score
                        best_pm = pm_ev

                if (
                    best_pm is not None
                    and best_score >= 0.5
                    and best_pm.id not in used_pm
                ):
                    results.append((bf_ev, runner, best_pm, best_score))
                    used_pm.add(best_pm.id)

        print(f"[POLITICS MATCHING] {len(results)} candidate-binary pairs matched")
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_best_match(
        self, trad_event: Event, poly_events: List[PolymarketEvent]
    ) -> Optional[Tuple[PolymarketEvent, float]]:
        best_match = None
        best_score = 0.0
        for pe in poly_events:
            score = self._calculate_similarity(trad_event, pe)
            if score > best_score:
                best_score = score
                best_match = pe
        return (
            (best_match, best_score)
            if best_match and best_score >= self.similarity_threshold
            else None
        )

    def _calculate_similarity(
        self, trad_event: Event, poly_event: PolymarketEvent
    ) -> float:
        """
        Multi-signal similarity score (0–1).

        Dispatches to the sport-specific matcher (from the matchers/ package)
        which handles competition-prefix stripping, club-name normalisation,
        and nickname-only matching for each sport.

        Falls back to the legacy inline logic only when the matchers package
        raises an unexpected error.
        """
        try:
            from backend.matchers import get_matcher

            matcher = get_matcher(trad_event.category)
            result = matcher.score(trad_event, poly_event)
            if result is not None:
                return float(result)
        except Exception:
            pass  # fall through to legacy implementation

        # ---- Legacy inline implementation (fallback) ----
        # Strip competition prefix from Polymarket question
        poly_question = poly_event.question
        poly_match_part = (
            poly_question.split(":", 1)[1].strip()
            if ":" in poly_question
            else poly_question
        )

        poly_text = self._normalise(poly_question)
        poly_match_text = self._normalise(poly_match_part)

        # Polymarket sports events carry team names in outcomes list:
        # e.g. outcomes = ["Real Madrid", "Getafe", "Draw"]
        # Combine all outcome names into a searchable string
        poly_outcomes_text = self._normalise(
            " ".join(poly_event.outcomes if poly_event.outcomes else [])
        )

        # ---- Canonicalise Betfair team names ----
        home_raw = trad_event.home_team
        away_raw = trad_event.away_team
        home_can = _canonicalise(home_raw)
        away_can = _canonicalise(away_raw)

        # ---- Check presence of each team in Polymarket data ----
        # We check: question text, match part, outcomes, AND canonical variants
        poly_combined = f"{poly_text} {poly_match_text} {poly_outcomes_text}"

        def _team_in_poly(team_raw: str, team_can: str) -> bool:
            tl = team_raw.lower()
            # 1. Full canonical name in poly text (strongest signal)
            if tl in poly_combined or team_can in poly_combined:
                return True
            # 2. Any registered alias present
            for alias in TEAM_ALIASES.get(team_can, []):
                if alias in poly_combined:
                    return True
            # 3. ALL distinctive tokens must appear (prevents city-name false positives).
            #    'Distinctive' = not in _GENERIC_NAME_TOKENS and length > 3.
            #    E.g. 'Atletico Madrid' → distinctive=['atletico','madrid'];
            #    both must be in poly — just 'madrid' alone is not enough.
            raw_tokens = [t for t in re.split(r"[\s\-/]+", tl) if len(t) > 2]
            distinctive = [
                t for t in raw_tokens if t not in _GENERIC_NAME_TOKENS and len(t) > 3
            ]
            if distinctive:
                return all(t in poly_combined for t in distinctive)
            # 4. Single-word short team (all tokens ≤3 or all generic) — require canonical
            return False

        home_found = _team_in_poly(home_raw, home_can)
        away_found = _team_in_poly(away_raw, away_can)

        # Hard gate: for sports events BOTH teams must be detectable
        if not (home_found and away_found):
            return 0.0

        score = 0.0

        # Signal 1: Both teams present (+0.55 is the dominant signal)
        score += 0.55

        # Signal 2: String similarity on team-pair vs Polymarket match part
        trad_pair = self._normalise(f"{home_raw} {away_raw}")
        seq_sim = max(
            self._seq_sim(trad_pair, poly_match_text),
            self._seq_sim(self._normalise(f"{home_can} {away_can}"), poly_match_text),
        )
        score += seq_sim * 0.20  # up to +0.20

        # Signal 3: Jaccard token overlap
        trad_tokens = self._tokens(trad_pair)
        poly_tokens = self._tokens(poly_match_text)
        if trad_tokens and poly_tokens:
            jaccard = len(trad_tokens & poly_tokens) / len(trad_tokens | poly_tokens)
            score += jaccard * 0.15  # up to +0.15

        # Signal 4: Date proximity
        if poly_event.end_date and trad_event.commence_time:
            score += (
                self._date_score(trad_event.commence_time, poly_event.end_date) * 0.10
            )

        return min(score, 1.0)

    # ------------------------------------------------------------------
    # Outcome alignment (for arbitrage engine)
    # ------------------------------------------------------------------

    def align_outcomes(
        self, trad_event: Event, poly_event: PolymarketEvent
    ) -> List[Tuple[str, str]]:
        """
        Return list of (betfair_runner_name, polymarket_outcome_name) pairs
        where the two names refer to the same real-world team/player.

        Used by the arbitrage engine to decide which outcomes to compare.

        For binary Yes/No markets (e.g. "Will Arsenal win? Yes/No"), the
        'Yes' outcome is resolved to the team named in the question.
        """
        _BINARY = {"yes", "no"}
        _DRAW_VARIANTS = {"draw", "the draw", "tie", "drawn", "x"}

        # Only align back outcomes — lay outcomes are handled by _check_lay_back
        back_outcomes = [o for o in trad_event.outcomes if o.bookmaker != "Betfair Lay"]

        # Binary market fallback: resolve "Yes"/"No" → both team names.
        # Works for tennis/2-outcome sports where PM uses Yes/No format.
        if poly_event.outcomes and all(
            o.lower() in _BINARY for o in poly_event.outcomes
        ):
            # Build a searchable text from the question (outcomes are just Yes/No)
            poly_all_text = self._normalise(poly_event.question)

            yes_bf_name: Optional[str] = None
            for outcome in back_outcomes:
                team_can = _canonicalise(outcome.name)
                if team_can in _DRAW_VARIANTS:
                    continue
                # 1. Canonical substring match
                if team_can and team_can in poly_all_text:
                    yes_bf_name = outcome.name
                    break
                # 2. Distinctive-token match — handles "Djokovic N." vs "djokovic"
                tl = outcome.name.lower()
                raw_tokens = [t for t in re.split(r"[\s\-/]+", tl) if len(t) > 2]
                distinctive = [t for t in raw_tokens if len(t) > 3]
                if distinctive and all(t in poly_all_text for t in distinctive):
                    yes_bf_name = outcome.name
                    break

            if not yes_bf_name:
                return []

            pairs: List[Tuple[str, str]] = [(yes_bf_name, "Yes")]
            # Map the complementary runner to "No" (binary opposite)
            yes_can = _canonicalise(yes_bf_name)
            for outcome in back_outcomes:
                team_can = _canonicalise(outcome.name)
                if team_can == yes_can or team_can in _DRAW_VARIANTS:
                    continue
                pairs.append((outcome.name, "No"))
                break  # only one complement
            return pairs

        pairs: List[Tuple[str, str]] = []
        used_poly: set = set()

        for outcome in back_outcomes:
            bf_can = _canonicalise(outcome.name)
            best_poly: Optional[str] = None
            best_score = 0.0
            for pm_outcome in poly_event.outcomes:
                if pm_outcome in used_poly:
                    continue
                pm_can = _canonicalise(pm_outcome)
                # Direct canonical match
                if bf_can == pm_can:
                    best_poly = pm_outcome
                    best_score = 1.0
                    break
                # Alias match
                s = self._seq_sim(bf_can, pm_can)
                if s > best_score:
                    best_score = s
                    best_poly = pm_outcome
            if best_poly and best_score >= 0.5:
                pairs.append((outcome.name, best_poly))
                used_poly.add(best_poly)

        return pairs

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def _normalise(self, text: str) -> str:
        text = (
            unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("ascii")
        )
        text = text.lower()
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _tokens(self, text: str) -> set:
        stop = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "vs",
            "versus",
            "win",
            "winner",
            "match",
            "game",
            "fc",
            "afc",
            "sc",
            "cf",
            "ac",
            "as",
            "us",
        }
        return {w for w in text.split() if len(w) > 2 and w not in stop}

    def _seq_sim(self, s1: str, s2: str) -> float:
        return SequenceMatcher(None, s1, s2).ratio()

    def _date_score(self, bf_time: datetime, pm_time: datetime) -> float:
        """1.0 within 6h, 0.5 at 36h, 0.0 beyond 3 days."""
        if bf_time.tzinfo is None:
            bf_time = bf_time.replace(tzinfo=timezone.utc)
        if pm_time.tzinfo is None:
            pm_time = pm_time.replace(tzinfo=timezone.utc)
        diff = abs((bf_time - pm_time).total_seconds())
        if diff <= 6 * 3600:
            return 1.0
        elif diff <= 36 * 3600:
            return 1.0 - ((diff - 6 * 3600) / (30 * 3600)) * 0.5
        elif diff <= 3 * 86400:
            return max(0.0, 0.5 - ((diff - 36 * 3600) / (36 * 3600)) * 0.5)
        return 0.0

    # ------------------------------------------------------------------
    # create_combined_event — unchanged contract, improved outcome alignment
    # ------------------------------------------------------------------

    def create_combined_event(
        self, trad_event: Event, poly_event: PolymarketEvent
    ) -> Event:
        """
        Merge Betfair and Polymarket outcomes into one Event.

        For sports markets Polymarket outcomes are team names (not Yes/No),
        so we tag each Polymarket outcome with the platform name and treat
        them as additional price sources for the same real-world outcome.
        """
        decimal_odds = poly_event.to_decimal_odds()
        poly_outcomes: List[Outcome] = []
        for pm_name, odds in zip(poly_event.outcomes, decimal_odds):
            if odds > 1.0:
                poly_outcomes.append(
                    Outcome(
                        name=pm_name,
                        price=odds,
                        bookmaker="Polymarket",
                        last_update=datetime.now(),
                    )
                )

        combined = Event(
            id=f"{trad_event.id}_combined",
            sport=trad_event.sport,
            commence_time=trad_event.commence_time,
            home_team=trad_event.home_team,
            away_team=trad_event.away_team,
            outcomes=trad_event.outcomes + poly_outcomes,
            category=trad_event.category,
            description=f"{trad_event} / Polymarket: {poly_event.question}",
            match_quality=1.0,
        )
        return combined

    # ------------------------------------------------------------------
    # Legacy helpers kept for compatibility
    # ------------------------------------------------------------------

    def _extract_keywords(self, text: str) -> set:
        return self._tokens(text)

    def _string_similarity(self, s1: str, s2: str) -> float:
        return self._seq_sim(s1, s2)

    def _time_similarity(self, time1: datetime, time2: datetime) -> float:
        return self._date_score(time1, time2)

    def match_by_category(self, category, traditional_events, polymarket_events):
        return self.find_matches(traditional_events, polymarket_events)

    def _get_category_keywords(self, category: str) -> List[str]:
        return []

    def _normalize_text(self, text: str) -> str:
        return self._normalise(text)

    def _legacy_find_matches(
        self, traditional_events: List[Event], polymarket_events: List[PolymarketEvent]
    ) -> List[Tuple[Event, PolymarketEvent, float]]:
        """
        Find matching events between traditional bookmakers and Polymarket.

        Args:
            traditional_events: Events from traditional bookmakers
            polymarket_events: Events from Polymarket

        Returns:
            List of tuples (traditional_event, polymarket_event, similarity_score)
        """
        matches = []

        print(
            f"\n[MATCHING] Starting to match {len(traditional_events)} traditional events against {len(polymarket_events)} Polymarket markets"
        )
        print(f"[MATCHING] Similarity threshold: {self.similarity_threshold}")

        for trad_event in traditional_events:
            best_match = self._find_best_match(trad_event, polymarket_events)
            if best_match:
                poly_event, score = best_match
                if score >= self.similarity_threshold:
                    matches.append((trad_event, poly_event, score))

        print(
            f"[MATCHING] {len(matches)}/{len(traditional_events)} matched (threshold={self.similarity_threshold})"
        )
        return matches

    def _legacy_find_best_match(
        self, trad_event: Event, poly_events: List[PolymarketEvent]
    ) -> Optional[Tuple[PolymarketEvent, float]]:
        """Find the best matching Polymarket event for a traditional event."""
        best_match = None
        best_score = 0.0

        for poly_event in poly_events:
            score = self._calculate_similarity(trad_event, poly_event)
            if score > best_score and score >= self.similarity_threshold:
                best_score = score
                best_match = poly_event

        return (best_match, best_score) if best_match else None

    def _legacy_calculate_similarity(
        self, trad_event: Event, poly_event: PolymarketEvent
    ) -> float:
        """
        Calculate similarity score between traditional and Polymarket events.

        Returns:
            Similarity score between 0 and 1
        """
        scores = []

        # Polymarket sports titles look like "T20 World Cup: India vs West Indies"
        # Strip the competition prefix (everything before the colon) to isolate team names
        poly_question = poly_event.question
        if ":" in poly_question:
            poly_match_part = poly_question.split(":", 1)[1].strip()
        else:
            poly_match_part = poly_question

        # Compare event names/questions
        trad_text = self._normalize_text(
            f"{trad_event.home_team} {trad_event.away_team} {trad_event.sport}"
        )
        poly_text = self._normalize_text(poly_question)
        poly_match_text = self._normalize_text(poly_match_part)

        # Check if team names appear in Polymarket question (full or match part)
        home_lower = trad_event.home_team.lower()
        away_lower = trad_event.away_team.lower()
        home_in_poly = home_lower in poly_text or home_lower in poly_match_text
        away_in_poly = away_lower in poly_text or away_lower in poly_match_text

        # Also check if Polymarket outcome names match team names
        # (e.g. outcomes=["India","West Indies"] vs home_team="India")
        poly_outcomes_lower = [o.lower() for o in poly_event.outcomes]
        if not home_in_poly:
            home_in_poly = any(
                home_lower in o or o in home_lower for o in poly_outcomes_lower
            )
        if not away_in_poly:
            away_in_poly = any(
                away_lower in o or o in away_lower for o in poly_outcomes_lower
            )

        # STRICT REQUIREMENT: For sports events, BOTH team names must be present
        # This prevents false matches like "FC Volendam vs Groningen" matching "Beth Van Duyne"
        if trad_event.sport and trad_event.sport.lower() not in [
            "polymarket",
            "prediction",
        ]:
            if not (home_in_poly and away_in_poly):
                return 0.0  # No match if both teams aren't mentioned

        # Direct string similarity (use match part for sports to avoid low scores from prefix)
        name_similarity = max(
            self._string_similarity(trad_text, poly_text),
            self._string_similarity(
                self._normalize_text(f"{trad_event.home_team} {trad_event.away_team}"),
                poly_match_text,
            ),
        )
        scores.append(name_similarity * 0.3)  # 30% weight

        if home_in_poly and away_in_poly:
            scores.append(0.6)  # 60% bonus if both teams found (key signal)
        elif home_in_poly or away_in_poly:
            scores.append(0.25)  # 25% bonus if one team mentioned

        # Check for keyword matches
        trad_keywords = self._extract_keywords(trad_text)
        poly_keywords = self._extract_keywords(poly_text)

        if trad_keywords and poly_keywords:
            keyword_match = len(trad_keywords & poly_keywords) / max(
                len(trad_keywords), len(poly_keywords)
            )
            scores.append(keyword_match * 0.15)  # 15% weight

        # Compare time proximity (if available)
        if poly_event.end_date:
            time_similarity = self._time_similarity(
                trad_event.commence_time, poly_event.end_date
            )
            scores.append(time_similarity * 0.1)  # 10% weight

        return min(sum(scores), 1.0)

    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison."""
        text = text.lower()
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _extract_keywords(self, text: str) -> set:
        """Extract significant keywords from text."""
        # Remove common words
        stop_words = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
            "will",
            "be",
            "is",
            "are",
            "was",
            "were",
            "vs",
            "versus",
            "win",
            "winner",
            "match",
            "game",
            "event",
        }

        words = text.split()
        keywords = {w for w in words if len(w) > 2 and w not in stop_words}
        return keywords

    def _string_similarity(self, s1: str, s2: str) -> float:
        """Calculate string similarity using SequenceMatcher."""
        return SequenceMatcher(None, s1, s2).ratio()

    def _time_similarity(self, time1: datetime, time2: datetime) -> float:
        """Calculate similarity based on time proximity."""
        # Handle None values
        if time1 is None or time2 is None:
            return 0.0

        # Make both timezone-aware or both timezone-naive
        if time1.tzinfo is None and time2.tzinfo is not None:
            # Make time1 aware (assume UTC)
            from datetime import timezone

            time1 = time1.replace(tzinfo=timezone.utc)
        elif time1.tzinfo is not None and time2.tzinfo is None:
            # Make time2 aware (assume UTC)
            from datetime import timezone

            time2 = time2.replace(tzinfo=timezone.utc)

        time_diff = abs((time1 - time2).total_seconds())

        # Events within 1 day = 100% similarity
        # Events within 1 week = 50% similarity
        # Beyond 1 week = 0% similarity

        if time_diff <= 86400:  # 1 day
            return 1.0
        elif time_diff <= 604800:  # 1 week
            return 1.0 - ((time_diff - 86400) / 518400)  # Linear decay
        else:
            return 0.0

    def match_by_category(
        self,
        category: str,
        traditional_events: List[Event],
        polymarket_events: List[PolymarketEvent],
    ) -> List[Tuple[Event, PolymarketEvent, float]]:
        """
        Find matches within a specific category.

        Args:
            category: Market category (politics, entertainment, etc.)
            traditional_events: Traditional bookmaker events
            polymarket_events: Polymarket events

        Returns:
            List of matched event pairs
        """
        # Filter events by category
        filtered_trad = [
            e
            for e in traditional_events
            if e.category and category.lower() in e.category.lower()
        ]

        # Polymarket doesn't have explicit categories in our model,
        # so we use keyword matching
        category_keywords = self._get_category_keywords(category)
        filtered_poly = [
            p
            for p in polymarket_events
            if any(kw in p.question.lower() for kw in category_keywords)
        ]

        return self.find_matches(filtered_trad, filtered_poly)

    def _get_category_keywords(self, category: str) -> List[str]:
        """Get keywords associated with a market category."""
        keyword_map = {
            "politics": [
                "election",
                "president",
                "senate",
                "congress",
                "vote",
                "political",
            ],
            "entertainment": [
                "oscar",
                "grammy",
                "emmy",
                "award",
                "movie",
                "film",
                "actor",
            ],
            "crypto": ["bitcoin", "ethereum", "crypto", "blockchain", "btc", "eth"],
            "finance": ["stock", "market", "economy", "gdp", "inflation", "rate"],
            "sports": ["game", "match", "championship", "league", "cup", "tournament"],
            "science": ["climate", "space", "technology", "research", "discovery"],
            "business": ["company", "merger", "ipo", "earnings", "ceo"],
        }
        return keyword_map.get(category.lower(), [])

    def _legacy_create_combined_event(
        self, trad_event: Event, poly_event: PolymarketEvent
    ) -> Event:
        """
        Create a combined event with outcomes from both platforms.

        Args:
            trad_event: Traditional bookmaker event
            poly_event: Polymarket event

        Returns:
            Combined Event with all outcomes
        """
        # Convert Polymarket prices to outcomes
        poly_outcomes = []
        decimal_odds = poly_event.to_decimal_odds()

        for outcome_name, odds in zip(poly_event.outcomes, decimal_odds):
            if odds > 0:  # Valid odds
                poly_outcome = Outcome(
                    name=outcome_name,
                    price=odds,
                    bookmaker="Polymarket",
                    last_update=datetime.now(),
                )
                poly_outcomes.append(poly_outcome)

        # Combine outcomes
        all_outcomes = trad_event.outcomes + poly_outcomes

        # Create combined event
        combined = Event(
            id=f"{trad_event.id}_combined",
            sport=trad_event.sport,
            commence_time=trad_event.commence_time,
            home_team=trad_event.home_team,
            away_team=trad_event.away_team,
            outcomes=all_outcomes,
            category=trad_event.category,
            description=f"{trad_event} / Polymarket: {poly_event.question}",
            match_quality=1.0,  # Will be set by caller based on similarity score
        )

        return combined
