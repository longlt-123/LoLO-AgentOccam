"""Observation-backed stopping rules for shopping order queries.

This checks evidence coverage, not the truth/arithmetic of the final answer.
Records come from browser observations; sort order may also come from an explicit,
installation-specific source contract. Model notes and reasons never count.
No model calls or browser dependencies are needed.
"""

from dataclasses import dataclass, field
import math
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from .stop_requirements import OrderRequirement, parse_date, parse_requirement
from .stop_policy import resolve_stop_mode


PAGE_KEYS = {"p", "page", "limit", "page_size"}
SORT_KEYS = {"sort", "dir", "order"}
REQUIREMENTS = {"auto", "aggregate", "enumeration", "comparison", "lookup", "existence", "sample"}
STOP = re.compile(r"(?:^|\n)\s*stop(?=\s|\[|$)[ \t]*\[?", re.I)
NEGATIVE = re.compile(
    r"\b(?:no|none|zero|nothing|never|not found|not exist|don't have|do not have|"
    r"haven't|have not|couldn't|could not|N/A)\b|"
    r"(?<![\w.])\$?0(?:\.0+)?(?!\d|\.\d)", re.I
)


def option(config, name, default):
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)


def classify_request(objective):
    """Conservative English heuristics for the repository's WebArena intents."""
    if re.search(r"\b(how many|how much|total|sum|count|spent|average)\b", objective, re.I):
        return "aggregate"
    if re.search(r"\b(all|every|list)\b", objective, re.I):
        return "enumeration"
    if re.search(r"\b(most|least|highest|lowest|largest|smallest|cheapest|latest|earliest|first|last)\b", objective, re.I):
        return "comparison"
    return "lookup"


def scope_key(url):
    """Pages/sizes share coverage; different filters and sort orders never do."""
    parts = urlsplit(url)
    query = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in PAGE_KEYS)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), urlencode(query), ""))


def order_rows(text):
    """Read the concise Orders table, excluding sidebars and Recent Orders."""
    rows = []
    in_table = False
    table_indent = -1
    for line in text.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if re.match(r"table(?:\s+\[\d+\])?\s+['\"]Orders['\"]", stripped):
            in_table, table_indent = True, indent
            continue
        if in_table and stripped and indent <= table_indent:
            in_table = False
        if not in_table:
            continue

        match = re.search(r"\brow\s+(?:\[\d+\]\s+)?['\"]?\|(.+)\|", stripped)
        if not match:
            continue

        cells = [cell.strip() for cell in match.group(1).split("|")]
        if len(cells) >= 4 and re.fullmatch(r"\d+", cells[0]):
            # Ignore action links and their unstable DOM IDs.
            rows.append(tuple(cells[:4]))
    return rows


@dataclass
class Coverage:
    url: str
    total: int | None = None
    positions: dict = field(default_factory=dict)
    rows: dict = field(default_factory=dict)
    pages: set = field(default_factory=set)
    page_count: int | None = None
    issue: str = "No explicit item count has been observed."
    sort_directions: dict = field(default_factory=dict)
    sort_sources: dict = field(default_factory=dict)

    @property
    def complete(self):
        return (
            self.total is not None
            and not self.issue
            and len(self.positions) == self.total
            and len(set(self.positions.values())) == self.total
            and all(1 <= i <= self.total for i in self.positions)
        )

    def snapshot(self):
        return {
            "url": self.url, "total_items": self.total,
            "observed_items": len(set(self.positions.values())),
            "visited_pages": sorted(self.pages), "total_pages": self.page_count,
            "complete": self.complete, "issue": self.issue,
            "sort_sources": sorted(set(self.sort_sources.values()) - {""}),
        }

    def ordered_prefix(self):
        """Return a contiguous prefix with a declared or source-verified date order.

        Neither a URL sort parameter nor locally monotonic dates establish the
        ordering of unread records. Every contributing observation needs metadata
        collected from aria-sort or an explicitly configured installation contract.
        """
        if self.issue:
            return None
        indexes = []
        while len(indexes) + 1 in self.positions:
            indexes.append(len(indexes) + 1)
        directions = {self.sort_directions.get(i) for i in indexes}
        if not indexes or len(directions) != 1 or None in directions:
            return None
        direction = directions.pop()
        rows = [self.rows[self.positions[i]] for i in indexes]
        dates = [parse_date(row[1]) for row in rows]
        if any(value is None for value in dates):
            return None
        if dates != sorted(dates, reverse=direction == "descending"):
            return None
        return direction, rows, dates


