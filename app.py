import streamlit as st
import os
import pandas as pd
import json
import re
from PyPDF2 import PdfReader
from docx import Document
import google.generativeai as genai
from dotenv import load_dotenv
from dateutil.parser import parse
from datetime import datetime
import json_repair

# Load environment variables
load_dotenv()

# Configure Gemini
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

def extract_text_from_file(file):
    """Extract text from PDF/DOCX files"""
    text = ""
    try:
        if file.type == "application/pdf":
            pdf_reader = PdfReader(file)
            for page in pdf_reader.pages:
                text += page.extract_text()
        elif file.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            doc = Document(file)
            for para in doc.paragraphs:
                text += para.text + "\n"
    except Exception as e:
        st.error(f"Error reading {file.name}: {str(e)}")
        return None
    return text

def calculate_experience(experience_entries):
    """Calculate total work experience in years from experience entries"""
    total_days = 0
    
    for entry in experience_entries:
        if isinstance(entry, dict):
            duration = entry.get('duration', '')
        else:
            # Extract duration from formatted string
            duration_match = re.search(r"\((.*?)\)", entry)
            duration = duration_match.group(1) if duration_match else ''
        
        try:
            if '-' in duration or '–' in duration:
                # Handle different separators
                separator = '-' if '-' in duration else '–'
                start_str, end_str = map(str.strip, duration.split(separator))
                
                # Parse dates
                end_date = datetime.now() if end_str.lower() == 'present' else parse(end_str, fuzzy=True)
                start_date = parse(start_str, fuzzy=True)
                
                # Calculate duration in days
                delta = end_date - start_date
                total_days += delta.days
        except Exception as e:
            continue
    
    return round(total_days / 365.25, 2)

def format_experience(experience):
    """Format experience entries as comma-separated titles with durations"""
    formatted = []
    for entry in experience:
        if isinstance(entry, dict):
            title = entry.get('title', 'N/A')
            duration = entry.get('duration', 'N/A')
            formatted.append(f"{title} ({duration})")
        else:
            match = re.search(r"Title: (.*?)\n.*Duration: (.*?)\n", entry)
            if match:
                title, duration = match.groups()
                formatted.append(f"{title.strip()} ({duration.strip()})")
            else:
                formatted.append(entry)
    return ", ".join(formatted)

def parse_resume_with_gemini(resume_text):
    """Use Gemini to parse resume content"""
    prompt = f"""
    Analyze this resume and return STRICT VALID JSON with this structure:
    {{
        "name": "full name",
        "email": "email address",
        "phone": "phone number",
        "skills": ["list", "of", "skills"],
        "experience": [
            {{
                "title": "job title",
                "duration": "MM/YYYY - MM/YYYY"
            }}
        ]
    }}

    RULES:
    1. Duration format must be "MM/YYYY - MM/YYYY"
    2. Use '-' as date separator
    3. Convert "Present" to current month/year
    4. Include ALL experience entries

    Resume Text:
    {resume_text}
    """
    
    try:
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content(prompt)
        raw_output = response.text
        
        # Clean JSON response
        cleaned_output = re.sub(r'^[^{]*{', '{', raw_output, 1, re.DOTALL)
        cleaned_output = re.sub(r'}[^}]*$', '}', cleaned_output, 1, re.DOTALL)
        cleaned_output = cleaned_output.strip().replace("```json", "").replace("```", "")
        
        return json_repair.loads(cleaned_output)
    except Exception as e:
        st.error(f"Gemini API Error: {str(e)}")
        return None

def reset_session():
    """Clear all session state data"""
    keys_to_reset = ['uploaded_files', 'parsed_data', 'file_uploader']
    for key in keys_to_reset:
        if key in st.session_state:
            del st.session_state[key]

def main():
    st.set_page_config(page_title="Resume Parser", layout="wide")
    st.title("📄 Mazo QuickParse")
    st.markdown("Upload multiple resumes (PDF/DOCX) to extract key information")

    # Initialize session state
    if 'uploaded_files' not in st.session_state:
        st.session_state.uploaded_files = []
    if 'parsed_data' not in st.session_state:
        st.session_state.parsed_data = None

    # File uploader
    uploaded_files = st.file_uploader(
        "Choose files",
        type=["pdf", "docx"],
        accept_multiple_files=True,
        help="Select multiple files using Ctrl/Cmd + Click",
        key="file_uploader"
    )

    # Update session state
    if uploaded_files != st.session_state.get('uploaded_files', []):
        st.session_state.uploaded_files = uploaded_files
        st.session_state.parsed_data = None

    # Parse button
    if st.session_state.uploaded_files and st.session_state.parsed_data is None:
        if st.button("🚀 Parse Resumes", use_container_width=True):
            all_data = []
            success_count = 0
            fail_count = 0
            
            for file in st.session_state.uploaded_files:
                try:
                    with st.spinner(f"Processing {file.name}..."):
                        text = extract_text_from_file(file)
                        if not text:
                            fail_count += 1
                            continue

                        data = parse_resume_with_gemini(text)
                        if not data:
                            fail_count += 1
                            continue

                        # Process experience data
                        exp_entries = data.get('experience', [])
                        
                        # Add calculated fields
                        data['experience'] = format_experience(exp_entries)
                        data['experience_in_years'] = calculate_experience(exp_entries)
                        data['skills'] = ", ".join(data.get('skills', []))
                        data['filename'] = file.name
                        
                        all_data.append(data)
                        success_count += 1

                except Exception as e:
                    st.error(f"Error processing {file.name}: {str(e)}")
                    fail_count += 1

            if all_data:
                # Create DataFrame with ordered columns
                column_order = [
                    'name', 
                    'email', 
                    'phone', 
                    'experience_in_years',
                    'experience',
                    'skills',
                    'filename'
                ]
                
                df = pd.DataFrame(all_data)[column_order]
                # Fix Sno numbering to start from 1
                df = df.reset_index()
                df['index'] = df['index'] + 1
                df = df.rename(columns={'index': 'Sno'})
                df.insert(1, 'Date', datetime.today().strftime('%Y-%m-%d'))
                
                st.session_state.parsed_data = df
                st.success(f"✅ Parsed {success_count} resumes successfully")
                if fail_count > 0:
                    st.warning(f"❌ Failed to parse {fail_count} resumes")
            else:
                st.error("No resumes could be parsed")

    # Display results
    if st.session_state.parsed_data is not None:
        st.dataframe(
            st.session_state.parsed_data.style.format({
                'experience_in_years': '{:.2f} years',
                'experience': lambda x: x
            }),
            height=600,
            use_container_width=True
        )

        # Action buttons
        col1, col2 = st.columns(2)
        with col1:
            excel_file = "Resume_Data.xlsx"
            st.session_state.parsed_data.to_excel(excel_file, index=False)
            with open(excel_file, "rb") as f:
                st.download_button(
                    "💾 Export Excel",
                    f.read(),
                    file_name=excel_file,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
        with col2:
            if st.button("🔄 Reset", use_container_width=True, on_click=reset_session):
                st.rerun()

if __name__ == "__main__":
    main()
