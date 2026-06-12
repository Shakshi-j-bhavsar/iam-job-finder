import os
import time
from dotenv import load_dotenv
load_dotenv()

import threading
import uuid
from io import BytesIO
from datetime import datetime
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import pandas as pd
import re


app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

# Configuration
MAX_JOBS = 70  # Stop searching when we reach this many jobs

# Core IAM keywords (only these will be considered)
CORE_IAM_KEYWORDS = [
    "IAM", "Identity and Access Management", "Identity Governance", "IGA",
    "PAM", "Privileged Access Management", "SailPoint", "CyberArk", "Saviynt",
    "Okta", "Ping Identity", "Entra ID", "Azure AD"
]

# IAM tools and platforms (for secondary verification)
IAM_TOOLS = [
    "sailpoint", "cyberark", "saviynt", "okta", "ping identity", "entra id",
    "azure ad", "active directory", "forgerock", "keycloak", "auth0",
    "beyondtrust", "delinea", "thycotic", "centrify", "onelogin"
]

# Words that indicate it's NOT an IAM job (to filter out)
EXCLUDE_WORDS = [
    "software engineer", "full stack", "frontend", "backend", "devops engineer",
    "data engineer", "data scientist", "machine learning", "ai engineer",
    "network engineer", "system administrator", "help desk", "it support",
    "sales", "marketing", "recruiter", "hr", "accountant", "finance"
]

# Strong IAM role indicators (must have at least one)
STRONG_IAM_INDICATORS = [
    "iam", "identity", "access management", "privileged access", "pam",
    "iga", "identity governance", "sailpoint", "cyberark", "saviynt",
    "okta", "ping", "entra", "azure ad", "active directory"
]

def is_genuine_iam_job(title, company, description=""):
    """Strictly check if a job is truly an IAM role"""
    if not title:
        return False
    
    title_lower = title.lower()
    company_lower = company.lower() if company else ""
    desc_lower = description.lower() if description else ""
    
    # First, exclude obviously non-IAM roles
    for exclude in EXCLUDE_WORDS:
        if exclude in title_lower:
            return False
    
    # Must have at least one strong IAM indicator
    has_iam_indicator = False
    for indicator in STRONG_IAM_INDICATORS:
        if indicator in title_lower or indicator in desc_lower:
            has_iam_indicator = True
            break
    
    if not has_iam_indicator:
        return False
    
    # Check for IAM tools (adds confidence)
    has_tool = False
    for tool in IAM_TOOLS:
        if tool in title_lower or tool in desc_lower:
            has_tool = True
            break
    
    # If no IAM tool mentioned but title has generic IAM terms, still accept
    generic_iam = ["iam", "identity access", "access management", "privileged access"]
    has_generic = any(term in title_lower for term in generic_iam)
    
    return has_tool or has_generic

# Major US cities for comprehensive search
US_LOCATIONS = [
    "New York, NY", "San Francisco, CA", "Austin, TX", "Seattle, WA",
    "Chicago, IL", "Boston, MA", "Los Angeles, CA", "Dallas, TX",
    "Atlanta, GA", "Washington, DC", "Denver, CO", "Phoenix, AZ",
    "United States"  # Broad search last
]

# In-memory store for active searches
active_searches = {}

def log_message(msg):
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{timestamp}] {msg}")

def safe_date_format(date_value):
    """Safely format a date value to string"""
    if date_value is None:
        return 'N/A'
    if isinstance(date_value, float):
        if pd.isna(date_value):
            return 'N/A'
        return 'N/A'
    if hasattr(date_value, 'strftime'):
        return date_value.strftime('%Y-%m-%d')
    return str(date_value)[:10] if str(date_value) else 'N/A'

