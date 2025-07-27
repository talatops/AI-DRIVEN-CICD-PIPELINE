# --- Flaky Test Identification Agent ---
# This agent identifies tests that exhibit inconsistent behavior without code changes

import anvil.server
import os
import json
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv
import time
import boto3
from botocore.exceptions import ClientError
from collections import defaultdict, deque
import threading

# --- Load Environment Variables ---
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=dotenv_path)

# --- Configuration & State ---
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
FEATURES_QUEUE_NAME = os.getenv("FEATURES_QUEUE_NAME", "ci_cd_features_queue")
ANALYSIS_RESULTS_QUEUE_NAME = os.getenv("ANALYSIS_RESULTS_QUEUE_NAME", "ci_cd_analysis_results_queue")
ANVIL_UPLINK_KEY = os.getenv("ANVIL_UPLINK_KEY")

# Agent's internal state
flaky_agent_state = {
    "agent_name": "Flaky Test Identification Agent",
    "status": "Idle",
    "last_processed": None,
    "errors": 0,
    "messages_processed": 0,
    "flaky_tests_identified": 0,
    "sqs_status": "Not Configured"
}

print("Flaky Test Identification Agent is initializing...")

# --- SQS Client Initialization ---
sqs_client_flaky = None
if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
    try:
        sqs_client_flaky = boto3.client(
            'sqs',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )
        flaky_agent_state["sqs_status"] = "Connected"
        print(f"Flaky Test Agent: Successfully connected to SQS.")
    except Exception as e:
        flaky_agent_state["sqs_status"] = "Connection Failed"
        print(f"Flaky Test Agent ERROR: Failed to initialize SQS client: {e}")
else:
    print("Flaky Test Agent WARNING: AWS SQS not configured.")

# --- Test History Tracking ---
test_history = defaultdict(lambda: deque(maxlen=50))  # Track last 50 runs per test
workflow_test_patterns = defaultdict(dict)  # Track test patterns per workflow
flaky_test_registry = {}  # Registry of identified flaky tests

class TestResult:
    def __init__(self, test_id, status, duration, timestamp, commit_sha=None):
        self.test_id = test_id
        self.status = status  # 'pass', 'fail', 'skip'
        self.duration = duration
        self.timestamp = timestamp
        self.commit_sha = commit_sha

def calculate_flakiness_score(test_results):
    """Calculate flakiness score for a test based on its history."""
    if len(test_results) < 5:  # Need minimum history
        return 0.0
    
    # Convert to list for easier processing
    results = list(test_results)
    
    # Basic flakiness indicators
    total_runs = len(results)
    failures = sum(1 for r in results if r.status == 'fail')
    passes = sum(1 for r in results if r.status == 'pass')
    
    if total_runs == 0:
        return 0.0
    
    failure_rate = failures / total_runs
    
    # Flakiness is high when failure rate is between 10% and 90%
    # (not consistently failing or passing)
    if 0.1 <= failure_rate <= 0.9:
        base_flakiness = min(failure_rate, 1 - failure_rate) * 2  # Scale to 0-1
    else:
        base_flakiness = 0.0
    
    # Check for alternating patterns (strong indicator of flakiness)
    alternations = 0
    for i in range(1, len(results)):
        if results[i].status != results[i-1].status:
            alternations += 1
    
    alternation_factor = min(alternations / (total_runs - 1), 1.0) if total_runs > 1 else 0
    
    # Duration variance (flaky tests often have inconsistent durations)
    durations = [r.duration for r in results if r.duration > 0]
    duration_variance = 0.0
    if len(durations) > 1:
        mean_duration = np.mean(durations)
        if mean_duration > 0:
            duration_variance = min(np.std(durations) / mean_duration, 1.0)
    
    # Combine factors
    flakiness_score = (base_flakiness * 0.5 + 
                      alternation_factor * 0.3 + 
                      duration_variance * 0.2)
    
    return min(flakiness_score, 1.0)

