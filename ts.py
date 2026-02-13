import streamlit as st
from google import genai
from google.genai import types
import time
import markdown
from xhtml2pdf import pisa
import io
import re
import base64
import yfinance as yf
import pandas as pd # <--- ADDED for Excel handling


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

    # --- EXCEL GENERATION FUNCTION (NEW) ---
def create_excel(markdown_content, ticker):
    """Extracts Financial Summary table and converts to formatted Excel."""
    try:
        # 1. LOCATE AND PARSE THE TABLE
        start_marker = "### Financial Summary"
        start_pos = markdown_content.find(start_marker)
        
        if start_pos == -1: return None
            
        # Extract text from that point onwards
        section_text = markdown_content[start_pos:]
        lines = section_text.split('\n')
        table_lines = []
        capture = False
        
        for line in lines:
            stripped = line.strip()
            # Start capturing at the header row (contains | Item or | **Item)
            if "| Item" in stripped or "| **Item" in stripped:
                capture = True
            
            if capture:
                if stripped.startswith("|"):
                    table_lines.append(stripped)
                # Stop if we hit a blank line after starting capture (end of table)
                elif stripped == "" and len(table_lines) > 0:
                    break
        
        if not table_lines: return None

        # 2. PROCESS MARKDOWN INTO DATAFRAME
        # Remove the separator line (---|---|---)
        table_lines = [line for line in table_lines if "---" not in line]
        
        # Extract headers (clean * and spaces)
        headers = [h.strip().replace('*', '') for h in table_lines[0].strip('|').split('|')]
        
        data = []
        for line in table_lines[1:]:
            # Split by pipe, clean bolding (**), strip whitespace
            row_vals = [c.strip().replace('**', '') for c in line.strip('|').split('|')]
            if len(row_vals) == len(headers):
                data.append(row_vals)
        
        df = pd.DataFrame(data, columns=headers)
        
        # 3. CLEAN DATA (String -> Number)
        def clean_financial_num(val):
            if not isinstance(val, str): return val
            val = val.strip()
            if val == "-": return 0
            
            # Detect formats
            is_percent = "%" in val
            
            # Remove artifacts
            clean = val.replace(',', '').replace('%', '').replace('x', '').replace('X', '')
            
            # Handle Parentheses for negatives: (1,200) -> -1200
            if '(' in clean and ')' in clean:
                clean = clean.replace('(', '').replace(')', '')
                sign = -1
            else:
                sign = 1
                
            try:
                num = float(clean) * sign
                if is_percent: return num / 100
                return num
            except ValueError:
                return val # Return original text if not a number

        # Apply cleaning to all columns except the first (Item names)
        for col in df.columns[1:]:
            df[col] = df[col].apply(clean_financial_num)

        # 4. WRITE TO EXCEL WITH FORMATTING
        output = io.BytesIO()
        # Use xlsxwriter engine for rich formatting
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Financial Summary', index=False)
            workbook = writer.book
            worksheet = writer.sheets['Financial Summary']
            
            # Define Formats
            header_fmt = workbook.add_format({'bold': True, 'bottom': 2, 'bg_color': '#F2F2F2', 'font_name': 'Arial', 'font_size': 10})
            item_fmt = workbook.add_format({'bold': True, 'font_name': 'Arial', 'font_size': 10})
            # Number formats
            num_fmt = workbook.add_format({'num_format': '#,##0;(#,##0)', 'font_name': 'Arial', 'font_size': 10}) 
            pct_fmt = workbook.add_format({'num_format': '0.0%', 'font_name': 'Arial', 'font_size': 10})
            x_fmt = workbook.add_format({'num_format': '0.00"x"', 'font_name': 'Arial', 'font_size': 10})
            text_fmt = workbook.add_format({'font_name': 'Arial', 'font_size': 10})

            # Apply Column Widths
            worksheet.set_column(0, 0, 30) # Item Column
            worksheet.set_column(1, len(df.columns)-1, 15) # Data Columns

            # Apply Header Format
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_fmt)

            # Row-by-Row Conditional Formatting
            for i, row in df.iterrows():
                row_idx = i + 1
                item_name = str(row[df.columns[0]]).lower()
                
                # Write Item Name (First Column)
                worksheet.write(row_idx, 0, row[df.columns[0]], item_fmt)
                
                # Write Data Columns
                for j, col in enumerate(df.columns[1:]):
                    col_idx = j + 1
                    val = row[col]
                    
                    if isinstance(val, (int, float)):
                        if "margin" in item_name or "%" in item_name:
                            worksheet.write(row_idx, col_idx, val, pct_fmt)
                        elif "leverage" in item_name or "coverage" in item_name:
                            worksheet.write(row_idx, col_idx, val, x_fmt)
                        else:
                            worksheet.write(row_idx, col_idx, val, num_fmt)
                    else:
                        worksheet.write(row_idx, col_idx, val, text_fmt)
                        
        return output.getvalue()
    except Exception as e:
        st.error(f"Excel Conversion Error: {e}")
        return None



