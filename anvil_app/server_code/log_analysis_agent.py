# --- Log Analysis & Root Cause Analysis (RCA) Agent ---
# This agent analyzes raw job logs to identify error patterns and infer root causes

import anvil.server
import os
import json
import re
from datetime import datetime
from dotenv import load_dotenv
import time
import boto3
from botocore.exceptions import ClientError
from collections import defaultdict, Counter
import threading
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
import numpy as np

# --- Load Environment Variables ---
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=dotenv_path)

# --- Configuration & State ---
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
LOGS_QUEUE_NAME = os.getenv("LOGS_QUEUE_NAME", "ci_cd_logs_queue")
ANALYSIS_RESULTS_QUEUE_NAME = os.getenv("ANALYSIS_RESULTS_QUEUE_NAME", "ci_cd_analysis_results_queue")
ANVIL_UPLINK_KEY = os.getenv("ANVIL_UPLINK_KEY")

# Agent's internal state
rca_agent_state = {
    "agent_name": "Log Analysis & RCA Agent",
    "status": "Idle",
    "last_processed": None,
    "errors": 0,
    "messages_processed": 0,
    "root_causes_identified": 0,
    "sqs_status": "Not Configured"
}

print("Log Analysis & RCA Agent is initializing...")

# --- SQS Client Initialization ---
sqs_client_rca = None
if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
    try:
        sqs_client_rca = boto3.client(
            'sqs',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )
        rca_agent_state["sqs_status"] = "Connected"
        print(f"RCA Agent: Successfully connected to SQS.")
    except Exception as e:
        rca_agent_state["sqs_status"] = "Connection Failed"
        print(f"RCA Agent ERROR: Failed to initialize SQS client: {e}")
else:
    print("RCA Agent WARNING: AWS SQS not configured.")

# --- Error Pattern Recognition ---

# Common error patterns and their classifications
ERROR_PATTERNS = {
    "dependency_resolution": [
        r"could not find a version that satisfies",
        r"no matching distribution found",
        r"package.*not found",
        r"dependency.*failed",
        r"requirements.*not satisfied",
        r"module.*not found"
    ],
    "compilation_error": [
        r"compilation failed",
        r"syntax error",
        r"compilation terminated",
        r"error: expected",
        r"undefined reference",
        r"cannot find symbol"
    ],
    "test_failure": [
        r"test.*failed",
        r"assertion.*failed",
        r"expected.*but was",
        r"test case.*failed",
        r"junit.*failure",
        r"pytest.*failed"
    ],
    "network_timeout": [
        r"connection timed out",
        r"read timed out",
        r"network.*timeout",
        r"connection refused",
        r"dns resolution failed",
        r"unable to connect"
    ],
    "resource_exhaustion": [
        r"out of memory",
        r"memory.*exhausted",
        r"disk.*full",
        r"no space left",
        r"resource temporarily unavailable",
        r"too many open files"
    ],
    "permission_denied": [
        r"permission denied",
        r"access denied",
        r"forbidden",
        r"unauthorized",
        r"authentication failed",
        r"insufficient privileges"
    ],
    "configuration_error": [
        r"configuration.*error",
        r"invalid.*configuration",
        r"missing.*configuration",
        r"config.*not found",
        r"environment variable.*not set",
        r"property.*not defined"
    ]
}

# Root cause mapping
ROOT_CAUSE_MAPPING = {
    "dependency_resolution": {
        "cause": "Missing or incompatible dependencies",
        "suggestions": [
            "Check requirements.txt or package.json for missing dependencies",
            "Verify dependency versions are compatible",
            "Update package manager cache",
            "Check for typos in dependency names"
        ]
    },
    "compilation_error": {
        "cause": "Code compilation issues",
        "suggestions": [
            "Review recent code changes for syntax errors",
            "Check compiler version compatibility",
            "Verify all required headers/imports are present",
            "Check for missing semicolons or brackets"
        ]
    },
    "test_failure": {
        "cause": "Test cases failing due to code changes or environment issues",
        "suggestions": [
            "Review recent code changes that might affect tests",
            "Check test data and fixtures",
            "Verify test environment setup",
            "Consider if tests need updating due to feature changes"
        ]
    },
    "network_timeout": {
        "cause": "Network connectivity or external service issues",
        "suggestions": [
            "Check external service availability",
            "Verify network connectivity",
            "Increase timeout values if appropriate",
            "Consider retry mechanisms"
        ]
    },
    "resource_exhaustion": {
        "cause": "Insufficient system resources",
        "suggestions": [
            "Increase memory allocation for the job",
            "Clean up temporary files",
            "Optimize resource usage in code",
            "Consider using larger runner instances"
        ]
    },
    "permission_denied": {
        "cause": "Insufficient permissions or authentication issues",
        "suggestions": [
            "Check file and directory permissions",
            "Verify authentication credentials",
            "Review access control settings",
            "Ensure service accounts have required permissions"
        ]
    },
    "configuration_error": {
        "cause": "Missing or incorrect configuration",
        "suggestions": [
            "Review configuration files for errors",
            "Check environment variable settings",
            "Verify configuration file paths",
            "Ensure all required configuration is present"
        ]
    }
}