def run_search(search_id, location, job_type):
    global active_searches
    all_results = []
    
    try:
        from jobspy import scrape_jobs
        import time
        
        if location == "United States":
            locations_to_search = US_LOCATIONS[:8]
            log_message(f"Search {search_id}: Will search {len(locations_to_search)} locations until {MAX_JOBS} jobs")
        else:
            locations_to_search = [location]
        
        for i, loc in enumerate(locations_to_search):
            if not active_searches.get(search_id, {}).get('active', False):
                break
            
            if len(all_results) >= MAX_JOBS:
                log_message(f"Search {search_id}: Reached target of {MAX_JOBS} jobs")
                break
            
            log_message(f"Search {search_id}: Searching {loc} ({i+1}/{len(locations_to_search)}) - Found {len(all_results)}/{MAX_JOBS}")
            
            # REMOVED GOOGLE - only Indeed and LinkedIn
            for keyword in CORE_IAM_KEYWORDS[:3]:
                if not active_searches.get(search_id, {}).get('active', False):
                    break
                
                if len(all_results) >= MAX_JOBS:
                    break
                    
                try:
                    time.sleep(2)  # 2 second delay
                    
                    jobs_df = scrape_jobs(
                        site_name=["indeed", "linkedin"],  # No Google
                        search_term=keyword,
                        location=loc,
                        results_wanted=15,
                        hours_old=168,
                        job_type=job_type.lower(),
                        remote_only=False,
                    )
                    
                    if jobs_df is not None and not jobs_df.empty:
                        for idx, row in jobs_df.iterrows():
                            if len(all_results) >= MAX_JOBS:
                                break
                                
                            title = str(row.get('title', ''))
                            company = str(row.get('company', ''))
                            
                            if is_genuine_iam_job(title, company, ''):
                                job_data = {
                                    "title": title,
                                    "company": company,
                                    "location": str(row.get('location', loc)),
                                    "job_url": str(row.get('job_url', '#')),
                                    "source": str(row.get('site', 'N/A')),
                                    "posted_date": safe_date_format(row.get('date_posted'))
                                }
                                
                                exists = any(j['title'] == job_data['title'] for j in all_results)
                                if not exists:
                                    all_results.append(job_data)
                                    
                except Exception as e:
                    log_message(f"Error: {e}")
                    continue
            
            # Update results
            if search_id in active_searches:
                processed = process_and_score_jobs(all_results)
                active_searches[search_id]['results'] = processed
                active_searches[search_id]['total_raw'] = len(all_results)
        
        final_results = process_and_score_jobs(all_results)
        
        if search_id in active_searches:
            active_searches[search_id]['results'] = final_results
            log_message(f"Search {search_id}: COMPLETED - Found {len(final_results)} IAM contract jobs")
        
    except Exception as e:
        log_message(f"Search {search_id} error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if search_id in active_searches:
            active_searches[search_id]['active'] = False

def process_and_score_jobs(jobs_list):
    """Process and score jobs based on IAM relevance"""
    if not jobs_list:
        return []
    
    # Remove duplicates
    unique_jobs = {}
    for job in jobs_list:
        key = f"{job['title']}_{job['company']}"
        if key not in unique_jobs:
            unique_jobs[key] = job
    
    jobs_list = list(unique_jobs.values())
    
    # Score each job
    for job in jobs_list:
        title_lower = job['title'].lower()
        score = 5  # Base score
        
        # Core IAM terms give higher score
        core_terms = ["iam", "identity", "access management", "privileged access", "pam", "iga"]
        for term in core_terms:
            if term in title_lower:
                score += 3
                break
        
        # IAM tools give additional points
        for tool in IAM_TOOLS:
            if tool in title_lower:
                score += 2
                break
        
        # Contract indicators
        contract_indicators = ['contract', 'freelance', 'consultant', 'c2c', 'w2']
        for ci in contract_indicators:
            if ci in title_lower:
                score += 1
                break
        
        # Cap at 10
        score = min(score, 10)
        
        # Determine verdict
        if score >= 8:
            verdict = "apply"
        elif score >= 6:
            verdict = "consider"
        else:
            verdict = "skip"
        
        job['relevance_score'] = score
        job['ai_verdict'] = verdict
    
    # Sort by score (highest first)
    jobs_list.sort(key=lambda x: x['relevance_score'], reverse=True)
    
    # Add sequential IDs
    for i, job in enumerate(jobs_list):
        job['id'] = i + 1
    
    return jobs_list

# Flask Routes
@app.route('/')
def index():
    return send_file('static/index.html')

@app.route('/start_search', methods=['POST'])
def start_search():
    data = request.get_json()
    location = data.get('location', 'United States')
    job_type = data.get('jobType', 'Contract')
    fast_mode = data.get('fast_mode', False)  # Get fast mode flag
    
    search_id = str(uuid.uuid4())
    
    # Adjust settings based on fast mode
    if fast_mode:
        # Fast mode settings
        locations_to_search = ["United States"]  # Only 1 location
        keywords_to_search = ["IAM"]  # Only 1 keyword
        max_jobs = 25  # Stop at 25 jobs
    else:
        # Normal mode settings
        locations_to_search = US_LOCATIONS[:8]  # Multiple locations
        keywords_to_search = CORE_IAM_KEYWORDS[:4]  # More keywords
        max_jobs = MAX_JOBS
    
    # Pass these to your search function
    # ... rest of your code

@app.route('/search_results/<search_id>')
def search_results(search_id):
    if search_id in active_searches:
        return jsonify({
            'active': active_searches[search_id]['active'],
            'results': active_searches[search_id]['results'],
            'total_raw': active_searches[search_id].get('total_raw', 0),
            'target': MAX_JOBS
        })
    else:
        return jsonify({'active': False, 'results': [], 'total_raw': 0, 'target': MAX_JOBS})
@app.route('/check_results/<search_id>')
def check_results(search_id):
    """Debug endpoint to check if results exist"""
    if search_id in active_searches:
        return jsonify({
            'exists': True,
            'active': active_searches[search_id]['active'],
            'results_count': len(active_searches[search_id]['results'])
        })
    else:
        return jsonify({'exists': False, 'message': 'Search ID not found'})
@app.route('/stop_search/<search_id>', methods=['POST'])
def stop_search(search_id):
    if search_id in active_searches:
        active_searches[search_id]['active'] = False
        log_message(f"⏹️ Stopped search: {search_id[:8]}")
    return jsonify({'status': 'stopped'})

@app.route('/export/<search_id>')
def export_excel(search_id):
    if search_id not in active_searches:
        return "No search found", 404
    
    results = active_searches[search_id]['results']
    if not results:
        return "No results to export", 404
    
    # Prepare data for export - EXCLUDING relevance_score and ai_verdict
    export_data = []
    for job in results:
        export_data.append({
            "Job ID": job.get('id', ''),
            "Title": job.get('title', ''),
            "Company": job.get('company', ''),
            "Location": job.get('location', ''),
            "Source": job.get('source', ''),
            "Posted Date": job.get('posted_date', ''),
            "Job URL": job.get('job_url', '')
        })
    
    # Create DataFrame
    df = pd.DataFrame(export_data)
    
    # Create Excel file in memory
    output = BytesIO()
    try:
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name="IAM_Contract_Jobs")
        output.seek(0)
        
        # Generate filename with timestamp
        filename = f"iam_jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        log_message(f"Export error: {e}")
        return f"Error creating Excel file: {str(e)}", 500

if __name__ == '__main__':
    print("=" * 60)
    print("🔐 IAM Contract Job Finder")
    print("=" * 60)
    print(f"📍 Open http://localhost:5000 in your browser")
    print(f"🎯 Will stop after finding {MAX_JOBS} jobs")
    print("🚀 Click 'Search IAM Jobs' to start finding contract positions")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
