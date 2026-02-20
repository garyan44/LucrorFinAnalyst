import streamlit as st
import requests
import re
import time
from urllib.parse import quote_plus, urljoin

st.set_page_config(page_title="Annual Report Finder", page_icon="📊", layout="wide")

st.title("📊 Annual Report Finder")
st.markdown("Find 10-K, 20-F, or annual report PDFs for any public company.")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
SEC_HEADERS = {"User-Agent": "annual-report-finder research@example.com"}


# ─────────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────────

def safe_str(val):
    if val is None:
        return ""
    return str(val)


def parse_entity_name(src: dict) -> str:
    raw = src.get("display_names") or src.get("entity_name") or ""
    if isinstance(raw, list) and raw:
        first = raw[0]
        if isinstance(first, dict):
            return first.get("name", "")
        if isinstance(first, str):
            return first
    if isinstance(raw, str):
        return raw
    return ""


# ─────────────────────────────────────────────────────────────────
# SEC EDGAR – EFTS full-text search
# ─────────────────────────────────────────────────────────────────

def search_sec_efts(company_name: str) -> list:
    results = []
    try:
        url = (
            "https://efts.sec.gov/LATEST/search-index"
            f"?q={quote_plus(company_name)}"
            "&dateRange=custom&startdt=2019-01-01"
            "&forms=10-K,20-F,40-F"
        )
        r = requests.get(url, headers=SEC_HEADERS, timeout=15)
        if r.status_code != 200:
            return results
        data = r.json()
        hits = data.get("hits", {}).get("hits", [])
        for hit in hits[:8]:
            if not isinstance(hit, dict):
                continue
            src = hit.get("_source")
            if not isinstance(src, dict):
                continue
            accession = safe_str(src.get("accession_no", "")).replace("-", "")
            cik = safe_str(src.get("entity_id") or src.get("cik") or "")
            form = safe_str(src.get("form_type", ""))
            period = safe_str(src.get("period_of_report") or src.get("file_date") or "")
            entity = parse_entity_name(src)
            if accession and cik:
                results.append({
                    "source": "SEC EDGAR",
                    "entity": entity,
                    "form": form,
                    "period": period,
                    "cik": cik,
                    "accession": accession,
                })
    except Exception as e:
        st.warning(f"SEC EDGAR search error: {e}")
    return results


# ─────────────────────────────────────────────────────────────────
# SEC EDGAR – ticker lookup → CIK → submissions
# ─────────────────────────────────────────────────────────────────

def search_sec_company_tickers(company_name: str) -> list:
    try:
        r = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=SEC_HEADERS, timeout=15,
        )
        if r.status_code != 200:
            return []
        needle = company_name.lower()
        matches = []
        for val in r.json().values():
            if not isinstance(val, dict):
                continue
            title = safe_str(val.get("title", "")).lower()
            if needle in title or title in needle:
                matches.append(val)
        return matches[:5]
    except Exception as e:
        st.warning(f"Ticker lookup error: {e}")
        return []


def get_latest_filing_for_cik(cik, preferred_forms=("10-K", "20-F", "40-F")):
    try:
        cik_str = safe_str(cik).zfill(10)
        r = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik_str}.json",
            headers=SEC_HEADERS, timeout=15,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        entity_name = safe_str(data.get("name", ""))
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        dates = recent.get("filingDate", [])
        for i, form in enumerate(forms):
            if form in preferred_forms:
                accession = safe_str(accessions[i]).replace("-", "")
                return {
                    "source": "SEC EDGAR",
                    "entity": entity_name,
                    "form": form,
                    "period": safe_str(dates[i]),
                    "cik": safe_str(cik),
                    "accession": accession,
                }
    except Exception as e:
        st.warning(f"CIK lookup error: {e}")
    return None


# ─────────────────────────────────────────────────────────────────
# Resolve SEC filing index → best document URL
# ─────────────────────────────────────────────────────────────────