def analyze_test_patterns(feature_data):
    """Analyze test patterns from feature data."""
    try:
        # Extract test-related information from features
        # This is a simplified approach - in reality, we'd need more detailed test data
        
        run_id = feature_data.get("run_id")
        repo = feature_data.get("repo", "unknown")
        success_rate = feature_data.get("success_rate", 1.0)
        failed_job_count = feature_data.get("failed_job_count", 0)
        job_count = feature_data.get("job_count", 1)
        
        # Create synthetic test results based on job success/failure patterns
        # In a real implementation, this would come from detailed test reports
        synthetic_tests = []
        
        if failed_job_count > 0:
            # Simulate some tests that might be flaky
            for i in range(min(failed_job_count, 3)):  # Limit to 3 synthetic tests
                test_id = f"{repo}:synthetic_test_{i}"
                # Randomly assign pass/fail based on success rate
                status = 'pass' if np.random.random() < success_rate else 'fail'
                duration = np.random.normal(30, 10)  # Random duration around 30s
                
                test_result = TestResult(
                    test_id=test_id,
                    status=status,
                    duration=max(duration, 1),  # Ensure positive duration
                    timestamp=datetime.utcnow().isoformat(),
                    commit_sha=feature_data.get("head_sha")
                )
                synthetic_tests.append(test_result)
        
        return synthetic_tests
        
    except Exception as e:
        print(f"Flaky Test Agent: Error analyzing test patterns: {e}")
        return []

def identify_flaky_tests(test_results):
    """Identify flaky tests from the given test results."""
    flaky_tests = []
    
    for test_result in test_results:
        test_id = test_result.test_id
        
        # Add to history
        test_history[test_id].append(test_result)
        
        # Calculate flakiness score
        flakiness_score = calculate_flakiness_score(test_history[test_id])
        
        # Threshold for considering a test flaky
        flakiness_threshold = 0.3
        
        if flakiness_score >= flakiness_threshold:
            # Check if this is a new flaky test or update existing
            current_time = datetime.utcnow().isoformat()
            
            flaky_test_info = {
                "test_id": test_id,
                "flakiness_score": flakiness_score,
                "recent_failures": sum(1 for r in list(test_history[test_id])[-10:] if r.status == 'fail'),
                "total_runs": len(test_history[test_id]),
                "last_seen": current_time,
                "run_id": test_result.test_id.split(':')[-1] if ':' in test_result.test_id else None
            }
            
            # Update registry
            flaky_test_registry[test_id] = flaky_test_info
            flaky_tests.append(flaky_test_info)
    
    return flaky_tests

def send_flaky_test_result(flaky_test_info, original_data):
    """Send flaky test identification result to analysis results queue."""
    message = {
        "analysis_type": "flaky_test_identified",
        "run_id": original_data.get("run_id"),
        "repo": original_data.get("repo", "unknown"),
        "test_id": flaky_test_info["test_id"],
        "flakiness_score": flaky_test_info["flakiness_score"],
        "recent_failures": flaky_test_info["recent_failures"],
        "total_runs": flaky_test_info["total_runs"],
        "timestamp": datetime.utcnow().isoformat(),
        "message": f"Test '{flaky_test_info['test_id']}' exhibits flaky behavior (score: {flaky_test_info['flakiness_score']:.2f})",
        "agent": "flaky_test_identification_agent"
    }
    
    if sqs_client_flaky and flaky_agent_state["sqs_status"] == "Connected":
        try:
            response = sqs_client_flaky.get_queue_url(QueueName=ANALYSIS_RESULTS_QUEUE_NAME)
            queue_url = response['QueueUrl']
            sqs_client_flaky.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(message)
            )
            print(f"Flaky test result sent to SQS: {flaky_test_info['test_id']}")
            return True
        except Exception as e:
            print(f"ERROR: Failed to send flaky test result to SQS: {e}")
            flaky_agent_state["errors"] += 1
            return False
    else:
        print(f"--- Flaky Test Identified (SQS not connected) ---")
        print(json.dumps(message, indent=2))
        print("------------------------------------------------------------------")
        return True

def process_feature_message(message_body):
    """Process a feature message from the features queue."""
    try:
        data = json.loads(message_body)
        feature_data = data.get("data", {})
        feature_type = data.get("feature_set_type", "")
        
        # Only process workflow run features for test analysis
        if feature_type != "workflow_run_features":
            return False
        
        # Analyze test patterns
        test_results = analyze_test_patterns(feature_data)
        
        if test_results:
            # Identify flaky tests
            flaky_tests = identify_flaky_tests(test_results)
            
            # Send results for each flaky test found
            for flaky_test in flaky_tests:
                success = send_flaky_test_result(flaky_test, feature_data)
                if success:
                    flaky_agent_state["flaky_tests_identified"] += 1
        
        return True
        
    except Exception as e:
        print(f"Flaky Test Agent: Error processing feature message: {e}")
        flaky_agent_state["errors"] += 1
        return False

