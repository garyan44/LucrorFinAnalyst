import streamlit as st
from google import genai
from google.genai import types
import time
import markdown
from xhtml2pdf import pisa
import io
import re

# --- CONFIGURATION ---
st.set_page_config(
    page_title="Financial Analyst AI",
    page_icon="📊",
    layout="centered"
)

# --- API SETUP ---
# PASTE YOUR API KEY HERE
# Change this line in your code:
MY_API_KEY = st.secrets["GENAI_API_KEY"]

@st.cache_resource
def get_client():
    return genai.Client(api_key=MY_API_KEY)

# --- PDF GENERATION FUNCTION ---
def create_pdf(markdown_content):
    """
    Converts Markdown text -> HTML -> PDF binary.
    """
    # 1. Convert Markdown to HTML (using 'tables' extension)
    html_text = markdown.markdown(markdown_content, extensions=['tables'])
    
    # 2. Add Custom CSS for clean tables and fonts
    styled_html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Helvetica, sans-serif; font-size: 12px; }}
            h1 {{ color: #2c3e50; font-size: 18px; }}
            h2 {{ color: #2c3e50; font-size: 16px; margin-top: 15px; }}
            h3 {{ color: #2c3e50; font-size: 14px; margin-top: 10px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; font-weight: bold; }}
            hr {{ margin-top: 20px; margin-bottom: 20px; }}
        </style>
    </head>
    <body>
        {html_text}
    </body>
    </html>
    """
    
    # 3. Convert HTML to PDF using xhtml2pdf
    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(io.BytesIO(styled_html.encode("utf-8")), dest=pdf_buffer)
    
    if pisa_status.err:
        return None
    return pdf_buffer.getvalue()

# --- BACKEND LOGIC ---
def generate_company_report(ticker):
    client = get_client()
    
    # UPDATED PROMPT: Updated with specific boss requirements for Financial Summary
    prompt = f"""
    You are a professional Financial Credit Analyst.
    Your goal is to produce a deep-dive company credit report that matches the EXACT format below.

    ### INSTRUCTIONS:
    1.  **Search Strategy (CRITICAL):**
        -   **Ratings:** Do NOT just search for "Credit Rating". Search specifically for:
            * "{ticker} Investor Relations credit ratings"
            * "{ticker} Moody's rating press release 2024 2025"
            * "{ticker} Fitch rating action commentary"
            * Look for the company's latest **Debt Investor Presentation** or **10-K** (Liquidity/Capital Resources section).
        -   **Financials:** Search for "{ticker} Investor Presentation Q3 2025" (or latest available) to get the most recent LTM numbers.
        -   **Management & Contact:** Search for "{ticker} CEO CFO name 2025" and "{ticker} Investor Relations email address contact". Include direct email if available. Write in Clean Format using Bullet Points.

    
    2.  **Calculations (MANDATORY):**
        -   $EBITDA = Operating Income + D&A$
        -   $EBITDA Margin = EBITDA / Revenue$
        -   $FFO = Net Income + D&A$
        -   $FOCF = OCF - Capex$
        -   $Net Debt = Total Debt - Cash$
        -   $Net Leverage = Net Debt / EBITDA$
        -   $Coverage = FOCF / Net Debt$
    
    3.  **Format:** Output strictly in Markdown. Follow the One-Shot Example structure exactly.
    
    4.  **Rationale (Internal):** AFTER the main report, output a section header called `Appendix`. INCLUDE IT IN THE NEXT PAGE. In this section, detail your thought process, reasoning for credit drivers, and how you located each data point (with URLs). This is for internal use and should NOT appear in the main report.

    5.  **Transparency & Footnotes (NEW REQUIREMENT):**
        -   **After EVERY section** (Ratings, Description, Financial Summary, Key Credit Drivers), you MUST include a small footnote  starting with "*Source:*" briefly describing where that specific data was found. (Leave one line, for tables of Ratings and Financial Summary, do NOT include "Source" in the table)
        -   **Financial Summary Specificity:** The footnote directly below the Financial Summary table (LEAVE ONE LINE JUST AFTER THE TABLE, DO NOT INCLUDE "Source" (the footnote) IN THE TABLE,) MUST clarify if the figures are from **Audited Financial Statements**, an **Earnings Release**, or **Management Accounts**. This is crucial for replication.
        -   **Ratings Specificity:** The footnote below the Ratings table MUST specify the exact document and date where the ratings were sourced. LEAVE ONE LINE AFTER THE TABLE, BEFORE THE SOURCE DESCRIPTION
    6. **Data Freshness:** Use ONLY the most recent data available (2024/2025). Do NOT use outdated financials or ratings.
    7. **Clean Format:** In the section of "Key Credit Drivers", use bullet points for clarity.
    8. **No Citation Tags:** DO NOT include any text like "" or "[previous search]" or "cite" or "(previous search)" in your output. 
    

    ### ONE-SHOT EXAMPLE (STRICTLY FOLLOW THIS TABLE STRUCTURE):
    Input: JLR
    Output:
    # **Jaguar Land Rover Automotive plc**

    | Agency | Rating |
    | :--- | :--- |
    | **Moody's:** | Ba1 (stable) |
    | **S&P:** | BBB- (positive) |
    | **Fitch:** | BB- (stable) |

    *Source: Latest Rating Action Commentaries from Moody's and S&P (Oct 2025).*

    ### Description
    Jaguar Land Rover (JLR) is a luxury automaker...

    *Source: Company Profile, FY2024 Annual Report.*

    **Key Management & Contact:**
    * **CEO:** Adrian Mardell
    * **CFO:** Richard Molyneux
    * **Investor Relations:** Email : investor@jaguarlandrover.com



    ### Financial Summary
    *In GBP mn*

    | Item | FY2023 | FY2024 | LTM |
    | :--- | :--- | :--- | :--- |
    | **Revenue** | 22,295 | 28,995 | 29,500 |
    | **EBITDA** | 2,500 | 3,400 | 3,650 |
    | **EBITDA Margin** | 11.2% | 11.7% | 12.4% |
    | **FFO** | 1,800 | 2,200 | 2,400 |
    | **OCF (Operating Cash Flow)** | 1,500 | 2,000 | 2,100 |
    | **Capex** | (1,200) | (1,300) | (1,400) |
    | **FOCF (OCF-Capex)** | 300 | 700 | 700 |
    | **Net Debt** | 4,200 | 3,800 | 3,500 |
    | **Net Leverage (Net Debt/EBITDA)** | 1.68x | 1.12x | 0.96x |
    | **Coverage (FOCF/Net Debt)** | 0.07x | 0.18x | 0.20x |

    *Source: Figures for FY23/24 derived from Audited Financial Statements; LTM figures derived from Q3 2025 Earnings Release (Management Accounts).*

    ### Key Credit Drivers
    **Premium brand positioning:** ...
    *Source: Market analysis and JLR November 2025 Debt Investor Presentation.*

    ### YOUR TASK:
    Now, generate the report for the following ticker using the latest available live data.
    Input: {ticker}
    Output:
    """

    # --- RETRY LOGIC (Maintained) ---
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-pro', # Updated to latest stable available
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())]
                )
            )
            return response
            
        except Exception as e:
            error_msg = str(e)
            if "503" in error_msg or "overloaded" in error_msg:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    st.warning(f"⚠️ Servers busy. Retrying in {wait_time}s... (Attempt {attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
            return f"Error: {e}"
        
# --- FRONTEND USER INTERFACE ---
st.title("📊 AI Financial Analyst")
st.markdown("Enter a ticker (e.g., `TSLA`, `F`, `HOG`) to generate a credit report.")

with st.form("ticker_form"):
    ticker_input = st.text_input("Company Ticker:", placeholder="e.g. F").upper()
    submitted = st.form_submit_button("Generate Report")

if submitted and ticker_input:
    with st.spinner(f"🔎 Researching {ticker_input} (Financials + Credit Drivers)..."):
        # Get the full response object
        response_obj = generate_company_report(ticker_input)
        
        if isinstance(response_obj, str) and "Error" in response_obj:
            st.error(response_obj)
        else:
            full_text = response_obj.text
            
            # --- SPLIT LOGIC ---
            split_marker = "### Appendix"
            
            pattern = r"(?i)\n#{1,3}\s+\**Appendix\**.*" 
            
            # Use re.split to chop the text at that pattern
            parts = re.split(pattern, full_text, maxsplit=1)
            
            if len(parts) > 1:
                main_report = parts[0].strip()
                # We re-add the header to the appendix so it looks nice in the expander
                rationale_text = "### Appendix\n" + parts[1].strip()
            else:
                main_report = full_text
                rationale_text = "No specific rationale generated."

            # 1. Show the Main Report
            st.success("Analysis Complete")
            st.markdown("---")
            st.markdown(main_report)
            
            # --- PDF DOWNLOAD BUTTON ---
            # We pass 'full_text' to include everything, or 'main_report' for just the clean version.
            # Here I passed 'full_text' so you get the thinking process in the PDF too.
            pdf_data = create_pdf(main_report)
            if pdf_data:
                st.download_button(
                    label="📄 Download Report as PDF",
                    data=pdf_data,
                    file_name=f"{ticker_input}_Credit_Report.pdf",
                    mime="application/pdf"
                )
            else:
                st.warning("⚠️ Could not generate PDF.")

            # 2. Show the "Thinking Mode"
            with st.expander("🧠 AI Thought Process & Sources (Click to Expand)", expanded=False):
                st.markdown("### Appendix: AI Rationale & Data Sources")
                st.markdown(rationale_text.strip())
                
                st.markdown("---")
                st.markdown("### 2. Live Search Data")
                
                try:
                    metadata = response_obj.candidates[0].grounding_metadata
                    if metadata and metadata.web_search_queries:
                        st.markdown("**🔍 Search Queries Issued:**")
                        for q in metadata.web_search_queries:
                            st.code(q, language="text")
                    
                    if metadata and metadata.grounding_chunks:
                        st.markdown("**🌐 Sources Verified:**")
                        unique_urls = set()
                        for chunk in metadata.grounding_chunks:
                            if chunk.web:
                                unique_urls.add(f"- [{chunk.web.title}]({chunk.web.uri})")
                        for url_md in list(unique_urls)[:7]:
                            st.markdown(url_md)
                except Exception:
                    st.info("No detailed grounding metadata available.")
elif submitted and not ticker_input:
    st.warning("Please enter a ticker symbol.")