# --- HELPER: GET COMPANY DOMAIN FOR LOGO ---
def get_company_domain(ticker):
    """Fetches the official website to ensure the logo is accurate."""
    try:
        dat = yf.Ticker(ticker)
        url = dat.info.get('website')
        if url:
            # Clean URL to get just the domain (e.g., tesla.com)
            domain = url.replace("https://", "").replace("http://", "").replace("www.", "").split('/')[0]
            return domain
    except:
        pass
    return f"{ticker.lower()}.com"




# --- PDF GENERATION FUNCTION ---
def create_pdf(markdown_content, ticker):

    import re

        # 1. Base64 Encode Lucror Logo for PDF (Universal Support)
    try:
        with open("lucror_logo.png", "rb") as f:
            lucror_base64 = base64.b64encode(f.read()).decode()
            lucror_img_src = f"data:image/png;base64,{lucror_base64}"
    except FileNotFoundError:
        lucror_img_src = "" # Fallback if file missing

        # 2. Get Company Logo

    domain = get_company_domain(ticker)

    company_logo_url = f"https://logo.clearbit.com/{domain}"  
    
    # --- 1. CLEAN THE HEADER ---
    # Replace the whole "Key Management" line (and any junk stars around it) with a clean header
    markdown_content = re.sub(
        r'(?i)^[\s\*]*Key Management.*?Contact.*?$', 
        '\n\n### Key Management & Contact', 
        markdown_content, 
        flags=re.MULTILINE
    )

    # --- 2. CLEAN & STANDARDIZE TITLES (CEO / CFO / President) ---
    # This loop ensures that specific titles start on a new line with a clean bullet.
    # We put "President & CEO" first so it doesn't get chopped up by the "CEO" rule.
    target_titles = ["President & CEO", "CEO", "CFO", "President"]
    
    for title in target_titles:
        # Regex: Find the title, preceded by any amount of garbage (stars, spaces, bullets), followed by a colon
        # Replace it with: Newline + Bullet + Bold Title + Colon
        pattern = fr'(?i)(?:\\n|^|[\s\*•-])+\**{re.escape(title)}\**\s*:'
        replacement = f'\n* **{title}:**'
        markdown_content = re.sub(pattern, replacement, markdown_content)

    # --- 3. FIX INVESTOR RELATIONS (The Merge Logic) ---
    
    # Step A: Standardize the "Investor Relations" label first
    markdown_content = re.sub(
        r'(?i)(?:\\n|^|[\s\*•-])+\**Investor\s*Relations\**\s*:', 
        '\n* **Investor Relations:**', 
        markdown_content
    )

    # Step B: The Merge. 
    # Look for "**Investor Relations:**" followed by a newline and an email address.
    # This grabs the email from the next line and pulls it up.
    markdown_content = re.sub(
        r'(?i)(\*\*Investor Relations:\*\*)\s*\n+[\s\*•-]*([^\n]*@)', 
        r'\1 \2', 
        markdown_content
    )

    # --- 4. CLEANUP ARTIFACTS ---
    # Removes the accidental double stars or weird space-star combos (like "* *")
    markdown_content = markdown_content.replace("****", "**")
    markdown_content = re.sub(r'(?m)^\s*\*\s*\*\s*$', '', markdown_content) # Deletes empty "* *" lines

    # --- 5. STRENGTHS & WEAKNESSES FORMATTING ---
    # Ensures these headers always have a blank line above them so they don't look like a wall of text.
    markdown_content = re.sub(r'(?i)(?<!\n)\s*\*?\s*\*\*?Strengths:?\**', '\n\n**Strengths:**\n', markdown_content)
    markdown_content = re.sub(r'(?i)(?<!\n)\s*\*?\s*\*\*?Weaknesses:?\**', '\n\n**Weaknesses:**\n', markdown_content)
    
    # --- CONVERSION TO HTML/PDF ---
    html_text = markdown.markdown(markdown_content, extensions=['tables'])
    
    styled_html = f"""
    <html>
    <head>
        <meta charset="UTF-8">

        <style>
            
            @page {{ margin: 0.7in; }}

            body {{ font-family: Helvetica, sans-serif; font-size: 11px; line-height: 1.4; color: #333; }}

            .header-table {{ width: 100%; border: none; margin-bottom: 20px; }}

            .header-table td {{ border: none; vertical-align: middle; }}

            .logo-left {{ text-align: left; width: 50%; }}

            .logo-right {{ text-align: right; width: 50%; }}

            .logo-img {{ height: 45px; object-fit: contain; }}
          
            h1 {{ color: #2c3e50; font-size: 18px; margin-bottom: 10px; border-bottom: 2px solid #2c3e50; padding-bottom: 5px; }}
            h2 {{ color: #2c3e50; font-size: 16px; margin-top: 25px; margin-bottom: 10px; border-bottom: 1px solid #ddd; padding-bottom: 3px; }}
            h3 {{ color: #2c3e50; font-size: 14px; margin-top: 20px; margin-bottom: 8px; font-weight: bold; }}
            
            /* Clean Table Styling */
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; margin-bottom: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; vertical-align: top; }}
            th {{ background-color: #f8f9fa; font-weight: bold; color: #2c3e50; }}
            
            /* Specific List Styling */
            ul {{ margin-top: 5px; margin-bottom: 15px; padding-left: 20px; }}
            li {{ margin-bottom: 6px; }}
            
            /* Source Footnote Styling */
            em {{ font-size: 10px; color: #666; display: block; margin-top: 5px; }}
        </style>
    </head>
    <body>
        {html_text}
    </body>
    </html>
    """
    
    pdf_buffer = io.BytesIO()
    
    pisa_status = pisa.CreatePDF(

        io.BytesIO(styled_html.encode("utf-8")), 

        dest=pdf_buffer,

        encoding='utf-8' 

    )
    
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
        -   **Year Verification:** Before extracting ANY number, verify the **Fiscal Year End**. (e.g., Does Microsoft's FY24 end in June 2024? If so, label it 2024. Do NOT shift it to 2023).
        -   **Financials:** Search for "{ticker} Investor Presentation Q3 2025" (or latest available) to get the most recent LTM numbers.
        -   **Management & Contact:** Search for "{ticker} CEO CFO name 2025" and "{ticker} Investor Relations email address contact".
            * **STRICT FORMATTING:** You MUST use a standard Markdown list.
            * Do NOT format inline (e.g., do not output "* CEO: ... * CFO: ...").
            * Ensure there is a newline character before every bullet point.
    
    
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
        -   In this section, you must provide a **"Financial Data Audit"**.
        -   For every year (FY23, FY24, LTM) in the Financial Summary, you must state:
            * **Exact Document Name:** (e.g., "Ford 2024 10-K" - https://investor.ford.com/...)
            * **Page Number/Table Name:** (e.g., "Consolidated Statement of Operations, Page 45")
            * **Raw Figure Used:** (e.g., "I saw Revenue = 158,000 in the PDF, so I used 158,000")
            * **Reasoning:** Explain why you assigned it to that specific column (e.g., "The report says 'Fiscal Year Ended Dec 31, 2024', so this goes in the FY2024 column").
        -   **This is to prevent year-shifting errors.**

    5.  **Transparency & Footnotes (NEW REQUIREMENT):**
        -   **After EVERY section** (Ratings, Description, Financial Summary, Key Credit Drivers), you MUST include a small footnote  starting with "*Source:*" briefly describing where that specific data was found. (Leave one line, for tables of Ratings and Financial Summary, do NOT include "Source" in the table)
        -   **Financial Summary Specificity:** The footnote directly below the Financial Summary table (LEAVE ONE LINE JUST AFTER THE TABLE, DO NOT INCLUDE "Source" (the footnote) IN THE TABLE,) MUST clarify if the figures are from **Audited Financial Statements**, an **Earnings Release**, or **Management Accounts**. This is crucial for replication.
        -   **Ratings Specificity:** The footnote below the Ratings table MUST specify the exact document and date where the ratings were sourced. LEAVE ONE LINE AFTER THE TABLE, BEFORE THE SOURCE DESCRIPTION
    6. **Data Freshness:** Use ONLY the most recent data available (2024/2025). Do NOT use outdated financials or ratings.
    7. **Clean Format:** In the section of "Key Credit Drivers", use bullet points for clarity.
    8. **No Citation Tags:** DO NOT include any text like "" or "[previous search]" or "cite" or "(previous search)" in your output.
    9. USE BULLET POINTS IN THE "KEY MANAGEMENTS AND CONTACT" SECTION
    

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
st.title("📊 Financial Analyst")
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
                        # 1. UI HEADER LOGOS
            col1, col2 = st.columns([1, 1])
            with col1:
                try:
                    st.image("lucror_logo.png", width=180)
                except:
                    st.write("**Lucror Analytics**")
            with col2:
                domain = get_company_domain(ticker_input)
                st.markdown(f'<div style="text-align: right;"><img src="https://logo.clearbit.com/{domain}" width="80"></div>', unsafe_allow_html=True)


            st.markdown("---")
            st.markdown(main_report)
            
            # --- DOWNLOAD BUTTONS (PDF + EXCEL) ---
            st.markdown("### 📥 Download Report")
            dl_col1, dl_col2 = st.columns([1, 1])
            
            # PDF Button

            pdf_data = create_pdf(main_report, ticker_input)
            with dl_col1:
                if pdf_data:
                    st.download_button(
                        label="📄 Download Report (PDF)",
                        data=pdf_data,
                        file_name=f"{ticker_input}_Credit_Report.pdf",
                        mime="application/pdf"
                    )
                else:
                    st.warning("⚠️ Could not generate PDF.")
            
            # Excel Button
            xls_data = create_excel(main_report, ticker_input)
            with dl_col2:
                if xls_data:
                    st.download_button(
                        label="📊 Download Financials (Excel)",
                        data=xls_data,
                        file_name=f"{ticker_input}_Financials.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                else:
                    st.info("⚠️ Financial table not found for Excel.")


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





















