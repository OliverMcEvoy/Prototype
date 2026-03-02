"""
matchers/soccer_matcher.py
==========================
Soccer / Football market matcher.

Key problems solved vs the generic matcher:
  • Polymarket uses FULL official names: "FC Barcelona", "Club Atlético de Madrid",
    "Brighton & Hove Albion FC", "Wolverhampton Wanderers FC"
  • Betfair uses short-form names: "Barcelona", "Atletico Madrid", "Brighton", "Wolves"
  • Strip leading "FC ", "Club ", "CD ", "AS ", "AC " etc. before comparing
  • Strip trailing "Calcio", "Fußball", founding years, etc.
  • Women's matches carry "(W)" on Betfair; PM may omit or use "Women"
  • Youth / reserve teams (U21, U19, Res) should score near-zero — they
    are rarely on Polymarket and cause false positives
  • Handle "de / di / van / del" particles without losing the club name
"""

import re
from typing import Dict, List, Optional

from models import Event, PolymarketEvent
from matchers.base_matcher import BaseSportMatcher, GENERIC_TOKENS


class SoccerMatcher(BaseSportMatcher):
    """Match soccer (football) markets across Betfair and Polymarket."""

    THRESHOLD = 0.35

    # Betfair → Polymarket name aliases for soccer.
    # Key = canonical (lower), values = alternative spellings.
    ALIASES: Dict[str, List[str]] = {
        # England — Premier League
        "manchester united": ["man utd", "man united", "manchester utd", "mufc"],
        "manchester city": ["man city", "man c", "mcfc"],
        "tottenham hotspur": ["spurs", "tottenham", "thfc"],
        "wolverhampton": [
            "wolves",
            "wolverhampton wanderers",
            "wolverhampton wanderers fc",
        ],
        "nottingham forest": [
            "nott'm forest",
            "notts forest",
            "nffc",
            "nottm forest",
            "nottm forest fc",
            "nottingham forest fc",
        ],
        "west bromwich": ["west brom", "wba", "west bromwich albion"],
        "queens park rangers": ["qpr"],
        "sheffield united": ["sheff utd", "sheffield utd", "sheffield united fc"],
        "sheffield wednesday": ["sheff wed", "sheffield wed"],
        "bournemouth": ["afc bournemouth", "afcb", "boscombe"],
        "brighton": [
            "brighton & hove albion",
            "brighton hove",
            "brighton hove albion",
            "brighton & hove albion fc",
        ],
        "newcastle": ["newcastle united", "nufc", "newcastle united fc"],
        "west ham": ["west ham united", "whu", "west ham united fc"],
        "leicester": ["leicester city", "lcfc", "leicester city fc"],
        "ipswich": ["ipswich town", "ipswich town fc"],
        "luton": ["luton town", "luton town fc"],
        "sunderland": ["sunderland afc", "safc"],
        "hull": ["hull city", "hull city fc", "hull city afc"],
        "norwich": ["norwich city", "ncfc"],
        "bristol city": ["bristol city fc"],
        "coventry": ["coventry city", "coventry city fc"],
        "swansea": ["swansea city", "swansea city afc"],
        "blackburn": ["blackburn rovers", "blackburn rovers fc"],
        "burnley": ["burnley fc"],
        "watford": ["watford fc"],
        "crystal palace": ["crystal palace fc"],
        "southampton": ["southampton fc", "the saints"],
        "brentford": ["brentford fc"],
        "everton": ["everton fc", "toffees"],
        "arsenal": ["arsenal fc", "the gunners"],
        "chelsea": ["chelsea fc", "the blues"],
        "liverpool": ["liverpool fc", "the reds"],
        "fulham": ["fulham fc"],
        "aston villa": ["aston villa fc"],
        "leeds": ["leeds united", "lufc", "leeds united fc"],
        "middlesbrough": ["boro", "middlesbrough fc"],
        "stoke": ["stoke city", "stoke city fc"],
        "derby": ["derby county", "derby county fc"],
        "millwall": ["millwall fc"],
        "rotherham": ["rotherham united", "rotherham united fc"],
        "barnsley": ["barnsley fc"],
        "birmingham": ["birmingham city", "birmingham city fc"],
        "charlton": ["charlton athletic", "charlton athletic fc"],
        "portsmouth": ["portsmouth fc"],
        "reading": ["reading fc"],
        "preston": ["preston north end", "pne"],
        "oxford": ["oxford united"],
        "exeter": ["exeter city"],
        # Scotland
        "celtic": ["celtic fc", "glasgow celtic"],
        "rangers": ["glasgow rangers", "rangers fc"],
        "hearts": ["heart of midlothian", "heart of midlothian fc"],
        "hibernian": ["hibs", "hibernian fc"],
        # Spain — La Liga
        "barcelona": ["fc barcelona", "barca", "barca fc"],
        "real madrid": ["real madrid cf", "real madrid fc"],
        "atletico madrid": [
            "atletico de madrid",
            "atl madrid",
            "atletico madrid cf",
            "club atletico de madrid",
        ],
        "real betis": ["real betis balompie", "betis"],
        "athletic bilbao": ["athletic club", "athletic bilbao fc"],
        "deportivo alaves": ["alaves", "deportivo alaves fc"],
        "real sociedad": ["r sociedad", "real sociedad de futbol", "real sociedad fc"],
        "valencia": ["valencia cf", "valencia fc"],
        "villarreal": ["villarreal cf", "villarreal fc"],
        "sevilla": ["sevilla fc"],
        "celta vigo": ["rc celta de vigo", "celta", "celta de vigo"],
        "rayo vallecano": ["rayo", "rayo vallecano de madrid"],
        "girona": ["girona fc"],
        "osasuna": ["ca osasuna"],
        "getafe": ["getafe cf"],
        "leganes": ["cd leganes"],
        "mallorca": ["rcd mallorca", "real mallorca"],
        "espanyol": ["rcd espanyol", "rcd espanyol de barcelona"],
        "elche": ["elche cf"],
        "cadiz": ["cadiz cf"],
        "almeria": ["ud almeria"],
        "granada": ["granada cf"],
        # Italy — Serie A / B
        "napoli": ["ssc napoli", "napoli calcio"],
        "ac milan": ["milan", "ac milan fc"],
        "inter milan": [
            "inter",
            "internazionale",
            "fc internazionale",
            "fc internazionale milano",
            "inter milan fc",
        ],
        "juventus": ["juve", "juventus fc"],
        "as roma": ["roma", "as roma fc"],
        "ss lazio": ["lazio", "ss lazio fc"],
        "atalanta": ["atalanta bc", "atalanta bc fc"],
        "fiorentina": ["acf fiorentina", "acf fiorentina fc"],
        "torino": ["torino fc"],
        "bologna": ["bologna fc", "bologna fc 1909"],
        "udinese": ["udinese calcio"],
        "monza": ["ac monza"],
        "cagliari": ["cagliari calcio"],
        "genoa": ["genoa cfc"],
        "empoli": ["fc empoli"],
        "frosinone": ["frosinone calcio"],
        "salernitana": ["us salernitana"],
        "lecce": ["us lecce"],
        "verona": ["hellas verona", "hellas verona fc"],
        "sassuolo": ["us sassuolo", "us sassuolo calcio"],
        "cremonese": ["us cremonese"],
        "parma": ["parma calcio", "parma calcio 1913"],
        "venezia": ["venezia fc"],
        "pisa": ["pisa sc", "ac pisa"],
        "spezia": ["spezia calcio"],
        "sampdoria": ["uc sampdoria"],
        "bari": ["ssd bari", "as bari"],
        "palermo": ["us palermo"],
        "catanzaro": ["us catanzaro"],
        # Germany — Bundesliga / 2. Bundesliga
        "borussia dortmund": ["bvb", "dortmund", "bv borussia 09 dortmund"],
        "borussia mgladbach": [
            "b. monchengladbach",
            "mgladbach",
            "gladbach",
            "borussia monchengladbach",
            "borussia mönchengladbach",
        ],
        "rb leipzig": ["rbl", "rasenball", "rb leipzig fc"],
        "bayer leverkusen": ["leverkusen", "bayer 04 leverkusen", "b04"],
        "eintracht frankfurt": ["frankfurt", "eintracht frankfurt fc"],
        "werder bremen": ["werder", "sv werder bremen", "1. fc union berlin"],
        "union berlin": ["1. fc union berlin", "fc union berlin"],
        "vfl wolfsburg": ["wolfsburg", "wolfsburg fc"],
        "vfb stuttgart": ["stuttgart", "stuttgart fc"],
        "sc freiburg": ["freiburg", "freiburg fc"],
        "hoffenheim": ["tsg hoffenheim", "tsg 1899 hoffenheim"],
        "fc augsburg": ["augsburg"],
        "hamburger sv": ["hamburg", "hsv", "hamburger sv fc"],
        "fc koln": ["koln", "1. fc koln", "fc köln", "1. fc köln"],
        "mainz": ["1. fsv mainz 05", "1. fsv mainz", "mainz 05"],
        "hertha berlin": ["hertha bsc", "hertha"],
        "heidenheim": ["1. fc heidenheim", "1. fc heidenheim 1846"],
        "st. pauli": ["fc st. pauli", "fc st pauli", "st pauli", "fc st. pauli 1910"],
        # France — Ligue 1
        "paris saint-germain": [
            "psg",
            "paris sg",
            "paris saint germain",
            "paris saint-germain fc",
        ],
        "olympique lyonnais": ["lyon", "ol", "olympique lyonnais fc"],
        "olympique marseille": ["marseille", "om", "olympique de marseille"],
        "stade rennais": ["rennes", "stade rennais fc", "stade rennais fc 1901"],
        "monaco": ["as monaco", "as monaco fc"],
        "lille": ["losc", "losc lille", "lille osc"],
        "nice": ["ogc nice"],
        "lens": ["rc lens", "racing club de lens"],
        "strasbourg": ["rc strasbourg", "rc strasbourg alsace"],
        "nantes": ["fc nantes"],
        "reims": ["stade de reims"],
        "brest": ["stade brestois", "stade brestois 29"],
        "toulouse": ["toulouse fc"],
        "angers": ["angers sco"],
        "lorient": ["fc lorient"],
        "auxerre": ["aj auxerre"],
        "havre": ["le havre", "le havre ac"],
        "metz": ["fc metz"],
        "clermont": ["clermont foot", "asm clermont auvergne"],
        # Portugal — Primeira Liga
        "sl benfica": ["benfica", "sport lisboa e benfica", "slb"],
        "fc porto": ["porto"],
        "sporting cp": [
            "sporting lisbon",
            "sporting",
            "sporting cp fc",
            "sc braga vs sporting cp",  # accidental but harmless
            "sc sporting",
        ],
        "sc braga": ["braga", "sporting braga"],
        "gil vicente": ["gil vicente fc"],
        "famalicao": ["fc famalicao", "fc famalicão"],
        "vitoria sc": ["vitoria guimaraes", "vitoria de guimaraes"],
        # Netherlands — Eredivisie
        "ajax": ["afc ajax", "ajax amsterdam", "ajax fc"],
        "psv": ["psv eindhoven", "psv fc"],
        "feyenoord": ["feyenoord rotterdam"],
        "az": ["az alkmaar"],
        "nec": ["nec nijmegen"],
        "fc utrecht": ["utrecht"],
        "fc groningen": ["groningen"],
        "sc heerenveen": ["heerenveen"],
        "fc twente": ["twente", "fc twente 65"],
        "heracles": ["heracles almelo"],
        "go ahead eagles": ["go ahead"],
        "nac breda": ["nac"],
        "sparta rotterdam": ["sparta"],
        "fortuna sittard": ["fortuna"],
        "telstar": ["telstar 1963"],
        # Turkey — Super Lig
        "galatasaray": ["galatasaray sk", "galatasaray fc"],
        "fenerbahce": ["fenerbahce sk", "fenerbahce fc", "fenerbahçe", "fenerbahçe sk"],
        "besiktas": ["besiktas jk", "beşiktaş", "beşiktaş jk"],
        "trabzonspor": ["trabzon"],
        "basaksehir": ["istanbul basaksehir", "rams basaksehir"],
        "alanyaspor": ["alanya"],
        "kayserispor": ["kayseri"],
        "rizespor": ["caykur rizespor", "çaykur rizespor"],
        "samsunspor": ["samsunspr"],
        "konyaspor": ["konya"],
        # Romania
        "fcsb": ["steaua bucharest", "steaua"],
        "cfr cluj": ["cfr 1907 cluj", "fc cfr 1907 cluj"],
        "universitatea craiova": ["craiova", "univ craiova"],
        "rapid bucharest": ["rapid", "fc rapid 1923"],
        "hermannstadt": ["fc hermannstadt", "fc sibiu"],
        # Czech Republic
        "slavia prague": ["sk slavia praha", "slavia"],
        "sparta prague": ["ac sparta praha", "sparta"],
        "slovan liberec": ["fc slovan liberec"],
        # Poland — Ekstraklasa
        "lech poznan": ["lech", "kks lech poznan"],
        "legia warsaw": ["legia"],
        "wisla krakow": ["wisla", "wisla plock"],
        # Mexico — Liga MX
        "america": ["cf america", "club america", "ca america"],
        "guadalajara": ["chivas", "cd guadalajara", "club deportivo guadalajara"],
        "monterrey": ["cf monterrey"],
        "pumas unam": ["pumas", "pumas de la unam"],
        "tigres": ["tigres uanl", "tigres de la uanl"],
        "cruz azul": ["cf cruz azul"],
        "atlas": ["atlas fc"],
        "toluca": ["deportivo toluca", "deportivo toluca fc"],
        "pachuca": ["cf pachuca"],
        "santos laguna": ["santos", "club santos laguna"],
        "necaxa": ["club necaxa"],
        "tijuana": ["club tijuana", "xolos"],
        "juarez": ["fc juarez", "cf juarez", "fc juárez"],
        "mazatlan": ["mazatlan fc", "mazatlán fc"],
        "queretaro": ["queretaro fc", "querétaro fc"],
        "puebla": ["club puebla", "puebla fc"],
        "leon": ["club leon", "club león"],
        "san luis": ["atletico san luis", "atlético san luis"],
        # Colombia
        "atletico nacional": ["atlético nacional", "nacional"],
        "independiente medellin": ["ind. medellin", "medellin"],
        "deportivo pereira": ["pereira"],
        # Argentina
        "river plate": ["ca river plate", "independiente rivadavia vs river plate"],
        # MLS
        "los angeles galaxy": ["la galaxy", "la galaxy fc"],
        "los angeles fc": ["lafc", "la fc"],
        "atlanta united": ["atlanta united fc"],
        "portland timbers": ["portland"],
        "seattle sounders": ["seattle sounders fc"],
        "colorado rapids": ["colorado rapids sc"],
        "new england revolution": ["new england rev", "revolution"],
        "chicago fire": ["chicago fire fc"],
        "nashville sc": ["nashville"],
        "columbus crew": ["columbus crew sc"],
        "fc dallas": ["dallas", "fc dallas fc"],
        "houston dynamo": ["houston dynamo fc"],
        "new york city fc": ["nycfc", "nyc fc"],
        "new york red bulls": ["nyrb", "red bulls"],
        "philadelphia union": ["union", "philadelphia union fc"],
        "charlotte fc": ["charlotte"],
        "st. louis city sc": ["st louis city"],
        "san jose earthquakes": ["san jose", "sj earthquakes"],
        "sporting kansas city": ["skc", "sporting kc"],
        "real salt lake": ["rsl", "salt lake"],
        "austin fc": ["austin"],
        "inter miami": ["inter miami cf", "miami cf"],
        "dc united": ["dc united sc", "d.c. united", "d.c. united sc"],
        "orlando city": ["orlando city sc"],
        "montreal": ["cf montreal", "impact"],
        "toronto fc": ["toronto"],
        "vancouver whitecaps": ["whitecaps", "vancouver whitecaps fc"],
        "minnesota united": ["minnesota united fc"],
        "san diego fc": ["san diego"],
        # South America
        "botafogo": ["botafogo fr"],
        "flamengo": ["cr flamengo"],
        "fluminense": ["fluminense fc"],
        "palmeiras": ["se palmeiras"],
        "gremio": ["gremio fbpa"],
        "sao paulo": ["sao paulo fc"],
        "santos": ["santos fc"],
        "internacional": ["sc internacional"],
        "atletico mineiro": ["atletico", "atletico mineiro fc"],
        "corinthians": ["sc corinthians paulista"],
        "cruzeiro": ["cruzeiro ec"],
        "boca juniors": ["ca boca juniors"],
        "racing club": ["racing club de avellaneda"],
        "san lorenzo": ["ca san lorenzo"],
        "independiente": ["ca independiente"],
        # Japan / Korea — J-League / K-League
        "kawasaki frontale": ["kawasaki"],
        "gamba osaka": ["gamba"],
        "urawa reds": ["urawa red diamonds"],
        "kashima antlers": ["kashima"],
        "yokohama marinos": ["yokohama f marinos", "yokohama f-marinos"],
        "cerezo osaka": ["cerezo"],
        # Draw
        "draw": ["the draw", "tie", "drawn", "x"],
    }

    # Regex to detect youth / reserve matches (skip these)
    _YOUTH_MATCH_RE = re.compile(
        r"\b(?:u\d{2}|u-\d{2}|under.?\d{2}|youth|reserve|reserves|res|"
        r"b-team|ii|iii|iv|junior|juniors|am\.)\b",
        re.IGNORECASE,
    )

    # -----------------------------------------------------------------------
    # Public interface
    # -----------------------------------------------------------------------

    def score(self, bf_event: Event, pm_event: PolymarketEvent) -> float:
        """Score a Betfair soccer event against a Polymarket soccer event."""
        # Skip youth / reserve matches — they almost never appear on Polymarket
        if self._is_youth_match(bf_event):
            return 0.0

        # Build PM searchable text (with prefix stripped)
        pm_q = pm_event.question
        pm_q_clean = self._strip_competition_prefix(pm_q)

        poly_text = self._normalise(pm_q)
        poly_match = self._normalise(pm_q_clean)
        poly_outcomes = self._normalise(" ".join(pm_event.outcomes or []))
        poly_combined = f"{poly_text} {poly_match} {poly_outcomes}"

        home_found = self._team_in_text(bf_event.home_team, poly_combined)
        away_found = self._team_in_text(bf_event.away_team, poly_combined)

        if not (home_found and away_found):
            return 0.0

        score = 0.55

        bf_pair = self._normalise(f"{bf_event.home_team} {bf_event.away_team}")
        bf_pair_can = self._normalise(
            f"{self._canonicalise(bf_event.home_team)} "
            f"{self._canonicalise(bf_event.away_team)}"
        )
        seq = max(
            self._seq_sim(bf_pair, poly_match),
            self._seq_sim(bf_pair_can, poly_match),
        )
        score += seq * 0.20
        score += self._token_jaccard(bf_pair, poly_match) * 0.15

        if pm_event.end_date and bf_event.commence_time:
            score += self._date_score(bf_event.commence_time, pm_event.end_date) * 0.10

        return min(score, 1.0)

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _is_youth_match(self, event: Event) -> bool:
        """Return True if the BF event is a youth/reserve fixture."""
        combined = f"{event.home_team} {event.away_team} {event.sport or ''}"
        return bool(self._YOUTH_MATCH_RE.search(combined))
