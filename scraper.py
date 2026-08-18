import re
import requests
from datetime import datetime, timezone

from config import REMOTE_KEYWORDS
from keywords_store import get_keywords

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{board_id}/jobs?content=true"
LEVER_API = "https://api.lever.co/v0/postings/{company}?mode=json&limit=500"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobTracker/1.0)"}
HTTP_TIMEOUT_SECONDS = 20


class ScrapeError(RuntimeError):
    """Raised when a company scan could not return a complete result set."""


class ScrapeResult(list):
    """Filtered jobs plus mutually exclusive counts from the raw ATS result."""

    def __init__(
        self,
        jobs: list[dict],
        *,
        total_found: int,
        not_remote: int,
        keyword_filtered: int,
    ):
        super().__init__(jobs)
        self.total_found = total_found
        self.not_remote = not_remote
        self.keyword_filtered = keyword_filtered

        if total_found != len(jobs) + not_remote + keyword_filtered:
            raise ValueError("Scrape filter counts do not add up to total_found")


# ---------------------------------------------------------------------------
# ATS detection
# ---------------------------------------------------------------------------

def detect_ats(careers_url: str) -> tuple[str, str]:
    """
    Inspect the careers URL (and page source if needed) to identify the ATS.
    Returns (ats_type, board_id) where ats_type is one of:
      'greenhouse', 'lever', 'unknown'
    """
    # Direct Greenhouse / Lever URLs
    if "greenhouse.io" in careers_url:
        m = re.search(r"greenhouse\.io/(?:embed/job_board\?for=)?(\w+)", careers_url)
        if m:
            return "greenhouse", m.group(1)

    if "lever.co" in careers_url:
        m = re.search(r"lever\.co/(\w+)", careers_url)
        if m:
            return "lever", m.group(1)

    # Fetch the page and sniff for embedded ATS widgets
    try:
        resp = requests.get(
            careers_url,
            timeout=HTTP_TIMEOUT_SECONDS,
            headers=HEADERS,
        )
        html = resp.text

        m = re.search(r'boards\.greenhouse\.io/embed/job_board\?for=(\w+)', html)
        if m:
            return "greenhouse", m.group(1)

        m = re.search(r'greenhouse\.io/(\w+)', html)
        if m:
            return "greenhouse", m.group(1)

        m = re.search(r'jobs\.lever\.co/(\w+)', html)
        if m:
            return "lever", m.group(1)

    except requests.RequestException as exc:
        print(f"  Warning: could not fetch {careers_url}: {exc}")

    return "unknown", ""


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------

def _matches_role(title: str) -> bool:
    kws = get_keywords()
    t = title.lower()
    if any(kw.lower() in t for kw in kws["title_exclude_keywords"]):
        return False
    return any(kw.lower() in t for kw in kws["title_keywords"])


def _is_remote(title: str, location: str, extra: str = "") -> bool:
    haystack = " ".join([title, location, extra]).lower()
    return any(kw.lower() in haystack for kw in REMOTE_KEYWORDS)


US_LOCATION_PATTERNS = [
    re.compile(r"\bunited\s+states\b", re.IGNORECASE),
    re.compile(r"(?<![a-z0-9])u\.?s\.?(?![a-z0-9])", re.IGNORECASE),
    re.compile(r"\busa\b", re.IGNORECASE),
]


def _is_us_workable(location: str) -> bool:
    """Return True if the location string indicates a US-based or US-remote role."""
    return any(pattern.search(location) for pattern in US_LOCATION_PATTERNS)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(ts) -> str | None:
    """Convert a Unix timestamp (int/float, seconds or ms) to an ISO date string."""
    if ts is None:
        return None
    try:
        ts = float(ts)
        # Lever uses milliseconds; anything > year 3000 in seconds is actually ms
        if ts > 32503680000:
            ts /= 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
    except (ValueError, OSError):
        return None


# ---------------------------------------------------------------------------
# Greenhouse
# ---------------------------------------------------------------------------