def extract_error_lines(log_content):
    """Extract lines that likely contain errors."""
    if not log_content:
        return []
    
    error_lines = []
    lines = log_content.split('\n')
    
    error_keywords = ['error', 'failed', 'failure', 'exception', 'fatal', 'critical']
    
    for line in lines:
        line_lower = line.lower()
        if any(keyword in line_lower for keyword in error_keywords):
            error_lines.append(line.strip())
    
    return error_lines

def classify_error_type(log_content):
    """Classify the error type based on log content."""
    if not log_content:
        return "unknown_error", 0.0
    
    log_lower = log_content.lower()
    
    # Score each error type
    type_scores = {}
    
    for error_type, patterns in ERROR_PATTERNS.items():
        score = 0
        for pattern in patterns:
            matches = len(re.findall(pattern, log_lower))
            score += matches
        
        if score > 0:
            type_scores[error_type] = score
    
    if not type_scores:
        return "unknown_error", 0.0
    
    # Return the error type with highest score
    best_type = max(type_scores, key=type_scores.get)
    max_score = type_scores[best_type]
    
    # Normalize confidence score (simple approach)
    confidence = min(max_score / 5.0, 1.0)  # Scale based on number of matches
    
    return best_type, confidence

def extract_relevant_log_snippet(log_content, error_type, max_length=500):
    """Extract the most relevant log snippet for the identified error."""
    if not log_content:
        return ""
    
    # Get patterns for the identified error type
    patterns = ERROR_PATTERNS.get(error_type, [])
    
    lines = log_content.split('\n')
    relevant_lines = []
    
    # Find lines matching error patterns
    for line in lines:
        line_lower = line.lower()
        for pattern in patterns:
            if re.search(pattern, line_lower):
                relevant_lines.append(line.strip())
                break
    
    # If no specific matches, get general error lines
    if not relevant_lines:
        relevant_lines = extract_error_lines(log_content)
    
    # Join and truncate
    snippet = '\n'.join(relevant_lines[:5])  # Max 5 lines
    if len(snippet) > max_length:
        snippet = snippet[:max_length] + "..."
    
    return snippet

def infer_root_cause(error_type, log_content, confidence):
    """Infer root cause based on error classification."""
    if error_type == "unknown_error" or confidence < 0.3:
        return {
            "inferred_root_cause": "Unable to determine root cause",
            "confidence_score": 0.0,
            "suggestions": ["Manual investigation required", "Check full logs for more details"]
        }
    
    root_cause_info = ROOT_CAUSE_MAPPING.get(error_type, {
        "cause": "Unknown issue",
        "suggestions": ["Manual investigation required"]
    })
    
    return {
        "inferred_root_cause": root_cause_info["cause"],
        "confidence_score": confidence,
        "suggestions": root_cause_info["suggestions"]
    }

def analyze_log_content(log_data):
    """Perform comprehensive log analysis."""
    try:
        run_id = log_data.get("run_id")
        job_id = log_data.get("job_id")
        repo = log_data.get("repo", "unknown")
        log_content = log_data.get("raw_log_content", "")
        
        # Classify error type
        error_type, confidence = classify_error_type(log_content)
        
        # Extract relevant snippet
        relevant_snippet = extract_relevant_log_snippet(log_content, error_type)
        
        # Infer root cause
        root_cause_info = infer_root_cause(error_type, log_content, confidence)
        
        # Basic log statistics
        log_stats = {
            "total_lines": len(log_content.split('\n')) if log_content else 0,
            "error_lines": len(extract_error_lines(log_content)),
            "log_size_bytes": len(log_content.encode('utf-8')) if log_content else 0
        }
        
        analysis_result = {
            "run_id": run_id,
            "job_id": job_id,
            "repo": repo,
            "error_type": error_type,
            "confidence_score": confidence,
            "relevant_log_snippet": relevant_snippet,
            "log_statistics": log_stats,
            **root_cause_info
        }
        
        return analysis_result
        
    except Exception as e:
        print(f"RCA Agent: Error analyzing log content: {e}")
        rca_agent_state["errors"] += 1
        return None

