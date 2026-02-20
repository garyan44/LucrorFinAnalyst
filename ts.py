import streamlit as st
import requests
import re
import time
from urllib.parse import quote_plus

st.set_page_config(page_title="Annual Report Finder", page_icon="📊", layout="wide")

st.title("📊 Annual Report Finder")
st.markdown("Find 10-K, 20-F, or annual report PDFs for any public company.")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
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
    """
    EDGAR display_names can be:
      - list of dicts  [{"name": "Apple Inc", ...}]
      - list of strings ["Apple Inc"]
      - a plain string  "Apple Inc"
      - absent / None
    """
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
            "&dateRange=custom&startdt=2020-01-01"
            "&forms=10-K,20-F"
        )
        r = requests.get(url, headers=SEC_HEADERS, timeout=15)
        if r.status_code != 200:
            return results

        data = r.json()
        hits = data.get("hits", {}).get("hits", [])

        for hit in hits[:6]:
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
            headers=SEC_HEADERS,
            timeout=15,
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


def get_latest_filing_for_cik(cik, preferred_forms=("10-K", "20-F")):
    try:
        cik_str = safe_str(cik).zfill(10)
        r = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik_str}.json",
            headers=SEC_HEADERS,
            timeout=15,
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
        st.warning(f"CIK submission lookup error: {e}")
    return None


# ─────────────────────────────────────────────────────────────────
# Resolve filing → actual document URL
# ─────────────────────────────────────────────────────────────────

def get_pdf_url_from_filing(cik: str, accession: str):
    """Return (url, filetype) for the best document in a filing."""
    try:
        idx_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/index.json"
        r = requests.get(idx_url, headers=SEC_HEADERS, timeout=15)
        if r.status_code != 200:
            return None, None
        data = r.json()
        files = data.get("directory", {}).get("item", [])
        base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/"

        # 1. PDF
        for f in files:
            name = safe_str(f.get("name", ""))
            if name.lower().endswith(".pdf"):
                return base + name, "pdf"

        # 2. Named HTM that looks like the main filing
        keywords = ("10k", "10-k", "20f", "20-f", "annual", "form")
        for f in files:
            name = safe_str(f.get("name", ""))
            if name.lower().endswith(".htm") and any(k in name.lower() for k in keywords):
                return base + name, "htm"

        # 3. Any HTM that isn't an index
        for f in files:
            name = safe_str(f.get("name", ""))
            if name.lower().endswith(".htm") and "index" not in name.lower():
                return base + name, "htm"
    except Exception:
        pass
    return None, None


# ─────────────────────────────────────────────────────────────────
# Web / DuckDuckGo fallback
# ─────────────────────────────────────────────────────────────────

def search_web_for_pdf(company_name: str) -> list:
    results = []
    queries = [
        f"{company_name} annual report 2023 2024 filetype:pdf",
        f"{company_name} 10-K annual report investor relations",
    ]
    for query in queries:
        try:
            url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            html = r.text

            for link in re.findall(r'href=["\']([^"\']*\.pdf[^"\']*)["\']', html, re.I):
                if link.startswith("http") and "duckduckgo" not in link:
                    results.append({
                        "source": "Web Search",
                        "entity": company_name,
                        "form": "PDF",
                        "period": "",
                        "url": link,
                        "file_type": "pdf",
                    })

            for link in re.findall(r'href=["\'](https?://[^"\']+)["\']', html):
                if any(k in link.lower() for k in ["annualreport", "annual-report", "10-k", "20-f", "investor"]):
                    if "duckduckgo" not in link:
                        results.append({
                            "source": "Web Search",
                            "entity": company_name,
                            "form": "Page",
                            "period": "",
                            "url": link,
                            "file_type": "page",
                        })
        except Exception:
            pass
        time.sleep(0.5)

    # Deduplicate by URL
    seen, deduped = set(), []
    for res in results:
        u = res.get("url", "")
        if u and u not in seen:
            seen.add(u)
            deduped.append(res)
    return deduped[:8]


# ─────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────

def score_result(res: dict) -> int:
    score = 0
    if res.get("source") == "SEC EDGAR":
        score += 50
    form = safe_str(res.get("form", "")).upper()
    if form in ("10-K", "20-F", "10-K/A", "20-F/A"):
        score += 30
    period = safe_str(res.get("period", ""))
    if "2024" in period:
        score += 25
    elif "2023" in period:
        score += 20
    elif "2022" in period:
        score += 10
    if safe_str(res.get("url", "")).lower().endswith(".pdf"):
        score += 15
    return score


# ─────────────────────────────────────────────────────────────────
# Download helper
# ─────────────────────────────────────────────────────────────────