def scrape_greenhouse(board_id: str, company_name: str, source_url: str, us_only: bool = False) -> list[dict]:
    url = GREENHOUSE_API.format(board_id=board_id)
    print(f"  -> Greenhouse API: {url}")

    try:
        resp = requests.get(url, timeout=HTTP_TIMEOUT_SECONDS, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        print(f"  Error: {exc}")
        raise ScrapeError(str(exc)) from exc

    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ScrapeError("Greenhouse returned an unexpected response shape")

    all_jobs = data.get("jobs", [])
    print(f"  Total listings: {len(all_jobs)}")
    jobs = []
    not_remote = 0
    keyword_filtered = 0
    for job in all_jobs:
        title = job.get("title", "")
        location = job.get("location", {}).get("name", "")
        job_url = job.get("absolute_url", "")
        department = ""
        if job.get("departments"):
            department = job["departments"][0].get("name", "")

        # Some boards (e.g. Airbnb) include a structured "Workplace Type" metadata field
        meta_workplace = next(
            (m.get("value", "") for m in (job.get("metadata") or [])
             if m.get("name") == "Workplace Type"),
            None,
        )
        meta_is_remote = isinstance(meta_workplace, str) and "remote" in meta_workplace.lower()

        if not _matches_role(title):
            keyword_filtered += 1
            continue
        # A country-only US location (e.g. "United States", no city) implies remote-eligible
        is_country_only_us = "," not in location and (_is_us_workable(location) or us_only)
        if not meta_is_remote and not _is_remote(title, location) and not is_country_only_us:
            not_remote += 1
            continue
        if not us_only and not _is_us_workable(location):
            not_remote += 1
            continue

        # Keep full ISO datetime from Greenhouse — has genuine hour/minute precision
        date_posted = job.get("first_published") or job.get("updated_at") or None

        jobs.append({
            "title": title,
            "company": company_name,
            "location": location,
            "url": job_url,
            "is_remote": 1,
            "department": department,
            "description": None,
            "date_posted": date_posted,
            "date_found": _now(),
            "last_seen": _now(),
            "source_url": source_url,
        })

    return ScrapeResult(
        jobs,
        total_found=len(all_jobs),
        not_remote=not_remote,
        keyword_filtered=keyword_filtered,
    )


# ---------------------------------------------------------------------------
# Lever
# ---------------------------------------------------------------------------

def scrape_lever(company_id: str, company_name: str, source_url: str) -> list[dict]:
    url = LEVER_API.format(company=company_id)
    print(f"  -> Lever API: {url}")

    try:
        resp = requests.get(url, timeout=HTTP_TIMEOUT_SECONDS, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        print(f"  Error: {exc}")
        raise ScrapeError(str(exc)) from exc

    if not isinstance(data, list):
        raise ScrapeError("Lever returned an unexpected response shape")

    print(f"  Total listings: {len(data)}")
    jobs = []
    not_remote = 0
    keyword_filtered = 0
    for job in data:
        title = job.get("text", "")
        categories = job.get("categories", {})
        location = categories.get("location", "") or job.get("workplaceType", "")
        commitment = categories.get("commitment", "")
        department = categories.get("department", "")
        job_url = job.get("hostedUrl", "")

        if not _matches_role(title):
            keyword_filtered += 1
            continue
        is_country_only_us = "," not in location and _is_us_workable(location)
        if not _is_remote(title, location, commitment) and not is_country_only_us:
            not_remote += 1
            continue
        if not _is_us_workable(location):
            not_remote += 1
            continue

        jobs.append({
            "title": title,
            "company": company_name,
            "location": location,
            "url": job_url,
            "is_remote": 1,
            "department": department,
            "description": None,
            "date_posted": _parse_ts(job.get("createdAt")),
            "date_found": _now(),
            "last_seen": _now(),
            "source_url": source_url,
        })

    return ScrapeResult(
        jobs,
        total_found=len(data),
        not_remote=not_remote,
        keyword_filtered=keyword_filtered,
    )


# ---------------------------------------------------------------------------
# ClinchTalent (Playwright-based, used by Zoom and others)
# ---------------------------------------------------------------------------

def scrape_clinchtalent(careers_url: str, company_name: str) -> list[dict]:
    """
    ClinchTalent career pages are server-rendered but protected by AWS WAF,
    so plain requests get blocked.  Playwright solves the WAF challenge, then
    we parse job cards from the rendered HTML and paginate via ?page=N.
    The careers_url should already include filter params (remote, country, etc.)
    """
    from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

    from playwright.sync_api import sync_playwright

    parsed = urlparse(careers_url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    # Remove page param — we'll inject it ourselves
    qs.pop("page", None)
    base_params = urlencode(qs, doseq=True)
    base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    print(f"  -> ClinchTalent (Playwright): {careers_url[:80]}...")

    all_jobs = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()

        page_num = 1
        while True:
            url = f"{base_url}?page={page_num}&{base_params}"
            page.goto(url, wait_until="networkidle", timeout=30000)

            cards = page.query_selector_all("article.job-search-results-card-col")
            if not cards:
                break

            for card in cards:
                link = card.query_selector("a[href*='/jobs/']")
                if not link:
                    continue
                title = (card.query_selector("h3, h2") or link).inner_text().strip()
                job_url = link.get_attribute("href") or ""
                loc_el = card.query_selector(".job-component-location span")
                location = loc_el.inner_text().strip() if loc_el else ""

                all_jobs.append({"title": title, "url": job_url, "location": location})

            # If fewer cards than a full page, we're done (ClinchTalent uses ~10/page)
            if len(cards) < 10:
                break
            page_num += 1

        browser.close()

    print(f"  Total listings fetched: {len(all_jobs)}")

    jobs = []
    not_remote = 0
    keyword_filtered = 0
    for entry in all_jobs:
        title = entry["title"]
        if not _matches_role(title):
            keyword_filtered += 1
            continue
        location = entry["location"]
        if not _is_remote(title, location) and "remote" not in careers_url.lower():
            not_remote += 1
            continue

        jobs.append({
            "title": title,
            "company": company_name,
            "location": location,
            "url": entry["url"],
            "is_remote": 1,
            "department": "",
            "description": None,
            "date_posted": None,
            "date_found": _now(),
            "last_seen": _now(),
            "source_url": careers_url,
        })

    return ScrapeResult(
        jobs,
        total_found=len(all_jobs),
        not_remote=not_remote,
        keyword_filtered=keyword_filtered,
    )


# ---------------------------------------------------------------------------
# Eightfold (Playwright-based, used by Microsoft and others)
# ---------------------------------------------------------------------------

def scrape_eightfold(careers_url: str, company_name: str) -> list[dict]:
    """
    Eightfold AI career pages (vscdn.net) require a live browser session.
    We use Playwright to load the page, intercept the /api/pcsx/search call,
    then paginate through results using page.request (inherits session cookies).
    The careers_url should already be filtered (remote, location, seniority, etc.)
    so we only apply title keyword matching on top.
    """
    from urllib.parse import urlparse
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    parsed = urlparse(careers_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    print(f"  -> Eightfold (Playwright): {careers_url[:80]}...")

    all_positions = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()

        search_api_base = None
        first_page_data = {}

        def handle_response(resp):
            nonlocal search_api_base
            if "/api/pcsx/search" in resp.url and search_api_base is None:
                # Strip the start= param so we can rebuild it for pagination
                search_api_base = re.sub(r"[&?]start=\d+", "", resp.url)
                try:
                    first_page_data["json"] = resp.json()
                except Exception:
                    pass

        page.on("response", handle_response)
        # Eightfold pages keep background requests alive indefinitely. Waiting
        # only for the DOM avoids false navigation timeouts while the response
        # listener above captures the search API payload.
        page.goto(careers_url, wait_until="domcontentloaded", timeout=30000)

        # The SPA can issue its search request just after DOMContentLoaded. Wait
        # for that response specifically instead of waiting for all network
        # traffic to become idle.
        if not search_api_base:
            try:
                search_response = page.wait_for_event(
                    "response",
                    predicate=lambda resp: "/api/pcsx/search" in resp.url,
                    timeout=30000,
                )
                handle_response(search_response)
            except PlaywrightTimeoutError:
                pass

        if not search_api_base:
            message = "Could not locate search API - page may require login."
            print(f"  {message}")
            browser.close()
            raise ScrapeError(message)

        if "json" not in first_page_data:
            browser.close()
            raise ScrapeError("Eightfold search response was not valid JSON")

        inner = first_page_data.get("json", {}).get("data", {})
        if "count" not in inner or not isinstance(inner.get("positions"), list):
            browser.close()
            raise ScrapeError("Eightfold returned an unexpected response shape")
        total = inner.get("count", 0)
        all_positions.extend(inner.get("positions", []))
        print(f"  Total matches on server: {total}")

        # Paginate remaining pages using the live browser session
        page_size = 10
        sep = "&" if "?" in search_api_base else "?"
        for start in range(page_size, total, page_size):
            api_url = f"{search_api_base}{sep}start={start}"
            try:
                resp = page.request.get(api_url)
                chunk = resp.json().get("data", {}).get("positions", [])
                all_positions.extend(chunk)
            except Exception as exc:
                print(f"  Pagination error at start={start}: {exc}")
                raise ScrapeError(
                    f"Pagination failed at start={start}: {exc}"
                ) from exc

        if len(all_positions) < total:
            browser.close()
            raise ScrapeError(
                f"Eightfold returned {len(all_positions)} of {total} positions"
            )

        browser.close()

    # Apply title filters (URL already handles remote + location + seniority)
    jobs = []
    keyword_filtered = 0
    for pos in all_positions:
        title = pos.get("name", "")
        if not _matches_role(title):
            keyword_filtered += 1
            continue

        locations = pos.get("locations", [])
        location = locations[0] if locations else ""
        dept = pos.get("department", "")
        pos_path = pos.get("positionUrl", "")
        job_url = f"{base_url}{pos_path}" if pos_path.startswith("/") else pos_path

        jobs.append({
            "title": title,
            "company": company_name,
            "location": location,
            "url": job_url,
            "is_remote": 1,
            "department": dept,
            "description": None,
            "date_posted": _parse_ts(pos.get("postedTs")),
            "date_found": _now(),
            "last_seen": _now(),
            "source_url": careers_url,
        })

    return ScrapeResult(
        jobs,
        total_found=len(all_positions),
        not_remote=0,
        keyword_filtered=keyword_filtered,
    )


# ---------------------------------------------------------------------------
# Eightfold v2 (public API — used by Netflix and others)
# ---------------------------------------------------------------------------

def _is_eightfold_v2_remote(position: dict) -> bool:
    """Return whether an Eightfold v2 position has listing-level remote evidence."""
    custom_fields = (
        (position.get("custom_JD") or {}).get("data_fields") or {}
    )
    work_types = custom_fields.get("work_type") or []
    if isinstance(work_types, str):
        work_types = [work_types]
    if work_types:
        return any("remote" in str(value).lower() for value in work_types)

    locations = " ".join(position.get("locations") or [])
    return _is_remote(position.get("name", ""), locations)


def scrape_eightfold_v2(careers_url: str, company_name: str) -> list[dict]:
    """
    Some Eightfold tenants expose /api/apply/v2/jobs publicly (no browser auth).
    Requires 'domain' and optionally 'base_url' parsed from careers_url.
    """
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(careers_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    params = parse_qs(parsed.query)
    domain = (params.get("domain") or [parsed.netloc])[0]
    location = (params.get("location") or ["Remote"])[0]
    sort_by = (params.get("sort_by") or ["new"])[0]

    api_base = f"{base_url}/api/apply/v2/jobs"
    print(f"  -> Eightfold v2 API: {api_base}?domain={domain}&location={location}")

    all_positions = []
    page_size = 10

    # First page — also gets total count
    try:
        r = requests.get(api_base, params={
            "domain": domain, "location": location,
            "sort_by": sort_by, "num": page_size, "start": 0,
        }, headers=HEADERS, timeout=HTTP_TIMEOUT_SECONDS)
        if r.status_code != 200:
            message = f"HTTP {r.status_code}: {r.text[:100]}"
            print(f"  Error {message}")
            raise ScrapeError(message)
        first = r.json()
    except requests.RequestException as exc:
        print(f"  Error: {exc}")
        raise ScrapeError(str(exc)) from exc

    if "count" not in first or not isinstance(first.get("positions"), list):
        raise ScrapeError("Eightfold v2 returned an unexpected response shape")

    total = first.get("count", 0)
    all_positions.extend(first.get("positions", []))
    print(f"  Total matches: {total}")

    for start in range(page_size, total, page_size):
        try:
            r = requests.get(api_base, params={
                "domain": domain, "location": location,
                "sort_by": sort_by, "num": page_size, "start": start,
            }, headers=HEADERS, timeout=HTTP_TIMEOUT_SECONDS)
            if r.status_code != 200:
                raise ScrapeError(
                    f"Pagination failed at start={start}: HTTP {r.status_code}"
                )
            all_positions.extend(r.json().get("positions", []))
        except requests.RequestException as exc:
            print(f"  Pagination error at start={start}: {exc}")
            raise ScrapeError(
                f"Pagination failed at start={start}: {exc}"
            ) from exc

    if len(all_positions) < total:
        raise ScrapeError(
            f"Eightfold v2 returned {len(all_positions)} of {total} positions"
        )

    jobs = []
    not_remote = 0
    keyword_filtered = 0
    for pos in all_positions:
        title = pos.get("name", "")
        if not _matches_role(title):
            keyword_filtered += 1
            continue

        raw_locs = pos.get("locations", [])
        location_str = raw_locs[0] if raw_locs else ""
        if not _is_us_workable(location_str):
            not_remote += 1
            continue

        # Netflix's remote search can return onsite jobs with a misleading
        # work_location_option of "remote_local" and even stale remote location
        # text. Verify the authoritative Work Type from every matching detail.
        pos_id = pos.get("id", "")
        if not pos_id:
            not_remote += 1
            continue
        try:
            detail_response = requests.get(
                f"{api_base}/{pos_id}",
                params={"domain": domain},
                headers=HEADERS,
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            detail_response.raise_for_status()
            if not _is_eightfold_v2_remote(detail_response.json()):
                not_remote += 1
                continue
        except requests.RequestException as exc:
            print(f"  Could not verify work type for {pos_id}: {exc}")
            raise ScrapeError(
                f"Could not verify work type for job {pos_id}: {exc}"
            ) from exc

        job_url = pos.get("canonicalPositionUrl") or ""
        if not job_url:
            pos_id = pos.get("id", "")
            job_url = f"{base_url}/careers/job/{pos_id}" if pos_id else ""

        jobs.append({
            "title": title,
            "company": company_name,
            "location": location_str,
            "url": job_url,
            "is_remote": 1,
            "department": pos.get("department", ""),
            "description": None,
            "date_posted": _parse_ts(pos.get("t_create") or pos.get("postedTs")),
            "date_found": _now(),
            "last_seen": _now(),
            "source_url": careers_url,
        })

    return ScrapeResult(
        jobs,
        total_found=len(all_positions),
        not_remote=not_remote,
        keyword_filtered=keyword_filtered,
    )


# ---------------------------------------------------------------------------
# Workday (public JSON API)
# ---------------------------------------------------------------------------

def _parse_workday_posted(posted_on: str) -> str | None:
    """Convert Workday 'Posted X Days Ago' text to an ISO date string."""
    from datetime import timedelta
    if not posted_on:
        return None
    s = posted_on.lower().strip()
    today = datetime.now(timezone.utc).date()
    if "today" in s or "just posted" in s:
        return today.isoformat()
    if "yesterday" in s:
        return (today - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\+?\s+day", s)
    if m:
        days = int(m.group(1))
        return (today - timedelta(days=days)).isoformat()
    return None


def scrape_workday(careers_url: str, company_name: str, us_only: bool = False) -> list[dict]:
    """
    Workday career pages expose a JSON API at:
      POST /wday/cxs/{tenant}/{board}/jobs
    Filter facets (locationCountry, Job_Family, etc.) are passed as
    appliedFacets in the request body, parsed from the careers_url query string.
    """
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(careers_url)
    # URL pattern: https://{tenant}.wd5.myworkdayjobs.com/en-US/{board}?...
    path_parts = [p for p in parsed.path.split("/") if p]
    # Remove locale segment (en-US, en-GB, etc.)
    board_parts = [p for p in path_parts if not re.match(r"^[a-z]{2}-[A-Z]{2}$", p)]
    board = board_parts[0] if board_parts else path_parts[-1]
    # Tenant is the subdomain
    tenant = parsed.hostname.split(".")[0]

    api_url = f"https://{parsed.hostname}/wday/cxs/{tenant}/{board}/jobs"
    print(f"  -> Workday API: {api_url}")

    # Build appliedFacets from URL query params — Workday always expects arrays
    qs = parse_qs(parsed.query)
    applied_facets = {key: values for key, values in qs.items()}

    headers = {
        **HEADERS,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    limit = 20
    offset = 0
    all_postings = []

    # First request to get total count
    payload = {"limit": limit, "offset": offset, "searchText": "", "appliedFacets": applied_facets}
    try:
        r = requests.post(api_url, json=payload, headers=headers, timeout=20)
        r.raise_for_status()
        first = r.json()
    except requests.RequestException as exc:
        print(f"  Error: {exc}")
        raise ScrapeError(str(exc)) from exc

    if "total" not in first or not isinstance(first.get("jobPostings"), list):
        raise ScrapeError("Workday returned an unexpected response shape")

    total = first.get("total", 0)
    all_postings.extend(first.get("jobPostings", []))
    print(f"  Total matches: {total}")

    for offset in range(limit, total, limit):
        payload["offset"] = offset
        try:
            r = requests.post(api_url, json=payload, headers=headers, timeout=20)
            r.raise_for_status()
            all_postings.extend(r.json().get("jobPostings", []))
        except requests.RequestException as exc:
            raise ScrapeError(
                f"Pagination failed at offset={offset}: {exc}"
            ) from exc

    if len(all_postings) < total:
        raise ScrapeError(
            f"Workday returned {len(all_postings)} of {total} postings"
        )

    base_url = f"{parsed.scheme}://{parsed.hostname}"
    jobs = []
    not_remote = 0
    keyword_filtered = 0
    for posting in all_postings:
        title = posting.get("title", "")
        if not _matches_role(title):
            keyword_filtered += 1
            continue

        location = posting.get("locationsText", "")
        # "N Locations" means multiple — only treat as US if a country facet was applied
        # or if the company is known to be US-only (us_only flag)
        if re.match(r"^\d+\s+[Ll]ocation", location):
            if "locationCountry" in applied_facets or us_only:
                location = "United States (Remote)"
            else:
                not_remote += 1
                continue  # can't determine location without country facet

        if not _is_us_workable(location):
            not_remote += 1
            continue
        if not _is_remote(title, location) and "remote" not in careers_url.lower():
            not_remote += 1
            continue

        ext_path = posting.get("externalPath", "")
        board_path = parsed.path.rstrip("/")
        job_url = f"{base_url}{board_path}{ext_path}" if ext_path.startswith("/") else ext_path

        jobs.append({
            "title": title,
            "company": company_name,
            "location": location,
            "url": job_url,
            "is_remote": 1,
            "department": "",
            "description": None,
            "date_posted": _parse_workday_posted(posting.get("postedOn", "")),
            "date_found": _now(),
            "last_seen": _now(),
            "source_url": careers_url,
        })

    return ScrapeResult(
        jobs,
        total_found=len(all_postings),
        not_remote=not_remote,
        keyword_filtered=keyword_filtered,
    )


# ---------------------------------------------------------------------------
# Ashby (public job board API)
# ---------------------------------------------------------------------------

def scrape_ashby(slug: str, company_name: str, source_url: str) -> list[dict]:
    """
    Ashby exposes a public job board API at:
      GET https://api.ashbyhq.com/posting-api/job-board/{slug}
    Returns all jobs in a single response (no pagination).
    """
    api_url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    print(f"  -> Ashby API: {api_url}")

    try:
        r = requests.get(
            api_url,
            headers=HEADERS,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as exc:
        print(f"  Error: {exc}")
        raise ScrapeError(str(exc)) from exc

    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ScrapeError("Ashby returned an unexpected response shape")

    all_postings = data.get("jobs", [])
    print(f"  Total listings: {len(all_postings)}")

    jobs = []
    not_remote = 0
    keyword_filtered = 0
    for posting in all_postings:
        title = posting.get("title", "")
        if not _matches_role(title):
            keyword_filtered += 1
            continue

        # A posting may list an office as its primary location and a US-remote
        # option in secondaryLocations. Keep each label paired with its
        # structured country so locations from different countries cannot be
        # combined into a false remote-US match.
        location_options = [
            (posting.get("location", ""), posting.get("address") or {}),
        ]
        for secondary in posting.get("secondaryLocations") or []:
            location_options.append((
                secondary.get("location", ""),
                secondary.get("address") or {},
            ))

        def is_us_option(option: tuple[str, dict]) -> bool:
            label, address = option
            country = (
                (address.get("postalAddress") or {})
                .get("addressCountry", "")
            )
            if country:
                return _is_us_workable(country)
            return _is_us_workable(label)

        us_location_options = [
            option for option in location_options if is_us_option(option)
        ]
        if not us_location_options:
            not_remote += 1
            continue

        # Remote check — Ashby provides workplaceType and isRemote
        workplace = (posting.get("workplaceType") or "").lower().strip()
        is_remote_flag = posting.get("isRemote", False)
        if workplace in ("hybrid", "onsite", "on-site"):
            not_remote += 1
            continue
        if not is_remote_flag and workplace != "remote":
            # Fall back to US location labels only. A title such as
            # "Distributed Data Systems" describes the technology, not a
            # remote workplace.
            if not any(
                _is_remote("", label)
                for label, _address in us_location_options
            ):
                not_remote += 1
                continue

        location = "; ".join(dict.fromkeys(
            label for label, _address in location_options if label
        ))
        job_url = posting.get("jobUrl") or posting.get("applyUrl") or ""

        jobs.append({
            "title": title,
            "company": company_name,
            "location": location,
            "url": job_url,
            "is_remote": 1,
            "department": posting.get("department", "") or posting.get("team", ""),
            "description": None,
            "date_posted": posting.get("publishedAt"),
            "date_found": _now(),
            "last_seen": _now(),
            "source_url": source_url,
        })

    return ScrapeResult(
        jobs,
        total_found=len(all_postings),
        not_remote=not_remote,
        keyword_filtered=keyword_filtered,
    )


# ---------------------------------------------------------------------------
# iCIMS / Phenom (used by GitHub Careers)
# ---------------------------------------------------------------------------

def scrape_icims_phenom(careers_url: str, company_name: str) -> list[dict]:
    """
    Some companies (e.g. GitHub) expose jobs via a Phenom-hosted iCIMS JSON API
    at {base}/api/jobs.  Pagination is page-based (10 per page).
    The careers_url query string should pre-filter for remote + US jobs.
    """
    from urllib.parse import urlparse, parse_qs, urlencode

    parsed = urlparse(careers_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    api_url = f"{base_url}/api/jobs"

    # Carry forward all query params from the careers URL into the API call
    qs = parse_qs(parsed.query, keep_blank_values=True)
    base_params = {k: v[0] for k, v in qs.items()}

    print(f"  -> iCIMS/Phenom API: {api_url}")

    all_jobs_raw = []
    page = 1
    while True:
        params = {**base_params, "page": page}
        try:
            r = requests.get(
                api_url,
                params=params,
                headers=HEADERS,
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            r.raise_for_status()
            d = r.json()
        except requests.RequestException as exc:
            print(f"  Error: {exc}")
            raise ScrapeError(f"Page {page} failed: {exc}") from exc

        if "totalCount" not in d or not isinstance(d.get("jobs"), list):
            raise ScrapeError(
                f"iCIMS/Phenom page {page} returned an unexpected response shape"
            )

        total = d.get("totalCount", 0)
        batch = d.get("jobs", [])
        if not batch:
            break
        all_jobs_raw.extend(batch)
        if page == 1:
            print(f"  Total matches: {total}")
        if len(all_jobs_raw) >= total:
            break
        page += 1

    jobs = []
    not_remote = 0
    keyword_filtered = 0
    for entry in all_jobs_raw:
        data = entry.get("data", {})
        title = data.get("title", "")
        if not _matches_role(title):
            keyword_filtered += 1
            continue

        location = data.get("location_name", "") or data.get("full_location", "")
        country_code = data.get("country_code", "")

        # US filter — trust country_code field if available, else fall back to text
        if country_code and country_code != "US":
            not_remote += 1
            continue
        if not country_code and not _is_us_workable(location):
            not_remote += 1
            continue

        req_id = data.get("req_id") or data.get("slug", "")
        job_url = f"{base_url}/careers-home/jobs/{req_id}" if req_id else ""

        # posted_date is a full ISO datetime string
        date_posted = data.get("posted_date") or data.get("create_date") or None

        jobs.append({
            "title": title,
            "company": company_name,
            "location": location,
            "url": job_url,
            "is_remote": 1,
            "department": (data.get("categories") or [{}])[0].get("name", "") if data.get("categories") else "",
            "description": None,
            "date_posted": date_posted,
            "date_found": _now(),
            "last_seen": _now(),
            "source_url": careers_url,
        })

    return ScrapeResult(
        jobs,
        total_found=len(all_jobs_raw),
        not_remote=not_remote,
        keyword_filtered=keyword_filtered,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def scrape_company(company: dict) -> list[dict]:
    name = company["name"]
    url = company["careers_url"]

    print(f"\n[{name}] {url[:80]}")

    # Use explicit overrides from config if provided, else auto-detect
    if "ats" in company:
        ats_type = company["ats"]
        board_id = company.get("board_id", "")
        print(f"  ATS (config): {ats_type}" + (f"  board_id: {board_id}" if board_id else ""))
    else:
        ats_type, board_id = detect_ats(url)
        print(f"  ATS (detected): {ats_type}  board_id: {board_id or '—'}")

    if ats_type == "greenhouse":
        return scrape_greenhouse(board_id, name, url, us_only=company.get("us_only", False))
    elif ats_type == "lever":
        return scrape_lever(board_id, name, url)
    elif ats_type == "eightfold":
        return scrape_eightfold(url, name)
    elif ats_type == "eightfold_v2":
        return scrape_eightfold_v2(url, name)
    elif ats_type == "workday":
        return scrape_workday(url, name, us_only=company.get("us_only", False))
    elif ats_type == "icims_phenom":
        return scrape_icims_phenom(url, name)
    elif ats_type == "clinchtalent":
        return scrape_clinchtalent(url, name)
    elif ats_type == "ashby":
        return scrape_ashby(company.get("board_id", name.lower()), name, url)
    else:
        message = (
            f"Unsupported ATS '{ats_type}' for {name}. Set a supported 'ats' "
            "value in config."
        )
        print(f"  {message}")
        raise ScrapeError(message)