def send_rca_result(analysis_result):
    """Send RCA result to analysis results queue."""
    if not analysis_result:
        return False
    
    message = {
        "analysis_type": "root_cause_identified",
        "run_id": analysis_result.get("run_id"),
        "job_id": analysis_result.get("job_id"),
        "repo": analysis_result.get("repo", "unknown"),
        "error_type": analysis_result["error_type"],
        "inferred_root_cause": analysis_result["inferred_root_cause"],
        "confidence_score": analysis_result["confidence_score"],
        "relevant_log_snippet": analysis_result["relevant_log_snippet"],
        "suggestions": analysis_result["suggestions"],
        "timestamp": datetime.utcnow().isoformat(),
        "message": f"Root cause analysis completed: {analysis_result['error_type']}",
        "agent": "log_analysis_rca_agent"
    }
    
    if sqs_client_rca and rca_agent_state["sqs_status"] == "Connected":
        try:
            response = sqs_client_rca.get_queue_url(QueueName=ANALYSIS_RESULTS_QUEUE_NAME)
            queue_url = response['QueueUrl']
            sqs_client_rca.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(message)
            )
            print(f"RCA result sent to SQS for job {analysis_result.get('job_id', 'unknown')}")
            return True
        except Exception as e:
            print(f"ERROR: Failed to send RCA result to SQS: {e}")
            rca_agent_state["errors"] += 1
            return False
    else:
        print(f"--- Root Cause Analysis Result (SQS not connected) ---")
        print(json.dumps(message, indent=2))
        print("------------------------------------------------------------------")
        return True

def process_log_message(message_body):
    """Process a log message from the logs queue."""
    try:
        data = json.loads(message_body)
        event_type = data.get("event_type", "")
        
        # Only process job log messages
        if event_type != "job_log_processed":
            return False
        
        log_data = data.get("data", {})
        
        # Perform log analysis
        analysis_result = analyze_log_content(log_data)
        
        if analysis_result:
            success = send_rca_result(analysis_result)
            if success:
                rca_agent_state["root_causes_identified"] += 1
            return success
        
        return False
        
    except Exception as e:
        print(f"RCA Agent: Error processing log message: {e}")
        rca_agent_state["errors"] += 1
        return False

def poll_logs_queue():
    """Continuously poll the logs queue for new messages."""
    if not sqs_client_rca:
        print("RCA Agent: SQS client not available.")
        return
    
    try:
        response = sqs_client_rca.get_queue_url(QueueName=LOGS_QUEUE_NAME)
        queue_url = response['QueueUrl']
    except Exception as e:
        print(f"RCA Agent: Cannot access logs queue: {e}")
        return
    
    print("RCA Agent: Starting to poll logs queue...")
    rca_agent_state["status"] = "Polling Logs Queue"
    
    while True:
        try:
            response = sqs_client_rca.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=5
            )
            
            messages = response.get('Messages', [])
            for message in messages:
                success = process_log_message(message['Body'])
                
                if success:
                    rca_agent_state["messages_processed"] += 1
                    rca_agent_state["last_processed"] = time.time()
                    
                    # Delete message from queue
                    sqs_client_rca.delete_message(
                        QueueUrl=queue_url,
                        ReceiptHandle=message['ReceiptHandle']
                    )
            
            time.sleep(1)
            
        except KeyboardInterrupt:
            print("RCA Agent: Stopping queue polling...")
            break
        except Exception as e:
            print(f"RCA Agent: Error during polling: {e}")
            rca_agent_state["errors"] += 1
            time.sleep(5)

# --- Anvil Callable Functions ---

@anvil.server.callable
def get_rca_status():
    """Returns the current status of the RCA agent."""
    return {
        "status": rca_agent_state["status"],
        "root_causes_identified": rca_agent_state["root_causes_identified"],
        "messages_processed": rca_agent_state["messages_processed"],
        "errors": rca_agent_state["errors"],
        "last_analysis": rca_agent_state.get("last_analysis", "Never")
    }