def download_pdf(url: str):
    try:
        r = requests.get(url, headers=SEC_HEADERS, timeout=30, stream=True)
        if r.status_code == 200:
            return r.content
    except Exception as e:
        st.error(f"Download error: {e}")
    return None


# ─────────────────────────────────────────────────────────────────
# Streamlit UI
# ─────────────────────────────────────────────────────────────────

company_name = st.text_input(
    "🔍 Enter company name:",
    placeholder="e.g. Apple, Samsung, Toyota, Nestle",
)
search_btn = st.button("Find Annual Report", type="primary")

if search_btn and company_name.strip():
    all_results = []

    # SEC EDGAR: EFTS full-text search
    with st.spinner("🔎 Searching SEC EDGAR (full-text)..."):
        for res in search_sec_efts(company_name):
            pdf_url, ftype = get_pdf_url_from_filing(res["cik"], res["accession"])
            res["url"] = pdf_url or ""
            res["file_type"] = ftype or ""
            res["score"] = score_result(res)
            all_results.append(res)

    # SEC EDGAR: ticker → CIK → submissions (fallback)
    if not any(r["source"] == "SEC EDGAR" and r.get("url") for r in all_results):
        with st.spinner("🔎 Searching SEC EDGAR (ticker lookup)..."):
            for match in search_sec_company_tickers(company_name)[:3]:
                cik = match.get("cik_str") or match.get("cik")
                filing = get_latest_filing_for_cik(cik)
                if filing:
                    pdf_url, ftype = get_pdf_url_from_filing(filing["cik"], filing["accession"])
                    filing["url"] = pdf_url or ""
                    filing["file_type"] = ftype or ""
                    filing["score"] = score_result(filing)
                    all_results.append(filing)

    # Web search fallback
    with st.spinner("🌐 Searching web for PDFs..."):
        for res in search_web_for_pdf(company_name):
            res["score"] = score_result(res)
            all_results.append(res)

    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)

    if not all_results:
        st.error("❌ No results found. Try a different company name or check spelling.")
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
                    st.link_button("🔗 Open in Browser", best["url"], use_container_width=True)
                    if best.get("file_type") == "pdf" or best["url"].lower().endswith(".pdf"):
                        if st.button("⬇️ Download PDF", use_container_width=True, key="dl_best"):
                            with st.spinner("Downloading..."):
                                pdf_bytes = download_pdf(best["url"])
                                if pdf_bytes:
                                    fname = f"{company_name.strip().replace(' ', '_')}_annual_report.pdf"
                                    st.download_button(
                                        label="💾 Save PDF",
                                        data=pdf_bytes,
                                        file_name=fname,
                                        mime="application/pdf",
                                        use_container_width=True,
                                        key="save_best",
                                    )
                                else:
                                    st.error("Download failed — use 'Open in Browser'.")
                else:
                    cik = best.get("cik", "")
                    if cik:
                        edgar_url = (
                            f"https://www.sec.gov/cgi-bin/browse-edgar"
                            f"?action=getcompany&CIK={cik}"
                            f"&type={best.get('form', '10-K')}&dateb=&owner=include&count=10"
                        )
                        st.link_button("🔗 View on SEC EDGAR", edgar_url, use_container_width=True)

        if len(all_results) > 1:
            st.subheader(f"📋 All Results ({len(all_results)})")
            for i, res in enumerate(all_results[1:], 2):
                label = (
                    f"#{i} — {res.get('source')} | "
                    f"{res.get('form', 'Doc')} | "
                    f"{res.get('period', '')} | "
                    f"Score: {res.get('score', 0)}"
                )
                with st.expander(label):
                    if res.get("entity"):
                        st.write(f"**Company:** {res['entity']}")
                    url = res.get("url", "")
                    if url:
                        st.write(f"**URL:** {url}")
                        st.link_button("Open Link", url, key=f"link_{i}")
                    elif res.get("cik"):
                        edgar_url = (
                            f"https://www.sec.gov/cgi-bin/browse-edgar"
                            f"?action=getcompany&CIK={res['cik']}"
                            f"&type={res.get('form', '10-K')}&dateb=&owner=include&count=10"
                        )
                        st.link_button("View on SEC EDGAR", edgar_url, key=f"edgar_{i}")

with st.expander("ℹ️ Tips & Notes"):
    st.markdown("""
    - **US public companies** (NYSE/NASDAQ) file **10-K** with the SEC — always contain revenue tables.
    - **Foreign private issuers** file **20-F** with the SEC (e.g. Samsung, Toyota, Nestle).
    - For **private or non-US companies**, the tool falls back to web search for investor relations PDFs.
    - If the download button fails, click **"Open in Browser"** and save manually.
    - Try name variations: `"Apple"` vs `"Apple Inc"`, `"Samsung"` vs `"Samsung Electronics"`.
    """)