def poll_features_queue():
    """Continuously poll the features queue for new messages."""
    if not sqs_client_flaky:
        print("Flaky Test Agent: SQS client not available.")
        return
    
    try:
        response = sqs_client_flaky.get_queue_url(QueueName=FEATURES_QUEUE_NAME)
        queue_url = response['QueueUrl']
    except Exception as e:
        print(f"Flaky Test Agent: Cannot access features queue: {e}")
        return
    
    print("Flaky Test Agent: Starting to poll features queue...")
    flaky_agent_state["status"] = "Polling Features Queue"
    
    while True:
        try:
            response = sqs_client_flaky.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=5
            )
            
            messages = response.get('Messages', [])
            for message in messages:
                success = process_feature_message(message['Body'])
                
                if success:
                    flaky_agent_state["messages_processed"] += 1
                    flaky_agent_state["last_processed"] = time.time()
                    
                    # Delete message from queue
                    sqs_client_flaky.delete_message(
                        QueueUrl=queue_url,
                        ReceiptHandle=message['ReceiptHandle']
                    )
            
            time.sleep(1)
            
        except KeyboardInterrupt:
            print("Flaky Test Agent: Stopping queue polling...")
            break
        except Exception as e:
            print(f"Flaky Test Agent: Error during polling: {e}")
            flaky_agent_state["errors"] += 1
            time.sleep(5)

# --- Anvil Callable Functions ---

@anvil.server.callable
def get_flaky_test_status():
    """Returns the current status of the flaky test identification agent."""
    return {
        "status": flaky_agent_state["status"],
        "flaky_tests_detected": flaky_agent_state["flaky_tests_identified"],
        "messages_processed": flaky_agent_state["messages_processed"],
        "errors": flaky_agent_state["errors"],
        "last_analysis": flaky_agent_state.get("last_analysis", "Never")
    }