def get_doc_url_from_filing(cik: str, accession: str):
    """Return (url, filetype) for the best document in an SEC filing."""
    try:
        idx_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/index.json"
        r = requests.get(idx_url, headers=SEC_HEADERS, timeout=15)
        if r.status_code != 200:
            return None, None
        data = r.json()
        files = data.get("directory", {}).get("item", [])
        base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/"

        # 1. PDF first
        for f in files:
            name = safe_str(f.get("name", ""))
            if name.lower().endswith(".pdf"):
                return base + name, "pdf"

        # 2. HTM that looks like the main filing
        keywords = ("10k", "10-k", "20f", "20-f", "40f", "40-f", "annual", "form")
        for f in files:
            name = safe_str(f.get("name", ""))
            if name.lower().endswith(".htm") and any(k in name.lower() for k in keywords):
                return base + name, "htm"

        # 3. Any HTM that isn't the index
        for f in files:
            name = safe_str(f.get("name", ""))
            if name.lower().endswith(".htm") and "index" not in name.lower():
                return base + name, "htm"
    except Exception:
        pass
    return None, None


# ─────────────────────────────────────────────────────────────────
# Web search (DuckDuckGo) – works for ANY company worldwide
# ─────────────────────────────────────────────────────────────────

def ddg_search_links(query: str) -> list[str]:
    """Return raw href links from DuckDuckGo HTML results."""
    try:
        r = requests.get(
            f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
            headers=HEADERS, timeout=12,
        )
        if r.status_code != 200:
            return []
        # DuckDuckGo wraps real links in uddg= param
        links = re.findall(r'uddg=([^&"\'>\s]+)', r.text)
        decoded = []
        for l in links:
            from urllib.parse import unquote
            decoded.append(unquote(l))
        # Also grab plain hrefs
        plain = re.findall(r'href=["\'](https?://[^"\']+)["\']', r.text)
        return decoded + plain
    except Exception:
        return []


def search_web_for_reports(company_name: str) -> list:
    results = []
    seen_urls = set()

    queries = [
        f"{company_name} annual report 2023 2024 filetype:pdf",
        f"{company_name} annual report PDF investor relations",
        f"{company_name} 10-K 20-F annual report SEC filing",
        f"{company_name} \"annual report\" site:ir. OR site:investors.",
    ]

    for query in queries:
        links = ddg_search_links(query)
        for link in links:
            if not link.startswith("http") or "duckduckgo" in link:
                continue
            if link in seen_urls:
                continue
            seen_urls.add(link)

            ftype = "page"
            if link.lower().endswith(".pdf"):
                ftype = "pdf"
            elif any(k in link.lower() for k in ["annualreport", "annual-report", "annual_report"]):
                ftype = "page"
            elif any(k in link.lower() for k in ["10-k", "10k", "20-f", "20f", "40-f", "40f"]):
                ftype = "page"
            elif any(k in link.lower() for k in ["investor", "ir.", "/ir/", "financials", "reports"]):
                ftype = "page"
            else:
                continue  # skip irrelevant links

            results.append({
                "source": "Web Search",
                "entity": company_name,
                "form": "PDF" if ftype == "pdf" else "Page",
                "period": "",
                "url": link,
                "file_type": ftype,
            })

        if len(results) >= 10:
            break
        time.sleep(0.4)

    # Also try scraping investor relations page for PDF links
    ir_pages = [r for r in results if r["file_type"] == "page"][:2]
    for page in ir_pages:
        try:
            pr = requests.get(page["url"], headers=HEADERS, timeout=10)
            if pr.status_code == 200:
                pdfs = re.findall(r'href=["\']([^"\']*\.pdf[^"\']*)["\']', pr.text, re.I)
                for pdf in pdfs[:5]:
                    full = urljoin(page["url"], pdf)
                    if full not in seen_urls:
                        seen_urls.add(full)
                        results.append({
                            "source": "Web Search (scraped)",
                            "entity": company_name,
                            "form": "PDF",
                            "period": "",
                            "url": full,
                            "file_type": "pdf",
                        })
        except Exception:
            pass

    return results[:15]


# ─────────────────────────────────────────────────────────────────
# Scoring – higher = more likely to have yearly revenue table
# ─────────────────────────────────────────────────────────────────

