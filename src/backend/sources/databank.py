import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from ..models import Candidate

DIRECTORY_URL = "https://www.databank.com/data-centers/"
PARSER_VERSION = "1"
LABELS = {
    "it square feet": "it_area_sqft",
    "it square footage": "it_area_sqft",
    "critical it load": "critical_it_mw",
    "onsite carriers": "onsite_carriers",
    "total data centers": "facility_count",
}
CODE = re.compile(r"\(([A-Z]{2,5}\d{1,3})\)")


def clean(text: str) -> str:
    return " ".join(text.split())


def canonical_url(href: str, base: str = DIRECTORY_URL) -> str:
    parts = urlsplit(urljoin(base, href))
    if parts.hostname not in {"www.databank.com", "databank.com"}:
        raise ValueError(f"External source link: {href}")
    if parts.scheme not in {"https", "http"} or not parts.path.startswith(
        "/data-centers/"
    ):
        raise ValueError(f"Unexpected source link: {href}")
    return urlunsplit(
        ("https", "www.databank.com", parts.path.rstrip("/") + "/", "", "")
    )


def discover_markets(content: bytes) -> list[str]:
    soup = BeautifulSoup(content, "html.parser")
    urls = set()
    for link in soup.select('a[href*="/data-centers/"]'):
        try:
            url = canonical_url(link["href"])
        except ValueError:
            continue
        parts = urlsplit(url).path.strip("/").split("/")
        if len(parts) == 2 and parts[1] not in {"edge-strategy", "data-center-design"}:
            urls.add(url)
    return sorted(urls)


def metric_elements(elements, url: str, level: str, origin: str) -> list[dict]:
    observations = []
    for element in elements:
        strong = element.find("strong")
        if strong is None:
            continue
        raw = clean(strong.get_text(" ", strip=True))
        text = clean(element.get_text(" ", strip=True))
        label = clean(text.removeprefix(raw))
        observations.append(
            {
                "source_url": url,
                "record_level": level,
                "origin": origin,
                "field": LABELS.get(label.lower()),
                "raw_value": raw,
                "raw_label": label,
            }
        )
    return observations


def metric_values(observations: list[dict]) -> dict[str, str]:
    values = {}
    for observation in observations:
        if observation["field"]:
            values.setdefault(observation["field"], observation["raw_value"])
    return values


def parse_market(content: bytes, url: str) -> tuple[list[Candidate], list[dict]]:
    soup = BeautifulSoup(content, "html.parser")
    market = urlsplit(url).path.strip("/").split("/")[-1]
    candidates = []
    observations = []
    # Count every card, including malformed cards; rejection happens downstream.
    for card in soup.select(".c-data-center-card"):
        title = card.select_one(".c-data-center-card__title")
        link = title.find("a") if title else None
        name = clean(title.get_text(" ", strip=True)) if title else ""
        code = CODE.search(name)
        level = (
            "campus"
            if "campus" in name.lower()
            and "data center" not in name.lower()
            and not code
            else "facility"
        )
        try:
            detail_url = (
                canonical_url(link["href"], url) if link and link.get("href") else ""
            )
        except ValueError:
            detail_url = ""
        address = card.select_one(".c-data-center-card__location")
        metrics = metric_elements(
            card.select(".c-data-center-card__data > div"), url, level, "card"
        )
        for observation in metrics:
            observation["facility_url"] = detail_url
            observation["facility_code"] = code.group(1) if code else None
        observations.extend(metrics)
        candidates.append(
            Candidate(
                name=name,
                url=detail_url,
                market=market,
                market_url=url,
                code=code.group(1) if code else None,
                address=clean(address.get_text(" ", strip=True)) if address else None,
                metrics=metric_values(metrics),
                record_level=level,
            )
        )
    observations.extend(parse_aggregates(soup, url, "market"))
    return candidates, observations


def parse_aggregates(soup: BeautifulSoup, url: str, level: str) -> list[dict]:
    # Headline li/strong stats are separate from facility cards and detail specs.
    elements = [
        li
        for li in soup.select("li")
        if li.find("strong", recursive=False)
        and not li.find_parent(class_="c-data-center-card")
        and not li.find_parent(class_="c-figure-stats")
        and not li.find_parent(class_="c-info-table__stats")
    ]
    observations = [
        o for o in metric_elements(elements, url, level, "headline") if o["field"]
    ]
    for stat in soup.select(".c-stat, .c-figure-map__stat"):
        value = stat.select_one(".c-stat__value, .c-figure-map__stat-value")
        label = stat.select_one(".c-stat__text, .c-figure-map__stat-label")
        if value and label and LABELS.get(clean(label.get_text()).lower()):
            observations.append(
                {
                    "source_url": url,
                    "record_level": "campus"
                    if "c-figure-map__stat" in stat.get("class", [])
                    else level,
                    "origin": "headline",
                    "field": LABELS[clean(label.get_text()).lower()],
                    "raw_value": clean(value.get_text(" ", strip=True)),
                    "raw_label": clean(label.get_text(" ", strip=True)),
                }
            )
    # Keep explicitly stated market FAQ totals as claims, not inferred facility values.
    for text in soup.select(".c-list__text"):
        value = clean(text.get_text(" ", strip=True))
        if not re.search(r"\btotal\b", value, re.I):
            continue
        patterns = {
            "critical_it_mw": r"([\d,.]+\s*(?:MW|kW|GW))\s+of\s+critical\s+IT",
            "it_area_sqft": r"([\d,]+)\s+(?:raised\s+)?square feet",
        }
        for field, pattern in patterns.items():
            for match in re.finditer(pattern, value, re.I):
                observations.append(
                    {
                        "source_url": url,
                        "record_level": level,
                        "origin": "faq",
                        "field": field,
                        "raw_value": match.group(1),
                        "raw_label": "Explicit total in FAQ",
                    }
                )
    return observations


def parse_directory(content: bytes) -> list[dict]:
    return parse_aggregates(
        BeautifulSoup(content, "html.parser"), DIRECTORY_URL, "portfolio"
    )


def parse_detail(content: bytes, url: str) -> tuple[str, dict[str, str], list[dict]]:
    soup = BeautifulSoup(content, "html.parser")
    title = soup.select_one("h1.c-hero__title") or soup.find("h1")
    name = clean(title.get_text(" ", strip=True)) if isinstance(title, Tag) else ""
    primary = metric_elements(
        soup.select(".c-figure-stats li"), url, "facility", "detail_main"
    )
    secondary = metric_elements(
        soup.select(".c-info-table__stats li"), url, "facility", "detail_specs"
    )
    # Main figures win over specification-table repeats; preserve both for comparison.
    return name, metric_values(primary + secondary), primary + secondary
