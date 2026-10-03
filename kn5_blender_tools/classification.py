"""Evidence-based, separate car and track mesh classifiers."""

import re


CAR_CATEGORIES = (
    "BODY", "AERO/FRONT_WING", "AERO/REAR_WING", "AERO/OTHER_AERO",
    "WHEELS", "TYRES", "BRAKES", "SUSPENSION", "INTERIOR", "GLASS",
    "LIGHTS", "EXHAUST", "ENGINE", "DRIVER", "DETAILS", "OTHER",
)
TRACK_CATEGORIES = (
    "ROAD", "KERBS", "GRASS", "TERRAIN", "RUNOFF", "GRAVEL_SAND",
    "WALLS_BARRIERS", "FENCES", "BUILDINGS", "PIT_BUILDINGS",
    "GRANDSTANDS", "BRIDGES", "VEGETATION", "SIGNS_ADS", "LIGHTS",
    "PROPS", "OTHER",
)


def _words(value):
    value = re.sub(r"([a-z])([0-9])", r"\1 \2", str(value).casefold())
    value = re.sub(r"([0-9])([a-z])", r"\1 \2", value)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _evidence(name, original, ancestors, material, shader, textures):
    # The nearest KN5 node is more specific than a broad grandparent or material.
    fields = [("mesh", name), ("original", original)]
    fields += [("parent", value) for value in reversed(ancestors)]
    fields += [("material", material)]
    fields += [("texture", value) for value in textures]
    fields += [("shader", shader)]
    return [(label, value, _words(value)) for label, value in fields if value]


def _match(fields, rules):
    for label, value, words in fields:
        for category, pattern in rules:
            if re.search(pattern, words):
                return category, f"{label}: {value} (rule: {pattern})"
    return "OTHER", "no reliable semantic match"


# Strong names and material roles precede broad terms such as BASE or black.
_CAR_STRONG = (
    ("TYRES", r"\b(?:tyres?|tires?|sidewalls?|treads?)\b"),
    ("BRAKES", r"\b(?:brakes?|calipers?|rotors?|discs?|disks?)\b"),
    ("WHEELS", r"\b(?:wheels?|rims?|hubs?)\b"),
    ("SUSPENSION", r"\b(?:susp|suspension|springs?|dampers?|wishbones?|arms?|tethers?)\b"),
    ("AERO/FRONT_WING", r"\b(?:front ?wings?|fwing|fwings?)\b"),
    ("AERO/REAR_WING", r"\b(?:rear ?wings?|rwing|rwings?)\b"),
    ("AERO/OTHER_AERO", r"\b(?:aero|diffusers?|splitters?|spoilers?|canards?|air ?ducts?)\b"),
    ("GLASS", r"\b(?:glass|gls|windows?|windscreens?|windshields?|visors?|defrost)\b|\bwin mask\b"),
    ("LIGHTS", r"\b(?:lights?|headlights?|taillights?|headlamps?|taillamps?|hlbase|tlbase|hlmask|tlmask|leds?|turnsignals?)\b"),
    ("EXHAUST", r"\b(?:exhausts?|mufflers?|tailpipes?)\b"),
    ("ENGINE", r"\b(?:engines?|motors?|radiators?|intakes?|turbo|intercoolers?)\b"),
    ("DRIVER", r"\b(?:drivers?|helmets?|gloves?|driver ?suits?)\b"),
    ("INTERIOR", r"\b(?:interior|intbase|intbadge|cockpit|dash|dashboard|seats?|gauges?|needles?|shifter|steering|steer|paddles?|cinture|seatbelts?)\b|\bint \w+"),
    ("DETAILS", r"\b(?:mirrors?|mirbase|badges?|stripes?|wipers?|antennas?|grilles?|emblems?|logos?)\b"),
    ("BODY", r"\b(?:body|chassis|shell|bonnet|hood|bumpers?|bmp|doors?|roof|floors?|skirt|trunk|boot|underbody|safetycell|paint)\b"),
)
_CAR_BROAD = (("BODY", r"\b(?:base|ext|exterior|carskin)\b"),)


def classify_car(name, original="", ancestors=(), material="", shader="", textures=()):
    """Return (category, evidence) using the original KN5 hierarchy and material."""
    fields = _evidence(name, original, ancestors, material, shader, textures)
    category, reason = _match(fields, _CAR_STRONG)
    return (category, reason) if category != "OTHER" else _match(fields, _CAR_BROAD)


# Track rules deliberately contain no car part categories or car classifier calls.
_TRACK_RULES = (
    ("KERBS", r"\b(?:kerbs?|curbs?|rumble ?strips?)\b"),
    ("GRAVEL_SAND", r"\b(?:gravel|sand|pebbles?)\b"),
    ("RUNOFF", r"\b(?:run ?off|escape ?road|carpet|out)\b"),
    ("ROAD", r"\b(?:roads?|asphalt|asph|tarmac|pavement|pit ?lane|whiteline|white ?line|chalk ?line|concrete|start ?line)\b"),
    ("PIT_BUILDINGS", r"\b(?:pit ?buildings?|pit ?boxes?|pit ?garages?|garages?|paddock|main ?box)\b"),
    ("GRANDSTANDS", r"\b(?:grandstands?|gstands?|tribunes?|bleachers?|seats?)\b"),
    ("BRIDGES", r"\b(?:bridges?|overpasses?|underpasses?)\b"),
    ("FENCES", r"\b(?:fences?|catch ?fences?|mesh ?fences?)\b"),
    ("WALLS_BARRIERS", r"\b(?:walls?|barriers?|barr|armco|guard ?rails?|grail|tecpro|tyre ?walls?|tire ?walls?|tyres?|tires?)\b"),
    ("GRASS", r"\b(?:grass|lawn|turf)\b"),
    ("TERRAIN", r"\b(?:terrain|ground|dirt|earth|soil|landscape)\b"),
    ("VEGETATION", r"\b(?:trees?|bush(?:es)?|shrubs?|vegetation|foliage|pines?|leaves|ivy|branches?|bark)\b"),
    ("SIGNS_ADS", r"\b(?:signs?|banners?|banderin|billboards?|adverts?|advertising|sponsors?|flags?|posters?|distanz|overheadad\w*|direction)\b"),
    ("LIGHTS", r"\b(?:\w*lights?\w*|led|lamps?|floodlights?|semaphores?)\b"),
    ("BUILDINGS", r"\b(?:buildings?|houses?|towers?|structures?|struc|roof ?tiles?)\b"),
    ("PROPS", r"\b(?:props?|cone\w*|cono|marshall\w*|crew|vehicles?|trucks?|ambulances?|sprinters?|ferris|speaker\w*|screens?|cameras?|tvgantry|poles?|stage\w*|spectators?|people|drivers?|suits?|jersey|pobject|trash|movies?|fuselage|aircraft|helicopter|heli|wings?|rotors?|rigging|struts?|undercarriage|helmets?|jackets?|piloto|c130|h135|sopwith)\b"),
)


def classify_track(name, original="", ancestors=(), material="", shader="", textures=(), source=""):
    """Return (category, evidence) from track semantics only."""
    if re.search(r"\b(?:sopwith|c 130|h 135|hel|heli|ferris|movie)\b", _words(source)):
        return "PROPS", f"source KN5: {source} (scene prop model)"
    if re.search(r"\b(?:ef sem|semaphore)\b", _words(source)):
        return "LIGHTS", f"source KN5: {source} (track signal model)"
    return _match(_evidence(name, original, ancestors, material, shader, textures), _TRACK_RULES)