class StopGuard:
    def __init__(self, objective, config=None, sites=None):
        self.enabled = resolve_stop_mode(config) == "evidence_gated"
        self.requirement = option(config, "requirement", "auto")

        if self.requirement not in REQUIREMENTS:
            raise ValueError(f"Unknown stop_guard.requirement: {self.requirement}")
        
        self.objective = objective
        parsed = parse_requirement(objective)
        self.request_type = ((parsed.kind if parsed.kind != "unknown" else classify_request(objective))
                             if self.requirement == "auto" else self.requirement)
        self.evidence_requirement = (parsed if parsed.kind == self.request_type
                                     else OrderRequirement(self.request_type))
        self.sort_contract = option(config, "order_history_sort", None)
        if self.sort_contract:
            origin = option(self.sort_contract, "origin", "")
            parts = urlsplit(origin)
            if (parts.scheme not in {"http", "https"} or not parts.netloc
                    or parts.path not in {"", "/"} or parts.query or parts.fragment
                    or option(self.sort_contract, "direction", "") != "descending"
                    or option(self.sort_contract, "source", "") != "magento_history_source"
                    or not option(self.sort_contract, "reference", "")):
                raise ValueError("order_history_sort needs an exact origin, descending Magento source contract, and reference")
        order_query = re.search(r"\b(orders?|purchases?|spent)\b", objective, re.I)
        mutation = re.search(r"\b(cancel|place|reorder|delete|buy|submit|change|update)\b", objective, re.I)

        self.supported = bool(order_query and not mutation and (sites is None or "shopping" in sites))
        self.scopes = {}
        self.feedback = ""
        self.rejections = 0

    def observe(self, url, observation):
        before = self._evidence_state()
        self._observe(url, observation)
        if before != self._evidence_state():
            # Keep refusals for an unchanged observation, but never present an
            # outdated missing-evidence message after new facts arrive.
            self.feedback = ""

    def _evidence_state(self):
        return {key: (dict(c.rows), dict(c.positions), c.total, c.issue, dict(c.sort_directions), dict(c.sort_sources))
                for key, c in self.scopes.items()}

    def configured_sort(self, url):
        """Apply only the verified installation's default order, never a guess
        from the current page. Explicit sort queries disable this fallback.
        """
        if not self.sort_contract:
            return {}
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if (origin != option(self.sort_contract, "origin", "").rstrip("/")
                or parts.path.rstrip("/") != "/sales/order/history"
                or any(k not in PAGE_KEYS for k, _ in parse_qsl(parts.query, keep_blank_values=True))):
            return {}
        return {"field": "date", "direction": "descending", "source": "magento_history_source",
                "reference": option(self.sort_contract, "reference", "")}

    def _observe(self, url, observation):
        if not self.enabled or not self.supported:
            return
        
        text = observation.get("text", "") if isinstance(observation, dict) else observation
        if not isinstance(text, str):
            return
        parts = urlsplit(url)
        # Do not confuse an account dashboard/sidebar with the full order history.
        if parts.path.rstrip("/") != "/sales/order/history":
            return
        
        # A complete arbitrary filter does not prove the user's requested scope.
        # Filter semantics need a site adapter before they can be trusted.
        if any(k not in PAGE_KEYS | SORT_KEYS for k, _ in parse_qsl(parts.query, keep_blank_values=True)):
            return
        
        key = scope_key(url)
        coverage = self.scopes.setdefault(key, Coverage(key))
        rows = order_rows(text)
        match = re.search(r"Items\s+([\d,]+)\s+(?:to|-)\s+([\d,]+)\s+of\s+([\d,]+)\s+total", text, re.I)
        empty = re.search(r"\bYou have placed no orders\b", text, re.I)
        single = re.search(r"\btext\s+['\"]([\d,]+)\s+Items?['\"]", text, re.I)
        if match:
            start, end, total = (int(v.replace(",", "")) for v in match.groups())
        elif empty and not rows:
            start, end, total = 1, 0, 0
        elif single:
            total = int(single.group(1).replace(",", ""))
            start, end = 1, total
        else:
            coverage.rows.update({row[0]: row for row in rows})
            coverage.issue = "Order rows or pagination metadata are missing; inspect the complete table."
            return

        # A changed result count invalidates earlier positional coverage.
        if coverage.total is not None and coverage.total != total:
            coverage = self.scopes[key] = Coverage(key)
        coverage.total = total
        coverage.rows.update({row[0]: row for row in rows})

        if not (total == 0 and end == 0) and not (1 <= start <= end <= total):
            coverage.issue = "Invalid item range in the observation."
            return
        if len(rows) != end - start + 1 or len({row[0] for row in rows}) != len(rows):
            coverage.issue = "The visible order rows do not cover the displayed item range (possibly truncated)."
            return
        
        # Never infer visited rows from a clicked page or a URL alone.
        incoming = {i: row[0] for i, row in enumerate(rows, start)}
        changed = any(i in coverage.positions and coverage.positions[i] != rid for i, rid in incoming.items())
        relocated = any(rid == old_rid and i != old_i
                        for i, rid in incoming.items() for old_i, old_rid in coverage.positions.items())
        if changed or relocated:
            coverage = self.scopes[key] = Coverage(key, total=total)
            coverage.rows.update({row[0]: row for row in rows})

        coverage.positions.update(incoming)
        sort_metadata = observation.get("order_history_sort", {}) if isinstance(observation, dict) else {}
        if not sort_metadata:
            sort_metadata = self.configured_sort(url)
        direction = sort_metadata.get("direction") if isinstance(sort_metadata, dict) else None
        source = sort_metadata.get("source") if isinstance(sort_metadata, dict) else None
        trusted_source = (source == "orders_table_aria_sort" or
                          (source == "magento_history_source" and sort_metadata == self.configured_sort(url)))
        verified_sort = (direction if direction in {"ascending", "descending"}
                         and sort_metadata.get("field") == "date"
                         and trusted_source else None)
        coverage.sort_directions.update({i: verified_sort for i in incoming})
        provenance = (source + ": " + sort_metadata.get("reference", "observed DOM")) if verified_sort else ""
        coverage.sort_sources.update({i: provenance for i in incoming})
        coverage.issue = ""

        page_match = re.search(r"currently reading page['\"]?\s*\n\s*text\s+['\"](\d+)", text, re.I)
        page = int(page_match.group(1)) if page_match else None
        if page is None and start == 1:
            page = 1
        if page is not None:
            coverage.pages.add(page)
        page_links = [int(p) for p in re.findall(r"\bPage (\d+)['\"]", text)]
        if start == 1 and rows:
            coverage.page_count = math.ceil(total / len(rows))
        elif page_links:
            coverage.page_count = max(page_links + [page or 1, coverage.page_count or 1])

    def snapshot(self):
        return [coverage.snapshot() for coverage in self.scopes.values()]

    def early_evidence(self, answer):
        """Return an auditable proof of sufficiency, or None; never trust a claim
        such as 'I checked everything' as evidence.
        """
        requirement = self.evidence_requirement
        if not requirement.understood or not answer:
            return None
        cited_ids = set(re.findall(r"\b\d{6,}\b", answer))
        for coverage in self.scopes.values():
            matching = {rid: row for rid, row in coverage.rows.items() if requirement.matches(row)}
            positive = not NEGATIVE.search(answer)
            if requirement.kind == "lookup" and positive and set(requirement.target_ids) <= matching.keys():
                return {"reason": "observed_target_order", "witness_ids": list(requirement.target_ids)}
            if (requirement.kind == "existence" and positive and matching
                    and (not cited_ids or cited_ids <= matching.keys())
                    and (re.match(r"\s*yes\b", answer, re.I) or cited_ids)):
                return {"reason": "matching_witness", "witness_ids": [next(iter(matching))]}
            if (requirement.kind == "sample" and positive and len(cited_ids) >= requirement.count
                    and cited_ids <= matching.keys()):
                return {"reason": "requested_matches_found", "witness_ids": sorted(cited_ids),
                        "required_count": requirement.count}
            prefix = coverage.ordered_prefix()
            if not prefix:
                continue
            direction, rows, dates = prefix
            if requirement.kind == "comparison" and requirement.direction == direction and positive:
                first = next((row for row in rows if requirement.matches(row)), None)
                if first and (cited_ids == {first[0]} or answer.strip().rstrip(".").lower()
                              in {value.lower() for value in first[1:]}):
                    return {"reason": "ordered_first_match", "witness_ids": [first[0]],
                            "sort_direction": direction}
            if requirement.start and requirement.kind in {"aggregate", "enumeration", "existence"}:
                crossed = (dates[-1] < requirement.start if direction == "descending"
                           else dates[-1] > requirement.end)
                if crossed:
                    return {"reason": "requested_date_range_covered", "scope_url": coverage.url,
                            "date_range": [requirement.start.isoformat(), requirement.end.isoformat()],
                            "sort_direction": direction, "prefix_items": len(rows),
                            "boundary_order_id": rows[-1][0],
                            "matching_order_ids": [row[0] for row in rows if requirement.matches(row)],
                            "sort_sources": sorted({coverage.sort_sources[i] for i in range(1, len(rows) + 1)})}
        return None

    def context(self):
        if not self.enabled or not self.supported:
            return ""
        
        lines = [f"STOP EVIDENCE CHECK: request type = {self.request_type}.",
                 "Stop when the evidence satisfies the request; visiting every page is not always necessary."]
        requirement = self.evidence_requirement
        if requirement.start:
            lines.append(f"Requested date range (inclusive): {requirement.start.isoformat()} to {requirement.end.isoformat()}; "
                         f"status={requirement.status or 'any'}; reference date from objective={requirement.reference_date or 'not needed'}.")
        if not requirement.understood:
            lines.append("The request's conditions are not fully understood by the early-stop rules; full coverage is required.")
        elif requirement.kind == "existence":
            lines.append("A positive answer needs one observed order matching ALL requested conditions. Absence needs complete relevant coverage.")
        elif requirement.kind == "sample":
            lines.append(f"Return {requirement.count} distinct matching order IDs. Once enough matches are observed, no further pages are required.")
        elif requirement.kind == "lookup":
            lines.append("The requested order's observed row is sufficient for an identity lookup.")
        else:
            lines.append("Cover the relevant scope. A date boundary or first match is sufficient only with explicitly verified date sorting and a contiguous prefix from item 1.")
        
        for coverage in self.scopes.values():
            total = coverage.total if coverage.total is not None else "unknown"
            lines.append(f"{coverage.url}: observed {len(set(coverage.positions.values()))}/{total} orders; "
                         f"pages {sorted(coverage.pages)}/{coverage.page_count or 'unknown'}; complete={coverage.complete}.")
            sources = sorted(set(coverage.sort_sources.values()) - {""})
            if sources:
                lines.append(f"Date sort evidence: {sources}.")
            elif requirement.start:
                lines.append("Date boundary shortcut unavailable: no trusted sorting evidence for this scope.")
            # Retain factual evidence even when the actor prunes interaction history.
            lines.extend(" | ".join(row) for row in coverage.rows.values())
            if requirement.understood:
                matches = [rid for rid, row in coverage.rows.items() if requirement.matches(row)]
                lines.append(f"Observed matching order IDs: {matches}.")

        if self.feedback:
            lines.append(self.feedback)
        return "\n".join(lines)

    def check(self, action):
        match = STOP.search(action or "")
        if not match:
            return None
        
        result = {"allowed": True, "request_type": self.request_type,
                  "requirement": self.evidence_requirement.snapshot(),
                  "coverage": self.snapshot(), "feedback": ""}
        if not self.enabled or not self.supported:
            result["reason"] = "disabled" if not self.enabled else "unsupported_task"
            return result
        
        answer = action[match.end():].strip().rstrip("]").strip()
        # A batch that navigates and stops cannot prove its post-action state.
        prefix = action[:match.start()].strip()

        if prefix and not all(line.strip().startswith("note [") for line in prefix.splitlines()):
            missing = "Navigation and stop are in the same batch. Navigate first, inspect the resulting observation, then propose stop."

        elif any(coverage.complete for coverage in self.scopes.values()):
            self.feedback = ""
            result["reason"] = "full_coverage"
            return result
        
        else:
            proof = self.early_evidence(answer)
            if proof:
                self.feedback = ""
                result.update(proof)
                return result
            
            if not self.scopes:
                missing = "The full My Orders history has not been inspected. A homepage, Recent Orders table, or arbitrary filter is insufficient."
            else:
                best = max(self.scopes.values(), key=lambda c: len(c.positions))
                total = best.total if best.total is not None else "unknown"
                missing = (f"Only {len(set(best.positions.values()))}/{total} order records have been observed. "
                           f"Checked pages: {sorted(best.pages)} of {best.page_count or 'unknown'}. ")
                if best.page_count:
                    unseen = sorted(set(range(1, best.page_count + 1)) - best.pages)
                    missing += f"Pages not yet checked: {unseen}. "
                missing += best.issue
            requirement = self.evidence_requirement
            if not requirement.understood:
                missing += " The request's conditions/date expression were not fully parsed. "
            elif requirement.start:
                missing += f" Requested interval: {requirement.start.isoformat()} to {requirement.end.isoformat()}. "
                if not any(c.ordered_prefix() for c in self.scopes.values()):
                    missing += "Missing a contiguous date-sorted prefix with trusted sort evidence. "
            if requirement.understood and requirement.kind in {"existence", "sample"}:
                missing += (f" To answer positively, observe {requirement.count} distinct order(s) matching ALL "
                            "requested conditions; cite the matching IDs when listing examples. "
                            "You may stop once that evidence is available. An absence or shortfall claim still needs complete relevant coverage.")
            else:
                missing += (" Continue until the relevant scope is covered, or the requested record is observed. "
                            "Unchecked records may change the conclusion. Do not infer absence from the current "
                            "page or assume global date ordering without trusted sort evidence.")
            
        self.rejections += 1
        self.feedback = "STOP REJECTED: insufficient evidence. " + missing
        result.update(allowed=False, reason="insufficient_evidence", feedback=self.feedback,
                      rejection_count=self.rejections)
        return result
