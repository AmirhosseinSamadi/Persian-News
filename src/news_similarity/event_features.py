"""Conservative Persian evidence extraction with original Unicode offsets."""

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from news_similarity.preprocessing import ARABIC_TO_PERSIAN

RULES_VERSION = "event-features-v1"
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩−", "01234567890123456789-")
MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "فروردین",
            "اردیبهشت",
            "خرداد",
            "تیر",
            "مرداد",
            "شهریور",
            "مهر",
            "آبان",
            "آذر",
            "دی",
            "بهمن",
            "اسفند",
        ),
        1,
    )
}
# Mention lexicon only: no geocoding, city/province inference or alias expansion.
LOCATIONS = tuple(
    (
        "تهران مشهد اصفهان شیراز تبریز کاشان یزد کرمان قم رشت گرگان سنندج "
        "اراک سمنان بوشهر همدان یاسوج اهواز بندرعباس زاهدان زنجان اردبیل "
        "ارومیه بیرجند ایلام قزوین کرج ساری شهرکرد بجنورد ایران"
    ).split()
) + ("خرم‌آباد",)
PREDICATES = {
    "cancel": r"لغو\s+(?:نشد|نشده\s+است|شد|شده\s+است)",
    "approve": r"تصویب\s+(?:نکرد|نشد|نشده\s+است|کرد|شد|شده\s+است)",
    "confirm": r"ت[اأ]یید\s+(?:نکرد|نشد|کرد|شد)",
    "hold": r"برگزار\s+(?:نشد|نشده\s+است|شد|شده\s+است)",
    "succeed": r"موفق\s+(?:نبود|نیست|بود|است)",
    "close": r"تعطیل\s+(?:نشد|نیست|نبود|شد|است|بود)",
    "open": r"افتتاح\s+(?:نشد|نشده\s+است|شد|شده\s+است)",
}
UNIT_RULES = [
    (r"کیلومتر\s+(?:بر|در)\s+ساعت", "km_per_hour", "1", None),
    (r"تن\s+در\s+هکتار", "tonne_per_hectare", "1", None),
    (r"کیلوگرم|کیلو\s+گرم|kg", "kilogram", "1", None),
    (r"گرم|g", "kilogram", "0.001", None),
    (r"تن|tonnes?", "kilogram", "1000", None),
    (r"کیلومتر|کیلو\s+متر|km", "meter", "1000", None),
    (r"متر|m", "meter", "1", None),
    (r"تومان", "IRR", "10", None),
    (r"ریال", "IRR", "1", None),
    (r"درصد|[%٪]", "percent", "1", None),
    (r"دانش\s*آموز", "person", "1", "pupil"),
    (r"دانشجو", "person", "1", "student"),
    (r"استاد", "person", "1", "professor"),
    (r"نفر", "person", "1", None),
    (r"مگاوات|MW", "watt", "1000000", None),
    (r"وات|W", "watt", "1", None),
    (r"درجه\s+(?:سانتیگراد|سلسیوس)|°C", "celsius", "1", None),
    (r"دقیقه", "minute", "1", None),
    (r"ساعت", "minute", "60", None),
]
_DATE = re.compile(r"(?<![\w/-])(\d{4})([/\-])(\d{1,2})\2(\d{1,2})(?![\w/-])")
_NAMED_DATE = re.compile(
    r"(?<!\w)(\d{1,2})\s+(" + "|".join(MONTHS) + r")(?:\s+(\d{4}))?(?!\w)"
)
_TIME = re.compile(r"(?<![\w:])(\d{1,2}):(\d{2})(?::(\d{2}))?(?![\w:])")
_NUMBER = re.compile(r"(?<![\w.])[+-]?\d+(?:[.,٫٬/]\d+)*(?!\d)")
_RANGE = re.compile(r"(?<!\w)\d+\s*(?:-|تا)\s*\d+(?!\w)")
_ENTITY = re.compile(
    r"(?<!\w)(شرکت|دانشگاه|بیمارستان|تیم|طرح|پروژه|نشست|جلسه|رویداد|سامانه|نمایش|کتاب|جشنواره|دکتر|آقای|خانم)"
    r'\s*(?:(?P<angle>«)|")(?P<name>[^»"\n]{1,80})(?(angle)»|")'
)
_NEGATION = re.compile(
    r"(?<!\w)(?:نمی\s*[^\W\d_]+|نیستند|نیست|نبودند|نبود|ندارد|نداشت|نکردند|نکرد|نشد|نشده|نه|هرگز|بدون|هیچ|عدم|تکذیب)(?!\w)"
)
_IGNORE = re.compile(r"(?:https?://|www\.)\S+|[\w.+-]+@[\w.-]+")