def score_result(res: dict) -> int:
    score = 0
    if res.get("source") == "SEC EDGAR":
        score += 60
    elif "scraped" in res.get("source", ""):
        score += 20

    form = safe_str(res.get("form", "")).upper()
    if form in ("10-K", "20-F", "40-F", "10-K/A", "20-F/A"):
        score += 40

    period = safe_str(res.get("period", ""))
    if "2024" in period:
        score += 25
    elif "2023" in period:
        score += 20
    elif "2022" in period:
        score += 10

    url = safe_str(res.get("url", "")).lower()
    if url.endswith(".pdf"):
        score += 20
    if any(k in url for k in ["annualreport", "annual-report", "annual_report"]):
        score += 10
    if any(k in url for k in ["10-k", "10k", "20-f", "20f"]):
        score += 10

    return score


# ─────────────────────────────────────────────────────────────────
# Download helpers
# ─────────────────────────────────────────────────────────────────

def fetch_as_pdf_bytes(url: str, file_type: str):
    """
    - If it's a PDF → download directly.
    - If it's an HTM SEC filing → download the HTM bytes (browser-renderable).
    Returns (bytes, mime_type, filename_extension).
    """
    try:
        r = requests.get(url, headers=SEC_HEADERS, timeout=45, stream=True)
        if r.status_code == 200:
            content_type = r.headers.get("content-type", "").lower()
            if "pdf" in content_type or url.lower().endswith(".pdf"):
                return r.content, "application/pdf", "pdf"
            else:
                return r.content, "text/html", "html"
    except Exception as e:
        st.error(f"Download error: {e}")
    return None, None, None


# ─────────────────────────────────────────────────────────────────
# Streamlit UI
# ─────────────────────────────────────────────────────────────────

company_name = st.text_input(
    "🔍 Enter company name:",
    placeholder="e.g. Apple, Bombardier, Aegea, Samsung, Toyota, Nestle",
)
search_btn = st.button("Find Annual Report", type="primary")

