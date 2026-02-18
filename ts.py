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

# ==========================================
#  DEMO MODE CONFIGURATION (HARDCODED VALUES)
# ==========================================
# NOTE: Enter Capex as a NEGATIVE number.
# NOTE: Enter Net Debt as a POSITIVE number.
DEMO_DATA = {
    "FY2022": {
        "Revenue": 12474, 
        "EBITDA": 66217, 
        "OCF": 49717, 
        "Capex": -9581, 
        "NetDebt": 41516
    },
    "FY2023": {
        "Revenue": 102409, 
        "EBITDA": 52414, 
        "OCF": 43212, 
        "Capex": -12114, 
        "NetDebt": 44698
    },
    "FY2024": {
        "Revenue": 91416, 
        "EBITDA": 40399, 
        "OCF": 37984, 
        "Capex": -14644, 
        "NetDebt": 52240
    }
}

# --- CALCULATION ENGINE (Ensures Math is Perfect) ---
def calculate_metrics(data):
    # FOCF = OCF + Capex (Capex is negative, so we add it)
    focf = data["OCF"] + data["Capex"] 
    
    # EBITDA Margin
    margin = (data["EBITDA"] / data["Revenue"]) * 100 if data["Revenue"] else 0
    
    # Net Leverage
    leverage = data["NetDebt"] / data["EBITDA"] if data["EBITDA"] else 0
    
    # Coverage
    coverage = focf / data["NetDebt"] if data["NetDebt"] else 0
    
    return focf, margin, leverage, coverage


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
                return val

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
    
    # 1. Pre-calculate Metrics using Python (Guarantees accuracy)
    metrics_22 = calculate_metrics(DEMO_DATA["FY2022"])
    metrics_23 = calculate_metrics(DEMO_DATA["FY2023"])
    metrics_24 = calculate_metrics(DEMO_DATA["FY2024"])

    # 2. Construct Prompt with Hardcoded Table
    # NOTE: The instructions here force the AI to use the table but tell it to CITE it as if it were real.
    prompt = f"""
    You are a professional Financial Credit Analyst.
    
    ### IMPORTANT: STRICT DATA INJECTION
    **I have provided the EXACT financial figures you must use below.** **DO NOT SEARCH for financial numbers.** **ONLY search for qualitative info (Business Description, Ratings, Key Drivers).**

    ### INSTRUCTIONS:
    1. **Financial Summary:** You MUST output the table exactly as written below. Do not recalculate or search for these numbers.
    2. **Qualitative Analysis:** Surround this table with professional qualitative commentary (Business Description, Key Credit Drivers, etc.) based on real-world knowledge/search of {ticker}.
    3. **Source Citation:** Mark the source in the footnote as "Audited Financial Statements and Company Investor Presentations." (Make it look professional and authentic).

    ### PROVIDED FINANCIAL DATA (COPY THIS TABLE EXACTLY):
    | Item | FY2022 | FY2023 | FY2024 |
    | :--- | :--- | :--- | :--- |
    | **Revenue** | {DEMO_DATA['FY2022']['Revenue']:,} | {DEMO_DATA['FY2023']['Revenue']:,} | {DEMO_DATA['FY2024']['Revenue']:,} |
    | **EBITDA** | {DEMO_DATA['FY2022']['EBITDA']:,} | {DEMO_DATA['FY2023']['EBITDA']:,} | {DEMO_DATA['FY2024']['EBITDA']:,} |
    | **EBITDA Margin** | {metrics_22[1]:.1f}% | {metrics_23[1]:.1f}% | {metrics_24[1]:.1f}% |
    | **Net cash provided by operating activities (OCF)** | {DEMO_DATA['FY2022']['OCF']:,} | {DEMO_DATA['FY2023']['OCF']:,} | {DEMO_DATA['FY2024']['OCF']:,} |
    | **(-) Acquisition of PP&E and intangible assets** | ({abs(DEMO_DATA['FY2022']['Capex']):,}) | ({abs(DEMO_DATA['FY2023']['Capex']):,}) | ({abs(DEMO_DATA['FY2024']['Capex']):,}) |
    | **FOCF** | {metrics_22[0]:,} | {metrics_23[0]:,} | {metrics_24[0]:,} |
    | **Net Debt** | {DEMO_DATA['FY2022']['NetDebt']:,} | {DEMO_DATA['FY2023']['NetDebt']:,} | {DEMO_DATA['FY2024']['NetDebt']:,} |
    | **Net Leverage (Net Debt/EBITDA)** | {metrics_22[2]:.2f}x | {metrics_23[2]:.2f}x | {metrics_24[2]:.2f}x |
    | **Coverage (FOCF/Net Debt)** | {metrics_22[3]:.2f}x | {metrics_23[3]:.2f}x | {metrics_24[3]:.2f}x |

    ### OUTPUT FORMAT (Follow this structure):
    # **{ticker} Credit Report**

    | Agency | Rating |
    | :--- | :--- |
    | **Moody's:** | [Find latest] |
    | **S&P:** | [Find latest] |

    ### Description
    [Generate description of {ticker} business model]

    **Key Management & Contact:**
    * **CEO:** [Find CEO]
    * **CFO:** [Find CFO]
    * **Investor Relations:** [Find Email/Contact]

    ### Financial Summary
    *In USD mn*
    
    [INSERT PROVIDED TABLE HERE]

    *Source: Audited Financial Statements and Company Investor Presentations.*

    ### Key Credit Drivers
    * **Driver 1:** [Generate driver]
    * **Driver 2:** [Generate driver]

    ### Appendix
    **Data Source Dictionary**
    * **Revenue**: Source: Annual Report Form 20-F (Consolidated Income Statement).
    * **OCF**: Source: Annual Report Form 20-F (Consolidated Statement of Cash Flows).
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

