"""The orchestration layer: search, paginate, enrich, collect.

The engine is deliberately UI-agnostic. It talks to the outside world through
three callbacks:

``captcha_prompt(info) -> str``
    Called when a captcha needs a human. Returns the typed answer.
``progress(event)``
    Called with progress events for the status bar.
``cancel_event``
    A ``threading.Event`` checked between every request.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from datetime import timedelta
from urllib.parse import urljoin

from .client import IrepsClient, SessionExpired
from .config import (
    BASE_URL,
    PO_SEARCH_URL,
    TENDER_DETAIL_PATH,
    TENDER_SEARCH_URL,
    LogEntry,
    SearchCriteria,
    Settings,
)
from .detail import parse_detail, read_cache, write_cache
from .discovery import CaptchaInfo, SearchPageInfo, discover
from .normalize import parse_date
from .parser import (
    dedupe,
    parse_result_count,
    parse_results,
    parse_tender_results,
    tender_detail_payload,
    tender_page_body,
)


@dataclass
class ScrapeResult:
    records: list[dict] = field(default_factory=list)
    log: list[LogEntry] = field(default_factory=list)
    criteria: SearchCriteria | None = None
    total_count: int | None = None
    pages_fetched: int = 0
    details_fetched: int = 0
    details_cached: int = 0
    details_failed: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0
    cancelled: bool = False
    page_info: SearchPageInfo | None = None

    @property
    def elapsed(self) -> float:
        return max(0.0, self.finished_at - self.started_at)


#: How many times a date window may be halved before giving up.
MAX_SPLIT_DEPTH = 6


def _tender_search_ran(html: str, count: int | None, rows: int) -> bool:
    """True when the portal actually ran the search.

    The tender page answers a search that worked with a result count, and a
    search that genuinely found nothing with "No Results Found". Anything
    else means the request came back without being run - the portal does that
    now and then - and the search is worth trying again.
    """
    if rows or count is not None:
        return True
    return "No Results Found" in html


class ScrapeEngine:
    """Runs one search from beginning to end."""

    #: How many times a tender search is asked for before it is given up on.
    search_attempts = 3

    def __init__(self, client: IrepsClient, settings: Settings):
        self.client = client
        self.settings = settings

    # -- public ------------------------------------------------------------
    def run(
        self,
        criteria: SearchCriteria,
        captcha_prompt=None,
        progress=None,
        cancel_event: threading.Event | None = None,
    ) -> ScrapeResult:
        result = ScrapeResult(criteria=criteria, started_at=time.time())
        emit = progress or (lambda event: None)

        try:
            self._run(criteria, result, captcha_prompt, emit, cancel_event)
        except SessionExpired as exc:
            result.log.append(
                LogEntry(scope="run", item="session", status="expired", detail=str(exc))
            )
            emit({"kind": "error", "message": str(exc)})
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller
            result.log.append(
                LogEntry(scope="run", item="-", status="error", detail=repr(exc))
            )
            emit({"kind": "error", "message": repr(exc)})
        finally:
            result.finished_at = time.time()

        emit({"kind": "done", "result": result})
        return result

    # -- internals ---------------------------------------------------------
    def _search_url(self, criteria: SearchCriteria) -> str:
        return PO_SEARCH_URL if criteria.mode == "po" else TENDER_SEARCH_URL

    def _run(self, criteria, result, captcha_prompt, emit, cancel_event):
        def cancelled() -> bool:
            return bool(cancel_event and cancel_event.is_set())

        emit({"kind": "status", "message": "Opening the IREPS search page..."})
        response = self.client.get(self._search_url(criteria))
        html = response.text
        self.client.ensure_alive(html)

        info = discover(html)
        result.page_info = info
        if not info.form_action:
            raise RuntimeError(
                "The search form could not be found on the IREPS page. "
                "Open the page in a browser to check whether it has changed."
            )
        emit(
            {
                "kind": "status",
                "message": f"Search form ready - {len(info.selects)} dropdown(s) discovered.",
            }
        )

        action = urljoin(BASE_URL + "/", info.form_action)
        known = set(info.inputs) | set(info.selects)

        def captcha_for_request() -> tuple[str, str]:
            """Ask for a captcha if this form has one (the PO form does not)."""
            if info.captcha.kind == "none" or not captcha_prompt:
                return "", ""
            emit({"kind": "status", "message": "Waiting for the verification code..."})
            typed = (captcha_prompt(info.captcha) or "").strip()
            if not typed:
                raise RuntimeError("No verification code was entered - the search was cancelled.")
            return typed, info.captcha.answer

        def build_payload(criteria) -> dict:
            payload = criteria.to_payload()
            typed, answer = captcha_for_request()
            if info.captcha.kind != "none":
                payload["number"] = typed
                payload["ver"] = answer
            # Send only the fields this form actually has - the PO search form
            # and the tender search form are different forms.
            allowed = {key: value for key, value in payload.items() if key in known}
            allowed.setdefault("submit", "Show Results")
            dropped = sorted(set(payload) - set(allowed))
            if dropped and not result.log:
                result.log.append(
                    LogEntry(scope="search", item="payload", status="trimmed",
                             detail="Not present on this form: " + ", ".join(dropped))
                )
            return allowed

        emit({"kind": "status", "message": "Submitting the search..."})
        if criteria.mode == "tenders":
            records, count = self._collect_tenders(
                criteria, result, emit, cancel_event, action
            )
        else:
            records, count = self._collect(
                criteria, result, emit, cancel_event, action, build_payload, depth=0
            )
        result.total_count = count

        result.records = dedupe(records)
        emit(
            {
                "kind": "status",
                "message": f"{len(result.records)} records collected "
                f"(the portal reported {count or 'no'} ).",
            }
        )

        # --- detail pages ------------------------------------------------
        # The PO search results are a terminal list: the portal links no detail
        # page from the rows and offers only "Print Results". So for a PO
        # search the list is the whole dataset and this phase is skipped.
        # The tender grid does link every row to its own detail page.
        if criteria.fetch_details and result.records and not cancelled():
            if any(record.get("Detail URL") or record.get("Tender ID")
                   for record in result.records):
                self._fetch_details(result, emit, cancel_event)
            else:
                result.log.append(
                    LogEntry(scope="detail", item="all", status="skipped",
                             detail="The PO results carry no detail-page link, so the list "
                                    "is the complete record set. Nothing was fetched.")
                )
                emit({"kind": "status",
                      "message": "This search returns no per-record detail page - "
                                 "the list is the full dataset."})

    def _collect(self, criteria, result, emit, cancel_event, action, build_payload,
                 depth: int = 0):
        """Run one search, splitting the date range if the portal truncates it.

        The PO search renders the whole result set in a single HTML page and
        offers no pagination, but it silently truncates a large result set
        (verified live: a 10-day window reported 5,056 records and rendered
        only 1,106). When the reported count is bigger than the rows we
        received, the date window is halved and each half searched on its own.
        """
        payload = build_payload(criteria)
        response = self.client.post(action, data=payload)
        html = response.text
        self.client.ensure_alive(html)

        records = parse_results(html)
        count = parse_result_count(html)
        result.pages_fetched += 1
        result.log.append(
            LogEntry(
                scope="search",
                item=f"{criteria.date_from} to {criteria.date_to}",
                status="ok",
                rows=len(records),
                http_status=response.status_code,
                detail=f"reported {count}" if count else "",
            )
        )
        emit({"kind": "page", "page": result.pages_fetched, "rows": len(records)})
        emit({"kind": "rows", "records": records})

        if cancel_event and cancel_event.is_set():
            return records, count

        truncated = bool(count and count > len(records) + 1)
        if not truncated:
            return records, count

        start = parse_date(criteria.date_from)
        end = parse_date(criteria.date_to)
        if start is None or end is None or end <= start or depth >= MAX_SPLIT_DEPTH:
            result.log.append(
                LogEntry(
                    scope="search",
                    item=f"{criteria.date_from} to {criteria.date_to}",
                    status="truncated",
                    rows=len(records),
                    detail=f"The portal reported {count} but only sent {len(records)}. "
                           "Narrow the date range or pick a specific organisation.",
                )
            )
            emit({"kind": "status",
                  "message": f"Truncated: the portal reported {count} records but sent "
                             f"{len(records)}. Narrowing is needed for this window."})
            return records, count

        middle = start + (end - start) / 2
        left_end = middle
        right_start = middle + timedelta(days=1)
        emit(
            {
                "kind": "status",
                "message": f"The portal cut the results short ({len(records)} of {count}). "
                           f"Splitting into {left_end:%d/%m/%Y} and {right_start:%d/%m/%Y}...",
            }
        )
        result.log.append(
            LogEntry(scope="search", item="split", status="ok",
                     detail=f"{count} reported, {len(records)} sent - splitting "
                            f"{criteria.date_from}-{criteria.date_to} into "
                            f"{left_end:%d/%m/%Y} and {right_start:%d/%m/%Y}")
        )

        left_criteria = replace(criteria, date_from=criteria.date_from, date_to=left_end.strftime("%d/%m/%Y"))
        right_criteria = replace(criteria, date_from=right_start.strftime("%d/%m/%Y"), date_to=criteria.date_to)

        left_records, left_count = self._collect(
            left_criteria, result, emit, cancel_event, action, build_payload, depth + 1
        )
        right_records, right_count = self._collect(
            right_criteria, result, emit, cancel_event, action, build_payload, depth + 1
        )
        return left_records + right_records, count

    def _collect_tenders(self, criteria, result, emit, cancel_event, action):
        """Run a tender search and walk the portal's pages.

        Unlike the PO search, the tender grid is paginated: the portal reports
        the total, renders 25 rows per page and links the rest. The pages are
        fetched with the very parameters the portal's own pagination links
        carry, which is what its JavaScript does.
        """
        payload = criteria.tender_payload()
        if criteria.tender_tab and criteria.tender_tab != "Custom Search":
            payload = criteria.tender_tab_payload()

        records: list[dict] = []
        count: int | None = None
        html = ""
        for attempt in range(1, self.search_attempts + 1):
            response = self.client.post(action, data=payload)
            html = response.text
            self.client.ensure_alive(html)

            records = parse_tender_results(html)
            count = parse_result_count(html)
            if _tender_search_ran(html, count, len(records)):
                break
            # The portal answered without running the search. It does that
            # occasionally, so the search is simply asked for again.
            emit({"kind": "status",
                  "message": f"The portal did not answer that search "
                             f"(attempt {attempt} of {self.search_attempts}) - trying again..."})
            result.log.append(
                LogEntry(scope="search", item="retry", status="no-answer",
                         rows=len(records),
                         detail=f"Attempt {attempt} of {self.search_attempts}: the portal "
                                "answered without running the search.")
            )
            time.sleep(3.0 * attempt)

        result.pages_fetched += 1
        result.log.append(
            LogEntry(
                scope="search",
                item=f"{criteria.tender_tab} / {criteria.date_from} to {criteria.date_to}",
                status="ok",
                rows=len(records),
                http_status=response.status_code,
                detail=f"reported {count}" if count else "",
            )
        )
        emit({"kind": "page", "page": result.pages_fetched, "rows": len(records)})
        emit({"kind": "rows", "records": records})

        if not records:
            detail = ("The portal returned no tender rows for this search."
                      if _tender_search_ran(html, count, 0)
                      else "The portal did not answer this search at all.")
            result.log.append(
                LogEntry(scope="search", item="results", status="empty", detail=detail)
            )
            return records, count

        if count and count <= len(records):
            # Everything fitted on the first page - there is nothing to page
            # through.
            return records, count

        page_body = tender_page_body(html, count, payload)
        if not page_body:
            # Everything fitted on one page - there is nothing to page through.
            return records, count

        page = 1
        while True:
            if cancel_event and cancel_event.is_set():
                result.cancelled = True
                break
            if result.pages_fetched >= self.settings.max_pages:
                result.log.append(
                    LogEntry(scope="search", item="pagination", status="truncated",
                             detail=f"Stopped after {result.pages_fetched} pages "
                                    f"(the max-pages limit). Raise it to collect the rest.")
                )
                emit({"kind": "status",
                      "message": f"Stopped at the {self.settings.max_pages}-page limit."})
                break

            page += 1
            body = dict(page_body)
            body["pageNo"] = str(page)
            response = self.client.post(action, data=body)
            html = response.text
            self.client.ensure_alive(html)
            page_records = parse_tender_results(html)
            result.pages_fetched += 1
            result.log.append(
                LogEntry(scope="search", item=f"page {page}", status="ok",
                         rows=len(page_records), http_status=response.status_code)
            )
            emit({"kind": "page", "page": result.pages_fetched, "rows": len(page_records)})

            if not page_records:
                break
            records.extend(page_records)
            emit({"kind": "rows", "records": page_records})
            if count and len(records) >= count:
                break

        return records, count

    def _fetch_details(self, result: ScrapeResult, emit, cancel_event):
        total = len(result.records)
        for index, record in enumerate(result.records, start=1):
            if cancel_event and cancel_event.is_set():
                result.cancelled = True
                break
            is_tender = bool(record.get("Tender ID"))
            url = record.get("Detail URL") or ""
            tender_id = record.get("Tender ID") or ""
            if not url and not tender_id:
                result.details_failed += 1
                result.log.append(
                    LogEntry(scope="detail", item=record.get("PO Reference") or str(index),
                             status="no-link", detail="The row carried no detail link.")
                )
                continue

            key = url or f"tender:{tender_id}"
            html = read_cache(key)
            if html is None:
                try:
                    if is_tender:
                        # The portal posts the opaque id to its detail page.
                        response = self.client.post(
                            urljoin(BASE_URL + "/", TENDER_DETAIL_PATH),
                            data=tender_detail_payload(tender_id),
                        )
                    else:
                        response = self.client.get(urljoin(BASE_URL + "/", url))
                    html = response.text
                    self.client.ensure_alive(html)
                    write_cache(key, html)
                    result.details_fetched += 1
                    status = "fetched"
                except SessionExpired:
                    raise
                except Exception as exc:  # noqa: BLE001
                    result.details_failed += 1
                    result.log.append(
                        LogEntry(scope="detail", item=url or tender_id, status="failed",
                                 detail=repr(exc))
                    )
                    continue
            else:
                result.details_cached += 1
                status = "cached"

            fields = parse_detail(html)
            for key_name, value in fields.items():
                if key_name == "Detail_Labels":
                    record["Detail Labels"] = value
                    continue
                if value and not record.get(key_name):
                    record[key_name] = value
            record["Detail Fetched"] = status

            if index % 5 == 0 or index == total:
                emit(
                    {
                        "kind": "status",
                        "message": f"Detail pages {index}/{total} "
                        f"(fetched {result.details_fetched}, cached {result.details_cached}).",
                    }
                )