@anvil.server.callable
def trigger_manual_rca():
    """Manually trigger RCA analysis for testing."""
    print("\n=== Manual Root Cause Analysis Triggered ===")
    rca_agent_state["status"] = "Manual Analysis..."
    
    try:
        # Create sample log data for demonstration
        sample_logs = [
            {
                "job_id": "123",
                "job_name": "build",
                "log_content": "Error: Could not connect to database. Connection timeout after 30 seconds. Check network connectivity."
            },
            {
                "job_id": "124",
                "job_name": "test",
                "log_content": "FAILED: test_user_authentication - AssertionError: Expected 200 but got 500. Server returned: Internal Server Error"
            },
            {
                "job_id": "125",
                "job_name": "deploy",
                "log_content": "Permission denied: Cannot write to /var/www/html. Check file permissions and user access rights."
            },
            {
                "job_id": "126",
                "job_name": "integration_test",
                "log_content": "ModuleNotFoundError: No module named 'requests'. Please install required dependencies using pip install -r requirements.txt"
            }
        ]
        
        print("Analyzing sample log data for root causes...")
        
        root_causes_found = []
        
        for log_data in sample_logs:
            job_id = log_data["job_id"]
            job_name = log_data["job_name"]
            log_content = log_data["log_content"]
            
            print(f"\nAnalyzing Job {job_id} ({job_name}):")
            print(f"Log: {log_content[:100]}...")
            
            # Perform RCA analysis
            rca_result = analyze_log_for_rca(log_content) if log_content else None
            
            if rca_result:
                rca_result["job_id"] = job_id
                rca_result["job_name"] = job_name
                root_causes_found.append(rca_result)
                
                print(f"  → Root Cause: {rca_result['root_cause']}")
                print(f"  → Category: {rca_result['error_category']}")
                print(f"  → Confidence: {rca_result['confidence']:.1%}")
                print(f"  → Recommendation: {rca_result['recommendation']}")
        
        # Display comprehensive results
        print(f"\n--- ROOT CAUSE ANALYSIS RESULTS ---")
        print(f"Analyzed {len(sample_logs)} job logs")
        print(f"Identified {len(root_causes_found)} root causes")
        
        # Categorize root causes
        categories = {}
        for rca in root_causes_found:
            category = rca['error_category']
            if category not in categories:
                categories[category] = []
            categories[category].append(rca)
        
        print(f"\nRoot Cause Categories:")
        for category, rcas in categories.items():
            print(f"  {category}: {len(rcas)} issues")
            for rca in rcas:
                print(f"    - {rca['job_name']}: {rca['root_cause']}")
        
        # Send results to analysis queue
        analysis_result = {
            "analysis_type": "root_cause_analysis",
            "root_causes_identified": len(root_causes_found),
            "total_logs_analyzed": len(sample_logs),
            "root_causes": root_causes_found,
            "categories": categories,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Send results to analysis queue (or print if SQS not available)
        print(f"--- Analysis Result (SQS not connected) ---")
        print(json.dumps(analysis_result, indent=2)[:500] + "...")
        print("-" * 50)
        success = True
        
        rca_agent_state["status"] = "Manual analysis completed"
        rca_agent_state["last_analysis"] = time.time()
        rca_agent_state["root_causes_identified"] += len(root_causes_found)
        
        print("\n=== Root Cause Analysis Complete ===")
        return {"message": f"Identified {len(root_causes_found)} root causes from {len(sample_logs)} logs"}
        
    except Exception as e:
        print(f"Error in manual RCA analysis: {e}")
        rca_agent_state["status"] = "Manual analysis error"
        rca_agent_state["errors"] += 1
        return {"message": f"Error: {str(e)}"}

@anvil.server.callable
def analyze_sample_log(log_content):
    """Manually analyze a sample log for testing."""
    print("Manual log analysis triggered.")
    
    sample_data = {
        "run_id": "sample_run",
        "job_id": "sample_job",
        "repo": "sample_repo",
        "raw_log_content": log_content
    }
    
    result = analyze_log_content(sample_data)
    return result if result else {"error": "Failed to analyze log content"}

# --- Main Agent Function ---

def run_log_analysis_agent():
    """Main function to keep the log analysis agent running."""
    if not ANVIL_UPLINK_KEY:
        print("RCA Agent ERROR: Missing ANVIL_UPLINK_KEY.")
        return
    
    try:
        anvil.server.connect(ANVIL_UPLINK_KEY)
        print("Log Analysis & RCA Agent successfully connected to Anvil Uplink.")
        rca_agent_state["status"] = "Connected to Anvil"
        
        # Start SQS polling if available
        if sqs_client_rca and rca_agent_state["sqs_status"] == "Connected":
            polling_thread = threading.Thread(target=poll_logs_queue, daemon=True)
            polling_thread.start()
            print("RCA Agent: SQS polling thread started.")
        
        anvil.server.wait_forever()
        
    except Exception as e:
        print(f"Log Analysis & RCA Agent failed to connect: {e}")
        rca_agent_state["status"] = "Anvil Connection Failed"

if __name__ == "__main__":
    run_log_analysis_agent()
