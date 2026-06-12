import os
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
import time

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

# Configuration
MAX_JOBS = 70

# Core IAM keywords
CORE_IAM_KEYWORDS = [
    "IAM", "Identity and Access Management", "Identity Governance", "IGA",
    "PAM", "Privileged Access Management", "SailPoint", "CyberArk", "Saviynt",
    "Okta", "Ping Identity", "Entra ID", "Azure AD"
]

IAM_TOOLS = [
    "sailpoint", "cyberark", "saviynt", "okta", "ping identity", "entra id",
    "azure ad", "active directory", "forgerock", "keycloak", "auth0"
]

EXCLUDE_WORDS = [
    "software engineer", "full stack", "frontend", "backend", "devops engineer",
    "data engineer", "data scientist", "machine learning", "ai engineer",
    "network engineer", "system administrator", "help desk", "it support"
]

STRONG_IAM_INDICATORS = [
    "iam", "identity", "access management", "privileged access", "pam",
    "iga", "identity governance", "sailpoint", "cyberark", "saviynt"
]

US_LOCATIONS = [
    "New York, NY", "San Francisco, CA", "Austin, TX", "Seattle, WA",
    "Chicago, IL", "Boston, MA", "Los Angeles, CA", "Dallas, TX",
    "Atlanta, GA", "Washington, DC"
]

active_searches = {}

def log_message(msg):
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{timestamp}] {msg}")

def safe_date_format(date_value):
    if date_value is None:
        return 'N/A'
    if isinstance(date_value, float):
        return 'N/A'
    if hasattr(date_value, 'strftime'):
        return date_value.strftime('%Y-%m-%d')
    return str(date_value)[:10] if str(date_value) else 'N/A'

def is_genuine_iam_job(title, company, description=""):
    if not title:
        return False
    
    title_lower = title.lower()
    
    for exclude in EXCLUDE_WORDS:
        if exclude in title_lower:
            return False
    
    has_iam_indicator = False
    for indicator in STRONG_IAM_INDICATORS:
        if indicator in title_lower:
            has_iam_indicator = True
            break
    
    if not has_iam_indicator:
        return False
    
    has_tool = False
    for tool in IAM_TOOLS:
        if tool in title_lower:
            has_tool = True
            break
    
    generic_iam = ["iam", "identity access", "access management", "privileged access"]
    has_generic = any(term in title_lower for term in generic_iam)
    
    return has_tool or has_generic

def process_and_score_jobs(jobs_list):
    if not jobs_list:
        return []
    
    unique_jobs = {}
    for job in jobs_list:
        key = f"{job['title']}_{job['company']}"
        if key not in unique_jobs:
            unique_jobs[key] = job
    
    jobs_list = list(unique_jobs.values())
    
    for job in jobs_list:
        title_lower = job['title'].lower()
        score = 5
        
        core_terms = ["iam", "identity", "access management", "privileged access", "pam", "iga"]
        for term in core_terms:
            if term in title_lower:
                score += 3
                break
        
        for tool in IAM_TOOLS:
            if tool in title_lower:
                score += 2
                break
        
        contract_indicators = ['contract', 'freelance', 'consultant', 'c2c', 'w2']
        for ci in contract_indicators:
            if ci in title_lower:
                score += 1
                break
        
        score = min(score, 10)
        
        if score >= 8:
            verdict = "apply"
        elif score >= 6:
            verdict = "consider"
        else:
            verdict = "skip"
        
        job['relevance_score'] = score
        job['ai_verdict'] = verdict
    
    jobs_list.sort(key=lambda x: x['relevance_score'], reverse=True)
    
    for i, job in enumerate(jobs_list):
        job['id'] = i + 1
    
    return jobs_list

def run_search(search_id, location, job_type):
    global active_searches
    all_results = []
    
    try:
        from jobspy import scrape_jobs
        
        if location == "United States":
            locations_to_search = US_LOCATIONS[:5]
            log_message(f"Search {search_id}: Searching {len(locations_to_search)} US locations")
        else:
            locations_to_search = [location]
        
        for i, loc in enumerate(locations_to_search):
            if not active_searches.get(search_id, {}).get('active', False):
                break
            
            if len(all_results) >= MAX_JOBS:
                break
            
            log_message(f"Search {search_id}: Searching {loc} ({i+1}/{len(locations_to_search)}) - Found {len(all_results)}/{MAX_JOBS}")
            
            for keyword in CORE_IAM_KEYWORDS[:3]:
                if not active_searches.get(search_id, {}).get('active', False):
                    break
                
                if len(all_results) >= MAX_JOBS:
                    break
                    
                try:
                    time.sleep(1)
                    
                    jobs_df = scrape_jobs(
                        site_name=["indeed", "linkedin"],
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

@app.route('/')
def index():
    return send_file('static/index.html')

@app.route('/start_search', methods=['POST'])
def start_search():
    data = request.get_json()
    location = data.get('location', 'United States')
    job_type = data.get('jobType', 'Contract')
    
    search_id = str(uuid.uuid4())
    active_searches[search_id] = {
        'active': True, 
        'results': [],
        'total_raw': 0,
        'start_time': datetime.now().isoformat()
    }
    
    log_message(f"🚀 Started search: {location} | {job_type} | Target: {MAX_JOBS} jobs")
    
    thread = threading.Thread(
        target=run_search, 
        args=(search_id, location, job_type), 
        daemon=True
    )
    thread.start()
    return jsonify({'search_id': search_id})

@app.route('/search_results/<search_id>')
def search_results(search_id):
    if search_id in active_searches:
        return jsonify({
            'active': active_searches[search_id]['active'],
            'results': active_searches[search_id]['results'],
            'total_raw': active_searches[search_id].get('total_raw', 0)
        })
    else:
        return jsonify({'active': False, 'results': [], 'total_raw': 0})

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
    
    df = pd.DataFrame(export_data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name="IAM_Contract_Jobs")
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f"iam_jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    )

if __name__ == '__main__':
    print("=" * 60)
    print("🔐 IAM Contract Job Finder")
    print("=" * 60)
    print(f"📍 Open http://localhost:5000 in your browser")
    print(f"🎯 Will stop after finding {MAX_JOBS} jobs")
    print("🚀 Click 'Search IAM Jobs' to start finding contract positions")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