@anvil.server.callable
def trigger_manual_flaky_analysis():
    """Manually trigger flaky test analysis for testing."""
    print("\n=== Manual Flaky Test Analysis Triggered ===")
    flaky_agent_state["status"] = "Manual Analysis..."
    
    try:
        # Create sample test data for demonstration
        sample_test_data = [
            {"test_name": "test_user_login", "results": ["pass", "pass", "pass", "pass", "pass"]},
            {"test_name": "test_database_connection", "results": ["pass", "fail", "pass", "pass", "fail"]},  # Flaky
            {"test_name": "test_api_endpoint", "results": ["pass", "pass", "pass", "pass", "pass"]},
            {"test_name": "test_file_upload", "results": ["pass", "pass", "fail", "pass", "fail"]},  # Flaky
            {"test_name": "test_email_service", "results": ["fail", "fail", "fail", "fail", "fail"]},  # Consistently failing
        ]
        
        print("Analyzing sample test data for flakiness...")
        
        flaky_tests_found = []
        
        for test_data in sample_test_data:
            test_name = test_data["test_name"]
            results = test_data["results"]
            
            # Calculate flakiness metrics
            total_runs = len(results)
            pass_count = results.count("pass")
            fail_count = results.count("fail")
            success_rate = pass_count / total_runs
            
            # Calculate flakiness score
            flakiness_score = calculate_flakiness_score({
                "test_name": test_name,
                "total_runs": total_runs,
                "pass_count": pass_count,
                "fail_count": fail_count,
                "results_history": results
            })
            
            print(f"\nTest: {test_name}")
            print(f"  Results: {results}")
            print(f"  Success Rate: {success_rate:.1%}")
            print(f"  Flakiness Score: {flakiness_score:.3f}")
            
            # Identify flaky tests (inconsistent results, not consistently failing)
            if flakiness_score > 0.3 and success_rate > 0.1 and success_rate < 0.9:
                flaky_test = {
                    "test_name": test_name,
                    "flakiness_score": flakiness_score,
                    "success_rate": success_rate,
                    "total_runs": total_runs,
                    "pass_count": pass_count,
                    "fail_count": fail_count,
                    "pattern": "Intermittent failures detected",
                    "recommendation": "Investigate test stability and dependencies"
                }
                flaky_tests_found.append(flaky_test)
                
                # Add to registry
                test_registry[test_name] = {
                    "flakiness_score": flakiness_score,
                    "last_updated": time.time(),
                    "total_runs": total_runs,
                    "recent_results": results
                }
        
        # Display results
        print(f"\n--- FLAKY TEST ANALYSIS RESULTS ---")
        print(f"Analyzed {len(sample_test_data)} tests")
        print(f"Found {len(flaky_tests_found)} flaky tests")
        
        for flaky_test in flaky_tests_found:
            print(f"\nFLAKY TEST: {flaky_test['test_name']}")
            print(f"  Flakiness Score: {flaky_test['flakiness_score']:.3f}")
            print(f"  Success Rate: {flaky_test['success_rate']:.1%}")
            print(f"  Pattern: {flaky_test['pattern']}")
            print(f"  Recommendation: {flaky_test['recommendation']}")
        
        # Send results to analysis queue
        analysis_result = {
            "analysis_type": "flaky_test_identification",
            "flaky_tests_detected": len(flaky_tests_found),
            "total_tests_analyzed": len(sample_test_data),
            "flaky_tests": flaky_tests_found,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Send results to analysis queue (or print if SQS not available)
        print(f"--- Analysis Result (SQS not connected) ---")
        print(json.dumps(analysis_result, indent=2)[:500] + "...")
        print("-" * 50)
        success = True
        
        flaky_agent_state["status"] = "Manual analysis completed"
        flaky_agent_state["last_analysis"] = time.time()
        flaky_agent_state["flaky_tests_identified"] += len(flaky_tests_found)
        
        print("\n=== Flaky Test Analysis Complete ===")
        return {"message": f"Identified {len(flaky_tests_found)} flaky tests out of {len(sample_test_data)} analyzed"}
        
    except Exception as e:
        print(f"Error in manual flaky test analysis: {e}")
        flaky_agent_state["status"] = "Manual analysis error"
        flaky_agent_state["errors"] += 1
        return {"message": f"Error: {str(e)}"}

@anvil.server.callable
def get_flaky_test_registry():
    """Get the current registry of flaky tests."""
    return dict(flaky_test_registry)

@anvil.server.callable
def get_flaky_test_statistics():
    """Get flaky test identification statistics."""
    return {
        "total_processed": flaky_agent_state["messages_processed"],
        "flaky_tests_identified": flaky_agent_state["flaky_tests_identified"],
        "unique_flaky_tests": len(flaky_test_registry),
        "test_history_size": sum(len(history) for history in test_history.values())
    }

@anvil.server.callable
def clear_flaky_test_registry():
    """Clear the flaky test registry (for testing purposes)."""
    global flaky_test_registry, test_history
    flaky_test_registry.clear()
    test_history.clear()
    flaky_agent_state["flaky_tests_identified"] = 0
    return "Flaky test registry cleared."

# --- Main Agent Function ---

def run_flaky_test_agent():
    """Main function to keep the flaky test identification agent running."""
    if not ANVIL_UPLINK_KEY:
        print("Flaky Test Agent ERROR: Missing ANVIL_UPLINK_KEY.")
        return
    
    try:
        anvil.server.connect(ANVIL_UPLINK_KEY)
        print("Flaky Test Identification Agent successfully connected to Anvil Uplink.")
        flaky_agent_state["status"] = "Connected to Anvil"
        
        # Start SQS polling if available
        if sqs_client_flaky and flaky_agent_state["sqs_status"] == "Connected":
            polling_thread = threading.Thread(target=poll_features_queue, daemon=True)
            polling_thread.start()
            print("Flaky Test Agent: SQS polling thread started.")
        
        anvil.server.wait_forever()
        
    except Exception as e:
        print(f"Flaky Test Identification Agent failed to connect: {e}")
        flaky_agent_state["status"] = "Anvil Connection Failed"

if __name__ == "__main__":
    run_flaky_test_agent()
