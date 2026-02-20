import streamlit as st
import requests
import re
import time
from urllib.parse import urljoin, urlparse, quote_plus

st.set_page_config(page_title="Annual Report Finder", page_icon="📊", layout="wide")

st.title("📊 Annual Report Finder")
st.markdown("Find 10-K, 20-F, or annual report PDFs for any public company.")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ── SEC EDGAR helpers ──────────────────────────────────────────────────────────

def search_sec_edgar(company_name):
    """Search SEC EDGAR full-text search for 10-K / 20-F filings."""
    results = []
    try:
        # Company search
        url = f"https://efts.sec.gov/LATEST/search-index?q=%22{quote_plus(company_name)}%22&dateRange=custom&startdt=2022-01-01&forms=10-K,20-F"
        r = requests.get(url, headers={"User-Agent": "research@example.com"}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            hits = data.get("hits", {}).get("hits", [])
            for hit in hits[:5]:
                src = hit.get("_source", {})
                accession = src.get("accession_no", "").replace("-", "")
                cik = src.get("entity_id", "")
                form = src.get("form_type", "")
                entity = src.get("display_names", [{}])
                entity_name = entity[0].get("name", "") if entity else ""
                period = src.get("period_of_report", "")
                if accession and cik:
                    filing_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=5"
                    # Direct index link
                    idx_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/index.json"
                    results.append({
                        "source": "SEC EDGAR",
                        "entity": entity_name,
                        "form": form,
                        "period": period,
                        "cik": cik,
                        "accession": accession,
                        "index_url": idx_url,
                    })
    except Exception as e:
        st.warning(f"SEC EDGAR search error: {e}")
    return results


def get_pdf_from_sec_filing(cik, accession):
    """Given CIK and accession number, find the PDF or HTM filing document."""
    try:
        idx_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/index.json"
        r = requests.get(idx_url, headers={"User-Agent": "research@example.com"}, timeout=10)
        if r.status_code != 200:
            return None, None
        data = r.json()
        files = data.get("directory", {}).get("item", [])
        
        # Prefer PDF
        for f in files:
            name = f.get("name", "")
            if name.lower().endswith(".pdf"):
                url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{name}"
                return url, "pdf"
        
        # Fallback: main HTM document
        for f in files:
            name = f.get("name", "")
            if name.lower().endswith(".htm") and any(k in name.lower() for k in ["10k", "20f", "annual", "form"]):
                url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{name}"
                return url, "htm"
        
        # Any HTM
        for f in files:
            name = f.get("name", "")
            if name.lower().endswith(".htm") and "index" not in name.lower():
                url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{name}"
                return url, "htm"
    except Exception as e:
        pass
    return None, None


def search_sec_company_tickers(company_name):
    """Search company tickers to get CIK."""
    try:
        r = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": "research@example.com"},
            timeout=10
        )
        if r.status_code == 200:
            tickers = r.json()
            company_lower = company_name.lower()
            matches = []
            for key, val in tickers.items():
                if company_lower in val.get("title", "").lower():
                    matches.append(val)
            return matches[:5]
    except:
        pass
    return []


