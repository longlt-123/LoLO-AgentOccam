"""Small, deliberately bounded grammar for observation-backed early stopping.

Unparsed conditions never become a wildcard witness predicate. They fall back to
coverage checks. Dates use the US convention of the Magento Shopping benchmark.
"""

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re


STATUS = {
    "complete": "complete", "completed": "complete", "fulfilled": "complete",
    "canceled": "canceled", "cancelled": "canceled", "pending": "pending",
    "processing": "processing", "on hold": "on hold", "holded": "on hold",
    "closed": "closed",
}
STATUS_PATTERN = "|".join(STATUS)
NUMBERS = {"a": 1, "an": 1, "any": 1, "one": 1, "two": 2, "three": 3,
           "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
           "nine": 9, "ten": 10}


def parse_date(value):
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    return None


def date_window(text, reference_date=None):
    month = re.fullmatch(r"(?:in|during) ([a-z]+) (\d{4})", text)
    if month:
        months = {name.lower(): i for i, name in enumerate(calendar.month_name) if i}
        number = months.get(month[1])
        year = int(month[2])
        if number and 1 <= year <= 9999:
            return date(year, number, 1), date(year, number, calendar.monthrange(year, number)[1])
    interval = re.fullmatch(r"from ([\d/-]+) to ([\d/-]+)", text)
    if interval:
        start, end = parse_date(interval[1]), parse_date(interval[2])
        if start and end and start <= end:
            return start, end
    relative = re.fullmatch(
        r"(?:over|in|during) the past (?:(\d+|" + "|".join(NUMBERS) + r") )?(day|week|month|year)s?", text)
    if relative and reference_date:
        token = relative[1]
        amount = 1 if token is None else int(token) if token.isdigit() else NUMBERS[token]
        if amount <= 0:
            return None
        unit = relative[2]
        try:
            if unit in {"day", "week"}:
                start = reference_date - timedelta(days=amount * (7 if unit == "week" else 1))
            else:
                months_back = amount * (12 if unit == "year" else 1)
                year, month_zero = divmod(reference_date.year * 12 + reference_date.month - 1 - months_back, 12)
                if not 1 <= year <= 9999:
                    return None
                month = month_zero + 1
                start = date(year, month, min(reference_date.day, calendar.monthrange(year, month)[1]))
            return start, reference_date
        except (ValueError, OverflowError):
            return None
    return None


@dataclass(frozen=True)
class OrderRequirement:
    kind: str
    understood: bool = False
    count: int = 1
    status: str | None = None
    start: date | None = None
    end: date | None = None
    direction: str | None = None
    target_ids: tuple = ()
    reference_date: date | None = None
    outputs: tuple = ()

    def snapshot(self):
        return {"kind": self.kind, "understood": self.understood, "status": self.status,
                "date_range": [self.start.isoformat(), self.end.isoformat()] if self.start else None,
                "reference_date": self.reference_date.isoformat() if self.reference_date else None,
                "outputs": list(self.outputs)}

    def matches(self, row):
        if not self.understood or len(row) != 4:
            return False
        if self.target_ids and row[0] not in self.target_ids:
            return False
        if self.status and STATUS.get(row[3].lower().strip()) != self.status:
            return False
        if self.start:
            observed_date = parse_date(row[1])
            if not observed_date or not self.start <= observed_date <= self.end:
                return False
        return True


def criteria_requirement(kind, criteria, reference_date=None, **kwargs):
    # Full match is intentional: "containing food", "over $100", unanchored dates,
    # negation, and extra subtasks must not silently drop out of the predicate.
    pattern = (rf"(?:my )?(?:(?P<before>{STATUS_PATTERN}) )?(?:orders?|purchases?)"
               rf"(?: (?:that (?:are|were)|with (?:the )?status) (?P<after>{STATUS_PATTERN}))?"
               r"(?: (?:placed )?(?P<dates>(?:in|during|from|over) .+))?")
    match = re.fullmatch(pattern, criteria)
    if not match:
        return OrderRequirement(kind)
    before, after = match["before"], match["after"]
    if before and after and STATUS[before] != STATUS[after]:
        return OrderRequirement(kind)
    window = date_window(match["dates"], reference_date) if match["dates"] else None
    if match["dates"] and not window:
        return OrderRequirement(kind)
    return OrderRequirement(kind, understood=True,
                            status=STATUS.get(before or after),
                            start=window[0] if window else None,
                            end=window[1] if window else None, reference_date=reference_date, **kwargs)


def parse_requirement(objective):
    text = re.sub(r"\s+", " ", objective.lower()).strip().rstrip("?.!")
    text = re.sub(r"^please ", "", text)
    reference_date = None
    anchored = re.fullmatch(r"today is ([\d/-]+)\.\s*(.+)", text)
    if anchored:
        reference_date = parse_date(anchored[1])
        if reference_date is None:
            return OrderRequirement("unknown")
        text = anchored[2]
    # Count + spending over the SAME period is a single aggregate scope, not an
    # arbitrary compound task. No evaluator answer or machine clock is used.
    aggregate_pair = re.fullmatch(
        r"(?:tell me )?how many (.+?) i have ((?:over|in|during) the past .+?),? "
        r"and the total (?:amount of money|amount) i spent", text)
    if aggregate_pair:
        return criteria_requirement("aggregate", aggregate_pair[1] + " " + aggregate_pair[2],
                                    reference_date=reference_date, outputs=("count", "total"))
    exists = re.fullmatch(
        r"(?:do i have|have i placed|have i made|are there|is there) (?:any|an?|at least one) (.+)", text)
    if exists:
        return criteria_requirement("existence", exists[1], reference_date=reference_date)
    sample = re.fullmatch(
        r"(?:find(?: me)?|show(?: me)?|list|give me) (\d+|" + "|".join(NUMBERS) + r") (.+)", text)
    if sample:
        count = int(sample[1]) if sample[1].isdigit() else NUMBERS[sample[1]]
        if count > 0:
            return criteria_requirement("sample", sample[2], count=count, reference_date=reference_date)
    identity = re.fullmatch(
        r"(?:what is|tell me) (?:the )?(?:status|date|total|total cost|order total) of (?:my )?order (\d{6,})", text)
    if identity:
        return OrderRequirement("lookup", understood=True, target_ids=(identity[1],))
    latest = re.fullmatch(
        r"(?:what is|tell me|get) (?:the )?(?:status|date|total cost|order number) of (?:my |the )?"
        r"(latest|most recent|earliest|first) (.+)", text)
    if latest:
        direction = "descending" if latest[1] in {"latest", "most recent"} else "ascending"
        return criteria_requirement("comparison", latest[2], direction=direction, reference_date=reference_date)
    for kind, pattern in (
        ("aggregate", r"how much (?:did i spend|i spent) (?:on )?(.+)"),
        ("aggregate", r"how many (.+) do i have"),
        ("aggregate", r"(?:what is|tell me) the (?:total|total cost|sum) of (.+)"),
        ("enumeration", r"(?:list|show(?: me)?) all (.+)"),
    ):
        match = re.fullmatch(pattern, text)
        if match:
            return criteria_requirement(kind, match[1], reference_date=reference_date)
    return OrderRequirement("unknown")