if search_btn and company_name.strip():
    all_results = []

    # 1. SEC EDGAR: EFTS full-text search
    with st.spinner("🔎 Searching SEC EDGAR (full-text)..."):
        for res in search_sec_efts(company_name):
            pdf_url, ftype = get_doc_url_from_filing(res["cik"], res["accession"])
            res["url"] = pdf_url or ""
            res["file_type"] = ftype or ""
            res["score"] = score_result(res)
            all_results.append(res)

    # 2. SEC EDGAR: ticker lookup fallback
    if not any(r.get("url") for r in all_results if r["source"] == "SEC EDGAR"):
        with st.spinner("🔎 Searching SEC EDGAR (ticker match)..."):
            for match in search_sec_company_tickers(company_name)[:3]:
                cik = match.get("cik_str") or match.get("cik")
                filing = get_latest_filing_for_cik(cik)
                if filing:
                    pdf_url, ftype = get_doc_url_from_filing(filing["cik"], filing["accession"])
                    filing["url"] = pdf_url or ""
                    filing["file_type"] = ftype or ""
                    filing["score"] = score_result(filing)
                    all_results.append(filing)

    # 3. Web search (always run — catches non-US / private companies)
    with st.spinner("🌐 Searching web for annual report PDFs..."):
        for res in search_web_for_reports(company_name):
            res["score"] = score_result(res)
            all_results.append(res)

    # Sort by score
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Deduplicate by URL
    seen, deduped = set(), []
    for res in all_results:
        key = res.get("url") or f"{res.get('cik')}_{res.get('accession')}"
        if key not in seen:
            seen.add(key)
            deduped.append(res)
    all_results = deduped

    if not all_results:
        st.error("❌ No results found. Try a different spelling or add the country (e.g. 'Aegea Brazil').")
    else:
        st.success(f"✅ Found {len(all_results)} result(s). Best match shown first.")

        best = all_results[0]
        st.subheader("⭐ Best Match")

        with st.container(border=True):
            col_info, col_btn = st.columns([3, 1])

            with col_info:
                st.markdown(f"**Source:** {best.get('source', 'N/A')}")
                if best.get("entity"):
                    st.markdown(f"**Company:** {best['entity']}")
                if best.get("form"):
                    st.markdown(f"**Filing Type:** `{best['form']}`")
                if best.get("period"):
                    st.markdown(f"**Period/Date:** {best['period']}")
                if best.get("url"):
                    u = best["url"]
                    display = u[:90] + "..." if len(u) > 90 else u
                    st.markdown(f"**URL:** [{display}]({u})")
                else:
                    st.info("No direct document URL resolved. Use the button to browse SEC EDGAR.")

            with col_btn:
                if best.get("url"):
                    # Open in browser – no key param
                    st.link_button("🔗 Open in Browser", best["url"], use_container_width=True)

                    # Download button for ALL file types (pdf and htm)
                    if st.button("⬇️ Download File", use_container_width=True, key="dl_best"):
                        with st.spinner("Downloading..."):
                            data_bytes, mime, ext = fetch_as_pdf_bytes(
                                best["url"], best.get("file_type", "")
                            )
                            if data_bytes:
                                fname = f"{company_name.strip().replace(' ', '_')}_annual_report.{ext}"
                                st.download_button(
                                    label=f"💾 Save {ext.upper()}",
                                    data=data_bytes,
                                    file_name=fname,
                                    mime=mime,
                                    use_container_width=True,
                                    key="save_best",
                                )
                            else:
                                st.error("Download failed — use 'Open in Browser' instead.")
                else:
                    # No URL but have CIK → link to EDGAR filing page
                    cik = best.get("cik", "")
                    if cik:
                        edgar_url = (
                            f"https://www.sec.gov/cgi-bin/browse-edgar"
                            f"?action=getcompany&CIK={cik}"
                            f"&type={best.get('form', '10-K')}&dateb=&owner=include&count=10"
                        )
                        st.link_button("🔗 View on SEC EDGAR", edgar_url, use_container_width=True)

        # ── All other results ──
        if len(all_results) > 1:
            st.subheader(f"📋 All Results ({len(all_results)})")
            for i, res in enumerate(all_results[1:], 2):
                period_str = f" | {res['period']}" if res.get("period") else ""
                label = f"#{i} — {res.get('source')} | {res.get('form', 'Doc')}{period_str} | Score: {res.get('score', 0)}"
                with st.expander(label):
                    if res.get("entity"):
                        st.write(f"**Company:** {res['entity']}")
                    url = res.get("url", "")
                    if url:
                        st.write(f"**URL:** {url}")
                        # FIX: st.link_button does NOT accept key=
                        col1, col2 = st.columns(2)
                        with col1:
                            st.link_button("🔗 Open", url)
                        with col2:
                            if st.button("⬇️ Download", key=f"dl_{i}"):
                                with st.spinner("Downloading..."):
                                    data_bytes, mime, ext = fetch_as_pdf_bytes(
                                        url, res.get("file_type", "")
                                    )
                                    if data_bytes:
                                        fname = f"{company_name.strip().replace(' ', '_')}_report_{i}.{ext}"
                                        st.download_button(
                                            label=f"💾 Save {ext.upper()}",
                                            data=data_bytes,
                                            file_name=fname,
                                            mime=mime,
                                            key=f"save_{i}",
                                        )
                                    else:
                                        st.error("Download failed.")
                    elif res.get("cik"):
                        edgar_url = (
                            f"https://www.sec.gov/cgi-bin/browse-edgar"
                            f"?action=getcompany&CIK={res['cik']}"
                            f"&type={res.get('form','10-K')}&dateb=&owner=include&count=10"
                        )
                        st.link_button("View on SEC EDGAR", edgar_url)

with st.expander("ℹ️ Tips & Notes"):
    st.markdown("""
    - **US public companies** (NYSE/NASDAQ) file **10-K** with the SEC — always contain revenue tables.
    - **Canadian companies** often file **40-F** with the SEC (e.g. Bombardier).
    - **Foreign private issuers** file **20-F** with the SEC (e.g. Samsung, Toyota, Nestle).
    - **Private or non-US companies** (e.g. Aegea) are found via web search — results link to their investor relations pages.
    - If no results: try adding the country → `"Aegea Brazil"`, or `"Bombardier Canada"`.
    - The **Download** button saves a PDF or HTML file. HTML filings are the full SEC document — open in your browser to read.
    - `st.link_button` does not accept a `key` parameter — this version fixes that crash.
    """)