def get_latest_filing_for_cik(cik, form_type="10-K"):
    """Get latest 10-K or 20-F filing for a CIK."""
    try:
        cik_str = str(cik).zfill(10)
        url = f"https://data.sec.gov/submissions/CIK{cik_str}.json"
        r = requests.get(url, headers={"User-Agent": "research@example.com"}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            filings = data.get("filings", {}).get("recent", {})
            forms = filings.get("form", [])
            accessions = filings.get("accessionNumber", [])
            dates = filings.get("filingDate", [])
            entity_name = data.get("name", "")
            
            for i, form in enumerate(forms):
                if form in ["10-K", "20-F", "10-K/A", "20-F/A"]:
                    accession = accessions[i].replace("-", "")
                    return {
                        "entity": entity_name,
                        "form": form,
                        "period": dates[i],
                        "cik": cik,
                        "accession": accession,
                    }
    except:
        pass
    return None


# ── Google / Bing fallback search ──────────────────────────────────────────────

def search_web_for_pdf(company_name):
    """Use SerpAPI-style or direct Google search for annual report PDFs."""
    results = []
    queries = [
        f"{company_name} annual report 2023 2024 filetype:pdf",
        f"{company_name} 10-K 2023 filetype:pdf",
        f"{company_name} 20-F 2023 filetype:pdf",
        f"{company_name} annual report PDF download investor relations",
    ]
    
    for query in queries[:2]:
        try:
            # Using DuckDuckGo HTML
            url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                # Extract PDF links
                pdf_links = re.findall(r'href=["\']([^"\']*\.pdf[^"\']*)["\']', r.text, re.IGNORECASE)
                for link in pdf_links[:3]:
                    if link.startswith("http") and "duckduckgo" not in link:
                        results.append({
                            "source": "Web Search",
                            "url": link,
                            "type": "pdf",
                            "label": f"PDF found via web search: {link[:80]}..."
                        })
                
                # Extract result links mentioning annual report
                result_links = re.findall(r'href=["\'](https?://[^"\']+)["\']', r.text)
                for link in result_links:
                    if any(k in link.lower() for k in ["annualreport", "annual-report", "10-k", "20-f", "investor"]):
                        if "duckduckgo" not in link and link not in [r.get("url") for r in results]:
                            results.append({
                                "source": "Web Search",
                                "url": link,
                                "type": "page",
                                "label": f"Investor/Report page: {link[:80]}"
                            })
        except Exception as e:
            pass
        time.sleep(0.5)
    
    return results[:8]


# ── Scoring: check if URL/content likely has revenue tables ───────────────────

def score_result(result):
    """Heuristic score: prefer 10-K/20-F from SEC, recent years, PDFs."""
    score = 0
    if result.get("source") == "SEC EDGAR":
        score += 50
    form = result.get("form", "").upper()
    if form in ["10-K", "20-F"]:
        score += 30
    period = result.get("period", "")
    if "2023" in period or "2024" in period:
        score += 20
    elif "2022" in period:
        score += 10
    url = result.get("url", "")
    if url.endswith(".pdf"):
        score += 15
    return score


# ── Download helper ────────────────────────────────────────────────────────────

def download_pdf(url):
    """Download PDF bytes from URL."""
    try:
        r = requests.get(url, headers={**HEADERS, "User-Agent": "research@example.com"}, timeout=30, stream=True)
        if r.status_code == 200 and "pdf" in r.headers.get("content-type", "").lower():
            return r.content
        elif r.status_code == 200:
            # Try anyway
            return r.content
    except Exception as e:
        st.error(f"Download error: {e}")
    return None


# ── Main UI ────────────────────────────────────────────────────────────────────

company_name = st.text_input("🔍 Enter company name:", placeholder="e.g. Apple, Samsung, Toyota, Nestle")

col1, col2 = st.columns([1, 3])
with col1:
    search_btn = st.button("Find Annual Report", type="primary", use_container_width=True)

if search_btn and company_name:
    all_results = []
    
    with st.spinner("🔎 Searching SEC EDGAR..."):
        # Method 1: EDGAR full-text search
        edgar_results = search_sec_edgar(company_name)
        
        # Method 2: company ticker lookup → CIK → filings
        if not edgar_results:
            matches = search_sec_company_tickers(company_name)
            for match in matches[:3]:
                cik = match.get("cik_str") or match.get("cik")
                filing = get_latest_filing_for_cik(cik, "10-K")
                if not filing:
                    filing = get_latest_filing_for_cik(cik, "20-F")
                if filing:
                    edgar_results.append(filing)
        
        # Resolve PDF/HTM links for EDGAR results
        for res in edgar_results:
            pdf_url, ftype = get_pdf_from_sec_filing(res["cik"], res["accession"])
            res["url"] = pdf_url
            res["file_type"] = ftype
            res["score"] = score_result(res)
            if pdf_url:
                all_results.append(res)
    
    with st.spinner("🌐 Searching web for PDFs..."):
        web_results = search_web_for_pdf(company_name)
        for res in web_results:
            res["score"] = score_result(res)
            all_results.append(res)
    
    # Sort by score
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    if not all_results:
        st.error("❌ No results found. Try a different company name or check spelling.")
    else:
        st.success(f"✅ Found {len(all_results)} result(s). Best match shown first.")
        
        # ── Best result ──
        best = all_results[0]
        st.subheader("⭐ Best Match")
        
        with st.container(border=True):
            cols = st.columns([3, 1])
            with cols[0]:
                st.markdown(f"**Source:** {best.get('source', 'N/A')}")
                if best.get("entity"):
                    st.markdown(f"**Company:** {best['entity']}")
                if best.get("form"):
                    st.markdown(f"**Filing Type:** `{best['form']}`")
                if best.get("period"):
                    st.markdown(f"**Period/Date:** {best['period']}")
                if best.get("url"):
                    st.markdown(f"**URL:** [{best['url'][:80]}...]({best['url']})")
            
            with cols[1]:
                if best.get("url"):
                    st.link_button("🔗 Open in Browser", best["url"], use_container_width=True)
                    
                    # Try to download PDF
                    if best.get("file_type") == "pdf" or best["url"].lower().endswith(".pdf"):
                        if st.button("⬇️ Download PDF", use_container_width=True):
                            with st.spinner("Downloading..."):
                                pdf_bytes = download_pdf(best["url"])
                                if pdf_bytes:
                                    fname = f"{company_name.replace(' ', '_')}_annual_report.pdf"
                                    st.download_button(
                                        label="💾 Save PDF",
                                        data=pdf_bytes,
                                        file_name=fname,
                                        mime="application/pdf",
                                        use_container_width=True
                                    )
                                else:
                                    st.error("Could not download. Use 'Open in Browser' instead.")
        
        # ── All results ──
        if len(all_results) > 1:
            st.subheader(f"📋 All Results ({len(all_results)})")
            for i, res in enumerate(all_results[1:], 2):
                with st.expander(f"#{i} — {res.get('source')} | {res.get('form', 'Document')} | {res.get('period', '')} | Score: {res.get('score', 0)}"):
                    if res.get("entity"):
                        st.write(f"**Company:** {res['entity']}")
                    if res.get("url"):
                        st.write(f"**URL:** {res['url']}")
                        st.link_button("Open Link", res["url"])

# ── Tips ──────────────────────────────────────────────────────────────────────
with st.expander("ℹ️ Tips & Notes"):
    st.markdown("""
    - **US public companies** (listed on NYSE/NASDAQ) file 10-K reports with the SEC — these always contain revenue tables.
    - **Foreign private issuers** file 20-F reports with the SEC.
    - For **private or non-US companies**, the tool will search the web for investor relations PDFs.
    - If the PDF link doesn't work, use **"Open in Browser"** and download manually.
    - SEC EDGAR is the most reliable source — filings there are official and always contain financial summaries.
    - Try variations of the company name if results are poor (e.g. "Apple Inc" vs "Apple").
    """)