@dataclass(frozen=True)
class EvidenceSpan:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class EventFeature:
    feature_type: str
    normalized: dict[str, str | None]
    evidence: EvidenceSpan
    clause: EvidenceSpan
    context_template: str
    qualifiers: tuple[str, ...]
    extraction_status: str
    rule: str


@dataclass(frozen=True)
class NewsFeatures:
    original_text: str
    features: tuple[EventFeature, ...]
    warnings: tuple[str, ...]
    rules_version: str = RULES_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalized_view(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Normalize grapheme-like base/mark clusters, retaining a raw-offset map."""
    output, offsets = [], []
    index = 0
    while index < len(text):
        end = index + 1
        while end < len(text) and unicodedata.combining(text[end]):
            end += 1
        cluster = unicodedata.normalize("NFKC", text[index:end])
        cluster = cluster.translate(ARABIC_TO_PERSIAN).translate(DIGITS)
        for character in cluster:
            category = unicodedata.category(character)
            if character == "ـ" or "\u064b" <= character <= "\u0652":
                continue
            if character.isspace() or character in {"\u200b", "\u200c"}:
                character = (
                    "\n" if character in {"\n", "\r", "\u2028", "\u2029"} else " "
                )
            elif category in {"Cf", "Cc", "Cs"}:
                continue
            output.append(character)
            offsets.append((index, end))
        index = end
    return "".join(output), offsets


def _plain(value: str) -> str:
    return " ".join(normalized_view(value)[0].split())


def _decimal(value: str) -> str | None:
    groups = value.replace("٬", ",").replace("٫", ".")
    if not re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", groups):
        return None
    try:
        number = Decimal(groups.replace(",", ""))
        return _fixed_decimal(number)
    except InvalidOperation:
        return None


def _fixed_decimal(value: Decimal) -> str:
    # Decimal.normalize() rounds to the ambient context; fixed formatting does not.
    result = format(value, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return "0" if value == 0 else result


def _clause_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    boundaries = [0]
    for match in re.finditer(r"[\n؛!?؟.]", text):
        position = match.start()
        if (
            text[position] == "."
            and position
            and position + 1 < len(text)
            and text[position - 1].isdigit()
            and text[position + 1].isdigit()
        ):
            continue
        boundaries.append(position + 1)
    boundaries.append(len(text))
    return max(value for value in boundaries if value <= start), min(
        value for value in boundaries if value >= end
    )


def _qualifiers(clause: str) -> tuple[str, ...]:
    result = []
    if re.search(
        r"ابتدا|سپس|اصلاح|تازه|پیشین|قبلی|جدید|به روز|افزایش|کاهش|رسید", clause
    ):
        result.append("update_or_change")
    if re.search(
        r"حدود|تقریبا|حداقل|حداکثر|بیش از|کمتر از|دست کم|احتمال|ممکن|شاید|"
        r"برآورد|پیش بینی|اگر|در صورت|آیا|مگر|قرار است|تکذیب|نادرست|[؟?]",
        clause,
    ):
        result.append("uncertain_or_bounded")
    if re.search(r"به گفته|گفت|مدعی|ادعا|گزارش|اعلام", clause):
        result.append("attributed_or_reported")
    return tuple(result)


class EventFeatureExtractor:
    def __init__(self, *, locations: Mapping[str, str] | None = None) -> None:
        self.locations = (
            dict(locations)
            if locations is not None
            else {name: name for name in LOCATIONS}
        )
        if any(
            not isinstance(key, str)
            or not _plain(key)
            or not isinstance(value, str)
            or not value.strip()
            for key, value in self.locations.items()
        ):
            raise ValueError(
                "Location aliases and canonical names must be nonempty strings."
            )

    def extract(self, text: str | None) -> NewsFeatures:
        if text is None:
            text = ""
        if not isinstance(text, str):
            raise TypeError("News text must be a string or None.")
        view, offsets = normalized_view(text)
        features, warnings = [], []
        occupied = [(match.start(), match.end()) for match in _IGNORE.finditer(view)]

        def overlaps(start: int, end: int) -> bool:
            return any(start < right and end > left for left, right in occupied)

        def span(start: int, end: int) -> EvidenceSpan:
            left, right = offsets[start][0], offsets[end - 1][1]
            return EvidenceSpan(left, right, text[left:right])

        def add(
            kind: str,
            start: int,
            end: int,
            values: dict[str, str | None],
            rule: str,
            status: str = "explicit",
        ) -> None:
            left, right = _clause_bounds(view, start, end)
            template = " ".join(
                (view[left:start] + f" <{kind}> " + view[end:right]).split()
            )
            features.append(
                EventFeature(
                    kind,
                    values,
                    span(start, end),
                    span(left, right),
                    template,
                    _qualifiers(view[left:right]),
                    status,
                    rule,
                )
            )

        for match in _ENTITY.finditer(view):
            if not overlaps(*match.span()):
                name = " ".join(match["name"].split())
                if not name:
                    continue
                entity_type = (
                    "person" if match[1] in {"دکتر", "آقای", "خانم"} else "quoted_name"
                )
                add(
                    "entity",
                    *match.span("name"),
                    {
                        "value": name,
                        "entity_type": entity_type,
                        "label": match[1],
                    },
                    "explicit_labeled_quoted_name",
                )
                occupied.append(match.span("name"))
        for match in _DATE.finditer(view):
            if overlaps(*match.span()):
                continue
            year, month, day = int(match[1]), int(match[3]), int(match[4])
            if year == 0 or not 1 <= month <= 12 or not 1 <= day <= 31:
                warnings.append("Invalid date-shaped span ignored.")
                occupied.append(match.span())
                continue
            add(
                "date",
                *match.span(),
                {
                    "value": f"{year:04}-{month:02}-{day:02}",
                    "calendar": "unspecified",
                    "year": str(year),
                    "month": str(month),
                    "day": str(day),
                },
                "year_first_date_components",
            )
            occupied.append(match.span())
        for match in _NAMED_DATE.finditer(view):
            if overlaps(*match.span()):
                continue
            month, day = MONTHS[match[2]], int(match[1])
            if match[3] == "0000" or not 1 <= day <= (31 if month <= 6 else 30):
                warnings.append("Invalid Persian named-month date ignored.")
                occupied.append(match.span())
                continue
            year = match[3]
            add(
                "date",
                *match.span(),
                {
                    "value": f"{year or '----'}-{month:02}-{day:02}",
                    "calendar": "solar_hijri",
                    "year": year,
                    "month": str(month),
                    "day": str(day),
                },
                "named_persian_month_no_calendar_conversion",
            )
            occupied.append(match.span())
        for match in _TIME.finditer(view):
            if overlaps(*match.span()):
                continue
            hour, minute, second = int(match[1]), int(match[2]), match[3]
            if hour > 23 or minute > 59 or second is not None and int(second) > 59:
                warnings.append("Invalid clock-shaped span ignored.")
                occupied.append(match.span())
                continue
            tail = view[match.end() : match.end() + 24]
            zone_match = re.match(r"\s*(UTC|GMT|به وقت تهران)(?![\w+-])", tail, re.I)
            unresolved_offset = re.match(
                r"\s*(?:UTC|GMT)[+-]\d{1,2}(?::\d{2})?(?![\w:])", tail, re.I
            )
            timezone = (
                ("Tehran_local" if zone_match[1] == "به وقت تهران" else "UTC")
                if zone_match
                else None
            )
            suffix = zone_match or unresolved_offset
            end = match.end() + (suffix.end() if suffix else 0)
            if unresolved_offset:
                warnings.append(
                    "Timezone offset retained as evidence but left unresolved."
                )
            value = f"{hour:02}:{minute:02}" + (
                f":{int(second):02}" if second is not None else ""
            )
            add(
                "time",
                match.start(),
                end,
                {
                    "value": value,
                    "timezone": timezone,
                    "precision": "second" if second is not None else "minute",
                },
                "explicit_clock_no_timezone_conversion",
            )
            occupied.append((match.start(), end))
        for match in _RANGE.finditer(view):
            if not overlaps(*match.span()):
                add(
                    "number",
                    *match.span(),
                    {
                        "value": None,
                        "unit": None,
                        "role": None,
                        "notation": match.group(),
                    },
                    "ambiguous_range_or_subtraction",
                    "ambiguous",
                )
                occupied.append(match.span())
        for match in _NUMBER.finditer(view):
            if overlaps(*match.span()):
                continue
            value, end = _decimal(match.group()), match.end()
            magnitude = re.match(r"\s*(هزار|میلیون|میلیارد)(?!\w)", view[end:])
            scale = Decimal(1)
            if magnitude:
                scale = Decimal(
                    {"هزار": 1000, "میلیون": 1000000, "میلیارد": 1000000000}[
                        magnitude[1]
                    ]
                )
                end += magnitude.end()
                if re.match(r"\s*(هزار|میلیون|میلیارد)(?!\w)", view[end:]):
                    value = None
            unit, role, factor = None, None, Decimal(1)
            for pattern, canonical, multiplier, quantity_role in UNIT_RULES:
                unit_match = re.match(r"\s*(?:" + pattern + r")(?!\w)", view[end:])
                if unit_match:
                    unit, role, factor = canonical, quantity_role, Decimal(multiplier)
                    end += unit_match.end()
                    break
            unsupported_compound = None
            if unit is not None:
                unsupported_compound = re.match(
                    r"\s*(?:بر\s+|در\s+|/\s*)"
                    r"(?:ساعت|دقیقه|ثانیه|روز|سال|هکتار|متر|کیلومتر|کیلوگرم|s|h|kg|m)"
                    r"(?!\w)",
                    view[end:],
                )
                if unsupported_compound:
                    end += unsupported_compound.end()
                    unit, role, factor = None, None, Decimal(1)
                    warnings.append("Unsupported compound unit left unresolved.")
            if unit is None and end < len(view) and view[end].isalpha():
                continue  # Do not split unsupported alphanumeric identifiers.
            with localcontext() as decimal_context:
                decimal_context.prec = len(value or "") + 32
                normalized_value = (
                    _fixed_decimal(Decimal(value) * scale * factor)
                    if value is not None
                    else None
                )
            add(
                "number",
                match.start(),
                end,
                {
                    "value": normalized_value,
                    "unit": unit,
                    "role": role,
                    "written_value": value,
                    "magnitude": str(scale),
                },
                "digit_quantity_with_explicit_unit",
                "explicit"
                if value is not None and not unsupported_compound
                else "ambiguous",
            )
        for alias, canonical in sorted(
            self.locations.items(), key=lambda item: (-len(item[0]), item[0])
        ):
            pattern = re.escape(_plain(alias)).replace(r"\ ", r"\s+")
            for match in re.finditer(r"(?<!\w)" + pattern + r"(?!\w)", view):
                if overlaps(*match.span()):
                    continue
                cue = re.search(
                    r"(?<!\w)(در|از|به|شهر|استان|شهرستان)\s+$", view[: match.start()]
                )
                if cue:
                    add(
                        "location",
                        *match.span(),
                        {"value": canonical, "role": cue[1]},
                        "gazetteer_with_explicit_location_cue",
                    )
                    occupied.append(match.span())
        for predicate, pattern in PREDICATES.items():
            for match in re.finditer(r"(?<!\w)(?:" + pattern + r")(?!\w)", view):
                if not overlaps(*match.span()):
                    negative = bool(re.search(r"(?<!\w)ن", match.group()))
                    add(
                        "assertion",
                        *match.span(),
                        {
                            "value": "negated" if negative else "affirmed",
                            "predicate": predicate,
                        },
                        "bounded_explicit_predicate_polarity",
                    )
        for match in _NEGATION.finditer(view):
            if not overlaps(*match.span()):
                ambiguous = match.group() == "نه" and bool(
                    re.match(r"\s+تنها", view[match.end() :])
                )
                add(
                    "negation",
                    *match.span(),
                    {"value": " ".join(match.group().split()), "scope": "unknown"},
                    "negation_cue_not_full_scope_analysis",
                    "ambiguous" if ambiguous else "explicit",
                )
        if not view.strip():
            warnings.append("Empty or formatting-only text; no event facts inferred.")
        return NewsFeatures(
            text,
            tuple(
                sorted(
                    features,
                    key=lambda feature: (feature.evidence.start, feature.feature_type),
                )
            ),
            tuple(warnings),
        )


def extract_event_features(text: str | None) -> NewsFeatures:
    return EventFeatureExtractor().extract(text)
