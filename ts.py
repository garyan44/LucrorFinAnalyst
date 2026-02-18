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
    # --- HELPER: PARSE MARKDOWN TABLE (FOR INTERACTIVE DISPLAY) ---

def parse_markdown_table(markdown_content):

    """Parses the Financial Summary markdown table into a Pandas DataFrame."""

    try:

        start_marker = "### Financial Summary"

        start_pos = markdown_content.find(start_marker)

        if start_pos == -1: return None, None, None



        # Split content into Pre-Table and Table Section

        pre_table_text = markdown_content[:start_pos + len(start_marker)]

        remaining_text = markdown_content[start_pos + len(start_marker):]



        lines = remaining_text.split('\n')

        table_lines = []

        post_table_lines = []

        capture_table = False

        table_finished = False



        for line in lines:

            stripped = line.strip()

            # Detect Table Start

            if "| Item" in stripped or "| **Item" in stripped:

                capture_table = True

            

            if capture_table and not table_finished:

                if stripped.startswith("|"):

                    table_lines.append(stripped)

                elif stripped == "" and len(table_lines) > 0:

                    table_finished = True

                elif not stripped.startswith("|") and len(table_lines) > 0:

                    table_finished = True

                    post_table_lines.append(line)

            elif table_finished:

                post_table_lines.append(line)

            else:

                pre_table_text += "\n" + line



        if not table_lines: return None, None, None



        # Process Table Data

        table_lines = [line for line in table_lines if "---" not in line]

        headers = [h.strip().replace('*', '') for h in table_lines[0].strip('|').split('|')]

        

        data = []

        for line in table_lines[1:]:

            row_vals = [c.strip().replace('**', '') for c in line.strip('|').split('|')]

            if len(row_vals) == len(headers):

                data.append(row_vals)

        

        df = pd.DataFrame(data, columns=headers)

        post_table_text = "\n".join(post_table_lines)

        return df, pre_table_text, post_table_text

    except Exception as e:

        return None, None, None

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
    1. **Search Strategy (CRITICAL):**
        
        - **Primary Source (Boss’s Orders):**
          Search specifically for **"{ticker} Investor Relations"** to locate the company’s official investor relations website.
          Use this site as the anchor for all financial documents.
        
        - **Regulatory Filings (MANDATORY – DO NOT SKIP):**
          Identify the company’s primary annual regulatory filing.
          - U.S. issuers: **Form 10-K**
          - Foreign private issuers / ADRs: **Form 20-F**
          Use ONLY these filings for audited financial statement data.
        
        - **Historical Financial Data (CRUCIAL):**
          - Search for **"{ticker} Form 10-K (FY2022)" OR "{ticker} Form 20-F (FY2022)"**
          - Search for **"{ticker} Form 10-K (FY2023)" OR "{ticker} Form 20-F (FY2023)"**
          - Search for **"{ticker} Form 10-K (FY2024)" OR "{ticker} Form 20-F (FY2024)"**
          Use the company’s primary annual filing for each fiscal year.
          Do NOT rely on documents labeled only as “Annual Report” unless they explicitly contain the audited financial statements.
        
        - **Fiscal Year Verification (NON-NEGOTIABLE):**
          First, identify the company’s fiscal year end from the filing.
          Assign data to FY2022 / FY2023 / FY2024 strictly based on the stated fiscal year,
          NOT the calendar year or publication date.
        
       - **EBITDA Source Rule (NON-NEGOTIABLE):**
          For each year (FY2022/FY2023/FY2024), you MUST extract EBITDA/Adjusted EBITDA from the SAME annual filing
          (Form 10-K or Form 20-F) that you used for Revenue for that year.
          Search WITHIN that filing for: "Adjusted EBITDA", "EBITDA", "Performance measures", "Non-GAAP measures".
        
          ONLY if the annual filing does NOT disclose an explicit EBITDA/Adjusted EBITDA figure,
          then use an OFFICIAL company IR earnings release / investor presentation as a fallback.
        
          DO NOT use third-party aggregators (Macrotrends, Yahoo Finance, StockAnalysis, etc.) for EBITDA.
          If you cannot find it in official sources, output "N/A".

        
        - **Cash Flow & Capex (STATEMENT-LEVEL DATA ONLY):**
          Extract the following strictly from the **Consolidated Statement of Cash Flows**:
          - **Net cash provided by operating activities** (or equivalent wording)
          - **Capex**, defined as:
            - Purchase of Property, Plant & Equipment
            - PLUS Purchase of Intangible Assets
        
        - **Credit Ratings:**
          Search for **"{ticker} Moody’s credit rating"**, **"{ticker} S&P credit rating"**, and **"{ticker} Fitch credit rating"**.
          Use the most recent rating action press releases (2024–2025).
        
        - **Management & Investor Relations Contact:**
          Search for:
          - **"{ticker} CEO"**
          - **"{ticker} CFO"**
          - **"{ticker} Investor Relations contact"**
          Prefer the official company or investor relations website.


    2.  **Calculations & Definitions (STRICT):**
        -   **Revenue:** Extract the exact **"Sales revenues"** or **"Net operating revenues"** line strictly from the **Consolidated Statement of Income** table.
            * **CRITICAL:** Do NOT use numbers from the "Financial Highlights", "Key Figures", or "Gross Revenue" sections. Use the GAAP/IFRS table value only.
        - **EBITDA (STRICT DOCUMENT CONSISTENCY RULE):**
          First, search for **"Adjusted EBITDA" explicitly within the SAME annual regulatory filing
          (Form 10-K or Form 20-F) used to extract Revenue for that fiscal year.**
        
          If an "Adjusted EBITDA" or "EBITDA" table exists in that filing (including notes,
          segment information, or performance measures sections),
          you MUST use that value.
        
          ONLY if the annual filing does NOT contain an explicit Adjusted EBITDA figure,
          then search for a separate "Adjusted EBITDA reconciliation" in earnings releases
          or investor presentations.
        
          DO NOT calculate EBITDA manually if an explicit value exists in the annual filing.

        -   **EBITDA Margin:** Adjusted EBITDA / Revenue.

        
        -   **Net cash provided by operating activities (OCF):** Extract the exact **"Net cash provided by operating activities"** (or "Net cash from operations") line directly from the **Consolidated Statement of Cash Flows**. 
            *DO NOT adjust for interest. Use the raw figure from the statement.*

        -   **(-) Acquisition of PP&E and intangible assets:** Extract the cash used for **"Purchase of property, plant and equipment"** (Capex) AND **"Purchase of intangible assets"** from the Investing section of the Cash Flow Statement.
            *Sum these values if reported separately.*

        -   **FOCF (Free Operating Cash Flow):** FOCF = (Net cash provided by operating activities) + (Acquisition of PP&E and intangible assets).
            *Note: Since Acquisition of PP&E is a negative outflow, you simply sum the two numbers (e.g., 2000 + (-1500) = 500).*
        -   **Net Debt (STRICT – Petrobras / screenshot definition):**
            You MUST compute Net Debt using this exact Petrobras definition from the FY2024 20-F:
            1) Gross Debt = Finance debt + Lease liabilities (IFRS 16)
            2) Net Debt = Gross Debt - Adjusted Cash and Cash Equivalents
        
            CRITICAL:
            - Do NOT use other “net debt” KPIs found in notes (e.g., Note 25) if they do NOT reconcile to Gross Debt - Adjusted Cash.
            - You MUST show the reconciliation math in the Appendix:
            Finance debt (value) + Lease liabilities (value) = Gross Debt (value)
            Gross Debt (value) - Adjusted Cash & Cash Equivalents (value) = Net Debt (value)
        
            For FY2022 and FY2023: use the SAME definition and compute from the filing using:
            Finance debt + Lease liabilities - Adjusted Cash & Cash Equivalents (if provided).
            If Adjusted Cash is not provided for a year, then use the filing’s explicitly reported Net Debt ONLY IF it is part of the same Gross Debt - Adjusted Cash reconciliation section.



        -   **Net Leverage:** Net Debt / Adjusted EBITDA.
        -   **Coverage:** FOCF / Net Debt.
    
    
    2.  **Calculations (MANDATORY):**
        -   $EBITDA Margin = EBITDA / Revenue$
        -   $FOCF = Net Cash from Ops + (Acquisition of PP&E and Intangibles)$
        -   $Net Debt = (Finance debt + Lease liabilities) - (Adjusted Cash & Cash Equivalents)$
        -   $Net Leverage = Net Debt / EBITDA$
        -   $Coverage = FOCF / Net Debt$
        **IMPORTANT:** EBITDA must be taken from an explicitly reported "EBITDA" or "Adjusted EBITDA" figure in an official filing.
        Do NOT compute EBITDA as Operating Income + D&A unless you explicitly label it as an estimate and only if no reported EBITDA exists.

        
    
    3.  **Format:** Output strictly in Markdown. Follow the One-Shot Example structure exactly.
        
    4.  **Audit Trail (CRITICAL):** -   AFTER the main report, output a section header called `### Appendix`.
        -   Inside the Appendix, you MUST generate a structured list titled **"Data Source Dictionary"**.
        -   **CRITICAL:** You must generate a bullet point for **EVERY SINGLE ROW** in the table, including **Calculated Metrics**, **Margins**, **Ratios**, and **Growth Rates**. Do not skip *any* row.
        -   Format:
            * **[Exact Row Name]**: Source: [Document Name/Page] OR Logic: [Formula used]. Raw Value: [Value].
            * **[Item Name]**: Source Document: [Name], Page: [Page #], Raw Value: [Value], Logic: [Explanation].

        -   Example:

            * **Revenue**: Source Document: Ford 2024 10-K, Page: 45, Raw Value: 158,000, Logic: Sum of Automotive and Credit revenue.

            * **FFO**: Source Document: Q3 Earnings Release, Page: 8, Raw Value: Calculated, Logic: Net Income (200) + D&A (150).
    
    5.  **Rationale (Internal):** AFTER the main report, output a section header called `Appendix`. INCLUDE IT IN THE NEXT PAGE. In this section, detail your thought process, reasoning for credit drivers, and how you located each data point (with URLs). This is for internal use and should NOT appear in the main report.
        -   In this section, you must provide a **"Financial Data Audit"**.
        -   For every year (FY23, FY24, LTM) in the Financial Summary, you must state:
            * **Exact Document Name:** (e.g., "Ford 2024 10-K" - https://investor.ford.com/...)
            * **Page Number/Table Name:** (e.g., "Consolidated Statement of Operations, Page 45")
            * **Raw Figure Used:** (e.g., "I saw Revenue = 158,000 in the PDF, so I used 158,000")
            * **Reasoning:** Explain why you assigned it to that specific column (e.g., "The report says 'Fiscal Year Ended Dec 31, 2024', so this goes in the FY2024 column").
        -   **This is to prevent year-shifting errors.**

    6.  **Transparency & Footnotes (NEW REQUIREMENT):**
        -   **After EVERY section** (Ratings, Description, Financial Summary, Key Credit Drivers), you MUST include a small footnote  starting with "*Source:*" briefly describing where that specific data was found. (Leave one line, for tables of Ratings and Financial Summary, do NOT include "Source" in the table)
        -   **Financial Summary Specificity:** The footnote directly below the Financial Summary table (LEAVE ONE LINE JUST AFTER THE TABLE, DO NOT INCLUDE "Source" (the footnote) IN THE TABLE,) MUST clarify if the figures are from **Audited Financial Statements**, an **Earnings Release**, or **Management Accounts**. This is crucial for replication.
        -   **Ratings Specificity:** The footnote below the Ratings table MUST specify the exact document and date where the ratings were sourced. LEAVE ONE LINE AFTER THE TABLE, BEFORE THE SOURCE DESCRIPTION
    7. **Data Freshness:** Use ONLY the most recent data available (2024/2025). Do NOT use outdated financials or ratings.
    8. **Clean Format:** In the section of "Key Credit Drivers", use bullet points for clarity.
    9. **No Citation Tags:** DO NOT include any text like "" or "[previous search]" or "cite" or "(previous search)" in your output.
    10. USE BULLET POINTS IN THE "KEY MANAGEMENTS AND CONTACT" SECTION
    

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

    | Item | FY2022 | FY2023 | FY2024 |
    | :--- | :--- | :--- | :--- |
    | **Revenue** | 18,320 | 22,809 | 28,995 |
    | **EBITDA** | 2,050 | 2,500 | 3,400 |
    | **EBITDA Margin** | 11.2% | 11.0% | 11.7% |
    | **Net cash provided by operating activities (OCF)** | 1,100 | 1,500 | 2,000 |
    | **(-) Acquisition of PP&E and intangible assets** | (1,000) | (1,200) | (1,300) |
    | **FOCF** | 100 | 300 | 700 |
    | **Net Debt** | 4,500 | 4,200 | 3,800 |
    | **Net Leverage (Net Debt/EBITDA)** | 2.2x | 1.68x | 1.12x |
    | **Coverage (FOCF/Net Debt)** | 0.02x | 0.07x | 0.18x |

    *Source: Figures for FY23/24 derived from Audited Financial Statements; LTM figures derived from Q3 2025 Earnings Release (Management Accounts).*

    ### Key Credit Drivers
    **Premium brand positioning:** ...
    *Source: Market analysis and JLR November 2025 Debt Investor Presentation.*

    ### Appendix
    **Data Source Dictionary**
    * **Revenue**: Source Document: FY2024 Annual Report, Page 88, Raw Value: 28,995, Logic: Extracted directly from Consolidated Income Statement.
    * **EBITDA**: Source Document: Investor Presentation Slide 12, Raw Value: 3,400, Logic: Reported Adjusted EBITDA.
    * **FFO**: Source Document: 10-K Cash Flow Stmt, Raw Value: Calculated, Logic: Net Income (1,200) + D&A (1,000).

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

# --- SESSION STATE INITIALIZATION ---
if "report_text" not in st.session_state:
    st.session_state["report_text"] = None
if "report_ticker" not in st.session_state:
    st.session_state["report_ticker"] = None
if "grounding_metadata" not in st.session_state:
    st.session_state["grounding_metadata"] = None



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
            # SAVE TO SESSION STATE (Crucial for interactivity)
            st.session_state["report_text"] = response_obj.text
            st.session_state["report_ticker"] = ticker_input
            try:
                st.session_state["grounding_metadata"] = response_obj.candidates[0].grounding_metadata
            except:
                st.session_state["grounding_metadata"] = None

# --- DISPLAY LOGIC (OUTSIDE THE FORM, HANDLES CLICKS) ---
if st.session_state["report_text"]:
    full_text = st.session_state["report_text"]
    current_ticker = st.session_state["report_ticker"]
    
    # Split Main Report and Appendix
    pattern = r"(?i)\n#{1,3}\s+\**Appendix\**.*" 
    parts = re.split(pattern, full_text, maxsplit=1)
    
    if len(parts) > 1:
        main_report = parts[0].strip()
        rationale_text = parts[1].strip()
    else:
        main_report = full_text
        rationale_text = ""

    st.success("Analysis Complete")
    
    # 1. Logos
    col1, col2 = st.columns([1, 1])
    with col1:
        try:
            st.image("lucror_logo.png", width=180)
        except:
            st.write("**Lucror Analytics**")
    with col2:
        domain = get_company_domain(current_ticker)
        st.markdown(f'<div style="text-align: right;"><img src="https://logo.clearbit.com/{domain}" width="80"></div>', unsafe_allow_html=True)

    st.markdown("---")

    # 2. PARSE AND DISPLAY FINANCIAL SUMMARY WITH TRACING
    df_financials, pre_table_text, post_table_text = parse_markdown_table(main_report)

    if df_financials is not None:
        # Display everything before the table
        st.markdown(pre_table_text)
        
        # INTERACTIVE TABLE
        st.subheader("Interactive Financial Summary")
        st.info("👆 **Click on any row** to see the source & calculation logic.")
        
        # Display Dataframe with Selection
        selection = st.dataframe(
            df_financials, 
            use_container_width=True, 
            on_select="rerun", 
            selection_mode="single-row",
            hide_index=True
        )

        # CHECK SELECTION & SHOW AUDIT TRAIL
# CHECK SELECTION & SHOW AUDIT TRAIL
# CHECK SELECTION & SHOW AUDIT TRAIL
        if len(selection.selection.rows) > 0:
            selected_row_idx = selection.selection.rows[0]
            selected_item = df_financials.iloc[selected_row_idx][0] # First column is "Item"
            
            # 1. Clean the clicked item name (e.g. "**Revenue**" -> "revenue")
            # We also split by "(" to handle "EBITDA (adj.)" -> just search for "ebitda"
            clean_search_term = selected_item.replace("**", "").split("(")[0].strip().lower()
            
            st.markdown(f"### 🔍 Audit Trail for: **{selected_item}**")
            
            # 2. Scan the AI's thought process (Appendix)
            appendix_lines = rationale_text.split('\n')
            found_entries = []
            
            for line in appendix_lines:
                line_lower = line.lower()
                
                # ROBUST MATCHING LOGIC:
                # 1. Does the line contain the item name? (e.g. "revenue")
                # 2. Does the line contain "source" or "document"? (To ensure it's a citation)
                # 3. Does it look like a list item? (Starts with * or -)
                if clean_search_term in line_lower and ("source" in line_lower or "document" in line_lower) and (line.strip().startswith("*") or line.strip().startswith("-")):
                    found_entries.append(line.strip())

            # 3. Display Results
            if found_entries:
                for entry in found_entries:
                    # formatting: highlight the search term for visibility
                    formatted_entry = re.sub(f"(?i)({re.escape(clean_search_term)})", r"**:blue[\1]**", entry)
                    st.info(formatted_entry)
            else:
                st.warning(f"Could not trace exact source for '{clean_search_term}'. Showing raw references found:")
                # Fallback: Show ANY line with the word, even if it doesn't look like a source
                fallback_found = False
                for line in appendix_lines:
                    if clean_search_term in line.lower():
                        st.markdown(f"- {line.strip()}")
                        fallback_found = True
                
                if not fallback_found:
                    st.error("No mention of this item found in the AI's audit trail.")
        
        # Display everything after the table
        st.markdown(post_table_text)
    else:
        # Fallback
        st.markdown(main_report)
    
    # 3. Download Buttons
    st.markdown("### 📥 Download Report")
    dl_col1, dl_col2 = st.columns([1, 1])
    
    pdf_data = create_pdf(main_report, current_ticker)
    with dl_col1:
        if pdf_data:
            st.download_button(
                label="📄 Download Report (PDF)",
                data=pdf_data,
                file_name=f"{current_ticker}_Credit_Report.pdf",
                mime="application/pdf"
            )
        else:
            st.warning("⚠️ Could not generate PDF.")
    
    xls_data = create_excel(main_report, current_ticker)
    with dl_col2:
        if xls_data:
            st.download_button(
                label="📊 Download Financials (Excel)",
                data=xls_data,
                file_name=f"{current_ticker}_Financials.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info("⚠️ Financial table not found for Excel.")

    # 4. Thinking Mode
    with st.expander("🧠 AI Thought Process & Sources (Click to Expand)", expanded=False):
        st.markdown("### Appendix: AI Rationale & Data Sources")
        st.markdown(rationale_text)
        
        st.markdown("---")
        st.markdown("### 2. Live Search Data")
        
        metadata = st.session_state["grounding_metadata"]
        if metadata:
            if metadata.web_search_queries:
                st.markdown("**🔍 Search Queries Issued:**")
                for q in metadata.web_search_queries:
                    st.code(q, language="text")
            
            if metadata.grounding_chunks:
                st.markdown("**🌐 Sources Verified:**")
                unique_urls = set()
                for chunk in metadata.grounding_chunks:
                    if chunk.web:
                        unique_urls.add(f"- [{chunk.web.title}]({chunk.web.uri})")
                for url_md in list(unique_urls)[:7]:
                    st.markdown(url_md)
        else:
             st.info("No detailed grounding metadata available.")
elif submitted and not ticker_input:
    st.warning("Please enter a ticker symbol.")



































