# --- Feature Engineering & Data Preprocessing Agent ---
# This agent transforms raw data from Layer-1 into clean, structured features for ML models

import anvil.server
import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv
import time
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError
from sklearn.preprocessing import StandardScaler, LabelEncoder
import re
import threading
from collections import defaultdict, deque

# --- Load Environment Variables ---
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=dotenv_path)

# --- Configuration & State ---
# AWS SQS Config
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
METRICS_QUEUE_NAME = os.getenv("METRICS_QUEUE_NAME")
LOGS_QUEUE_NAME = os.getenv("LOGS_QUEUE_NAME")
FEATURES_QUEUE_NAME = os.getenv("FEATURES_QUEUE_NAME", "ci_cd_features_queue")

# Anvil Config
ANVIL_UPLINK_KEY = os.getenv("ANVIL_UPLINK_KEY")

# Agent's internal state
feature_agent_state = {
    "agent_name": "Feature Engineering Agent",
    "status": "Idle",
    "last_processed": None,
    "errors": 0,
    "messages_processed": 0,
    "features_generated": 0,
    "sqs_status": "Not Configured"
}

print("Feature Engineering Agent is initializing...")

# --- SQS Client Initialization ---
sqs_client_features = None
if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
    try:
        sqs_client_features = boto3.client(
            'sqs',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )
        # Test connection by checking if queues exist
        if FEATURES_QUEUE_NAME:
            try:
                sqs_client_features.get_queue_url(QueueName=FEATURES_QUEUE_NAME)
                feature_agent_state["sqs_status"] = "Connected"
                print(f"Feature Agent: Successfully connected to SQS queue: {FEATURES_QUEUE_NAME}")
            except ClientError as e:
                if e.response['Error']['Code'] == 'AWS.SimpleQueueService.NonExistentQueue':
                    feature_agent_state["sqs_status"] = "Queue Not Found"
                    print(f"Feature Agent WARNING: SQS Queue '{FEATURES_QUEUE_NAME}' does not exist.")
                else:
                    feature_agent_state["sqs_status"] = f"Connection Error: {e.response['Error']['Code']}"
                    print(f"Feature Agent ERROR: Failed to connect to SQS: {e}")
    except Exception as e:
        feature_agent_state["sqs_status"] = "Connection Failed"
        print(f"Feature Agent ERROR: Failed to initialize SQS client: {e}")
else:
    print("Feature Agent WARNING: AWS SQS not configured. Features will be printed to console.")

# --- Data Storage for Feature Engineering ---
# In-memory storage for historical data (for time-series features)
workflow_history = defaultdict(lambda: deque(maxlen=50))  # Last 50 runs per workflow
job_history = defaultdict(lambda: deque(maxlen=100))      # Last 100 jobs per job type
repo_metrics = defaultdict(dict)                          # Repository-level aggregated metrics

# --- Feature Engineering Functions ---

def extract_temporal_features(timestamp_str):
    """Extract temporal features from timestamp."""
    try:
        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        return {
            "hour_of_day": dt.hour,
            "day_of_week": dt.weekday(),  # 0=Monday, 6=Sunday
            "week_of_year": dt.isocalendar()[1],
            "month": dt.month,
            "is_weekend": 1 if dt.weekday() >= 5 else 0,
            "is_business_hours": 1 if 9 <= dt.hour <= 17 else 0
        }
    except Exception as e:
        print(f"Error extracting temporal features: {e}")
        return {
            "hour_of_day": 0, "day_of_week": 0, "week_of_year": 1,
            "month": 1, "is_weekend": 0, "is_business_hours": 0
        }

def calculate_rolling_metrics(history_deque, metric_key, window_size=5):
    """Calculate rolling averages and statistics."""
    if len(history_deque) < 2:
        return {"avg": 0, "std": 0, "trend": 0}
    
    values = [item.get(metric_key, 0) for item in list(history_deque)[-window_size:]]
    values = [v for v in values if v is not None and v > 0]
    
    if not values:
        return {"avg": 0, "std": 0, "trend": 0}
    
    avg = np.mean(values)
    std = np.std(values) if len(values) > 1 else 0
    
    # Simple trend calculation (positive = increasing, negative = decreasing)
    trend = 0
    if len(values) >= 3:
        recent_avg = np.mean(values[-2:])
        older_avg = np.mean(values[:-2])
        trend = (recent_avg - older_avg) / older_avg if older_avg > 0 else 0
    
    return {"avg": float(avg), "std": float(std), "trend": float(trend)}

def encode_categorical_features(data):
    """Encode categorical data into numerical format."""
    encoded = {}
    
    # Event type encoding
    event_types = ["push", "pull_request", "workflow_dispatch", "schedule", "release"]
    for event_type in event_types:
        encoded[f"event_{event_type}"] = 1 if data.get("event") == event_type else 0
    
    # Conclusion encoding
    conclusions = ["success", "failure", "cancelled", "skipped", "timed_out"]
    for conclusion in conclusions:
        encoded[f"conclusion_{conclusion}"] = 1 if data.get("conclusion") == conclusion else 0
    
    return encoded

def parse_log_features(log_content):
    """Extract basic features from log content."""
    if not log_content or log_content == "":
        return {
            "log_length": 0,
            "error_count": 0,
            "warning_count": 0,
            "has_timeout": 0,
            "has_memory_error": 0,
            "has_network_error": 0
        }
    
    log_lower = log_content.lower()
    
    # Count different log levels
    error_patterns = [r'\berror\b', r'\bfailed\b', r'\bfailure\b', r'\bexception\b']
    warning_patterns = [r'\bwarning\b', r'\bwarn\b']
    
    error_count = sum(len(re.findall(pattern, log_lower)) for pattern in error_patterns)
    warning_count = sum(len(re.findall(pattern, log_lower)) for pattern in warning_patterns)
    
    # Specific error type detection
    has_timeout = 1 if re.search(r'\btimeout\b|\btimed.out\b', log_lower) else 0
    has_memory_error = 1 if re.search(r'out.of.memory|memory.error|oom', log_lower) else 0
    has_network_error = 1 if re.search(r'network.error|connection.failed|dns.resolution', log_lower) else 0
    
    return {
        "log_length": len(log_content),
        "error_count": error_count,
        "warning_count": warning_count,
        "has_timeout": has_timeout,
        "has_memory_error": has_memory_error,
        "has_network_error": has_network_error
    }

def process_workflow_metrics(data):
    """Process workflow run data into features."""
    try:
        run_id = data.get("run_id")
        workflow_id = data.get("workflow_id")
        repo = data.get("repo", "unknown")
        
        # Basic metrics
        features = {
            "run_id": run_id,
            "workflow_id": workflow_id,
            "repo": repo,
            "duration_seconds": data.get("duration_seconds", 0),
            "job_count": len(data.get("jobs", [])),
            "files_changed": data.get("code_metrics", {}).get("files_changed_count", 0),
            "additions": data.get("code_metrics", {}).get("additions", 0),
            "deletions": data.get("code_metrics", {}).get("deletions", 0)
        }
        
        # Calculate code churn
        total_changes = features["additions"] + features["deletions"]
        features["code_churn"] = total_changes
        features["change_ratio"] = features["additions"] / max(total_changes, 1)
        
        # Temporal features
        timestamp = data.get("timestamp", datetime.utcnow().isoformat())
        features.update(extract_temporal_features(timestamp))
        
        # Categorical encoding
        features.update(encode_categorical_features(data))
        
        # Job-level aggregations
        jobs = data.get("jobs", [])
        if jobs:
            job_durations = [job.get("duration_seconds", 0) for job in jobs]
            job_conclusions = [job.get("conclusion") for job in jobs]
            
            features["avg_job_duration"] = np.mean(job_durations)
            features["max_job_duration"] = max(job_durations)
            features["failed_job_count"] = job_conclusions.count("failure")
            features["success_rate"] = job_conclusions.count("success") / len(jobs)
        else:
            features.update({
                "avg_job_duration": 0, "max_job_duration": 0,
                "failed_job_count": 0, "success_rate": 0
            })
        
        # Historical features (rolling metrics)
        workflow_key = f"{repo}:{workflow_id}"
        history = workflow_history[workflow_key]
        
        duration_metrics = calculate_rolling_metrics(history, "duration_seconds")
        features.update({
            "avg_duration_last_5": duration_metrics["avg"],
            "duration_std_last_5": duration_metrics["std"],
            "duration_trend": duration_metrics["trend"]
        })
        
        # Failure rate calculation
        if len(history) >= 5:
            recent_conclusions = [item.get("conclusion") for item in list(history)[-5:]]
            failure_rate = recent_conclusions.count("failure") / len(recent_conclusions)
            features["failure_rate_last_5"] = failure_rate
        else:
            features["failure_rate_last_5"] = 0
        
        # Update history
        history.append({
            "duration_seconds": features["duration_seconds"],
            "conclusion": data.get("conclusion"),
            "timestamp": timestamp
        })
        
        return features
        
    except Exception as e:
        print(f"Error processing workflow metrics: {e}")
        feature_agent_state["errors"] += 1
        return None

def process_log_data(data):
    """Process log data into features."""
    try:
        run_id = data.get("run_id")
        job_id = data.get("job_id")
        repo = data.get("repo", "unknown")
        log_content = data.get("raw_log_content", "")
        
        # Basic log features
        features = {
            "run_id": run_id,
            "job_id": job_id,
            "repo": repo,
            "feature_set_type": "log_features"
        }
        
        # Extract log-based features
        log_features = parse_log_features(log_content)
        features.update(log_features)
        
        return features
        
    except Exception as e:
        print(f"Error processing log data: {e}")
        feature_agent_state["errors"] += 1
        return None

def send_features_to_queue(features):
    """Send processed features to the features queue."""
    if not features:
        return False
    
    message = {
        "feature_set_type": features.get("feature_set_type", "workflow_run_features"),
        "data": features,
        "timestamp": datetime.utcnow().isoformat(),
        "agent": "feature_engineering_agent"
    }
    
    if sqs_client_features and feature_agent_state["sqs_status"] == "Connected":
        try:
            response = sqs_client_features.get_queue_url(QueueName=FEATURES_QUEUE_NAME)
            queue_url = response['QueueUrl']
            sqs_client_features.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(message)
            )
            print(f"Successfully sent features for {features.get('run_id', 'unknown')} to SQS.")
            return True
        except Exception as e:
            print(f"ERROR: Failed to send features to SQS: {e}")
            feature_agent_state["errors"] += 1
            return False
    else:
        print(f"--- Generated Features (SQS not connected) ---")
        print(json.dumps(message, indent=2)[:500] + "...")
        print("------------------------------------------------------------------")
        return True

# --- SQS Message Processing ---

def process_sqs_message(queue_name, message_body):
    """Process a single SQS message."""
    try:
        data = json.loads(message_body)
        event_type = data.get("event_type", "")
        
        features = None
        
        if event_type == "workflow_run_processed":
            # Process workflow metrics
            workflow_data = data.get("data", {})
            features = process_workflow_metrics(workflow_data)
            if features:
                features["feature_set_type"] = "workflow_run_features"
                
        elif event_type == "job_log_processed":
            # Process log data
            log_data = data.get("data", {})
            features = process_log_data(log_data)
            if features:
                features["feature_set_type"] = "log_features"
        
        if features:
            success = send_features_to_queue(features)
            if success:
                feature_agent_state["features_generated"] += 1
            return success
        
        return False
        
    except Exception as e:
        print(f"Error processing SQS message: {e}")
        feature_agent_state["errors"] += 1
        return False

def poll_sqs_queues():
    """Continuously poll SQS queues for new messages."""
    if not sqs_client_features:
        print("Feature Agent: SQS client not available, cannot poll queues.")
        return
    
    queues_to_poll = []
    
    # Add metrics queue if available
    if METRICS_QUEUE_NAME:
        try:
            response = sqs_client_features.get_queue_url(QueueName=METRICS_QUEUE_NAME)
            queues_to_poll.append((METRICS_QUEUE_NAME, response['QueueUrl']))
        except Exception as e:
            print(f"Feature Agent: Cannot access metrics queue: {e}")
    
    # Add logs queue if available
    if LOGS_QUEUE_NAME:
        try:
            response = sqs_client_features.get_queue_url(QueueName=LOGS_QUEUE_NAME)
            queues_to_poll.append((LOGS_QUEUE_NAME, response['QueueUrl']))
        except Exception as e:
            print(f"Feature Agent: Cannot access logs queue: {e}")
    
    if not queues_to_poll:
        print("Feature Agent: No input queues available for polling.")
        return
    
    print(f"Feature Agent: Starting to poll {len(queues_to_poll)} queues...")
    feature_agent_state["status"] = "Polling SQS Queues"
    
    while True:
        try:
            for queue_name, queue_url in queues_to_poll:
                # Poll for messages
                response = sqs_client_features.receive_message(
                    QueueUrl=queue_url,
                    MaxNumberOfMessages=10,
                    WaitTimeSeconds=5  # Long polling
                )
                
                messages = response.get('Messages', [])
                for message in messages:
                    # Process message
                    success = process_sqs_message(queue_name, message['Body'])
                    
                    if success:
                        feature_agent_state["messages_processed"] += 1
                        feature_agent_state["last_processed"] = time.time()
                        
                        # Delete message from queue
                        sqs_client_features.delete_message(
                            QueueUrl=queue_url,
                            ReceiptHandle=message['ReceiptHandle']
                        )
            
            time.sleep(1)  # Brief pause between polling cycles
            
        except KeyboardInterrupt:
            print("Feature Agent: Stopping SQS polling...")
            break
        except Exception as e:
            print(f"Feature Agent: Error during SQS polling: {e}")
            feature_agent_state["errors"] += 1
            time.sleep(5)  # Wait before retrying

# --- Anvil Callable Functions ---

@anvil.server.callable
def get_feature_agent_status():
    """Returns the current status of the feature engineering agent."""
    return feature_agent_state

@anvil.server.callable
def get_feature_engineering_status():
    """Returns the current status of the feature engineering agent."""
    return {
        "status": feature_agent_state["status"],
        "features_generated": feature_agent_state["features_generated"],
        "messages_processed": feature_agent_state["messages_processed"],
        "errors": feature_agent_state["errors"],
        "last_processed": feature_agent_state.get("last_processed", "Never")
    }

@anvil.server.callable
def trigger_manual_feature_engineering():
    """Manually trigger feature engineering for testing."""
    print("\n=== Manual Feature Engineering Triggered ===")
    feature_agent_state["status"] = "Manual Processing..."
    
    try:
        # Create sample workflow data for demonstration
        sample_workflow_data = {
            "run_id": 999999,
            "workflow_id": 12345,
            "workflow_name": "Sample CI/CD Pipeline",
            "status": "completed",
            "conclusion": "success",
            "duration_seconds": 180,
            "repo": "sample/repo",
            "head_branch": "main",
            "event": "push",
            "code_metrics": {
                "files_changed_count": 3,
                "additions": 25,
                "deletions": 10
            },
            "jobs": [
                {
                    "job_id": 123,
                    "job_name": "build",
                    "conclusion": "success",
                    "duration_seconds": 120
                },
                {
                    "job_id": 124,
                    "job_name": "test",
                    "conclusion": "success",
                    "duration_seconds": 60
                }
            ]
        }
        
        # Process the sample data through feature engineering
        print("Processing sample workflow data through feature engineering...")
        features = process_workflow_metrics(sample_workflow_data)
        
        if features:
            print("\n--- GENERATED FEATURES ---")
            for key, value in features.items():
                if isinstance(value, float):
                    print(f"{key}: {value:.3f}")
                else:
                    print(f"{key}: {value}")
            
            # Send to features queue
            features["feature_set_type"] = "manual_workflow_features"
            success = send_features_to_queue(features)
            
            feature_agent_state["status"] = "Manual processing completed"
            feature_agent_state["last_processed"] = time.time()
            feature_agent_state["features_generated"] += 1
            
            print("\n=== Feature Engineering Complete ===")
            return {"message": f"Generated {len(features)} features from sample workflow data"}
        else:
            feature_agent_state["status"] = "Manual processing failed"
            return {"message": "Failed to generate features from sample data"}
            
    except Exception as e:
        print(f"Error in manual feature engineering: {e}")
        feature_agent_state["status"] = "Manual processing error"
        feature_agent_state["errors"] += 1
        return {"message": f"Error: {str(e)}"}

# --- Main Agent Function ---

def run_feature_engineering_agent():
    """Main function to keep the feature engineering agent running."""
    if not ANVIL_UPLINK_KEY:
        print("Feature Agent ERROR: Missing ANVIL_UPLINK_KEY. Agent will not run.")
        return
    
    try:
        anvil.server.connect(ANVIL_UPLINK_KEY)
        print("Feature Engineering Agent successfully connected to Anvil Uplink.")
        feature_agent_state["status"] = "Connected to Anvil"
        
        # Start SQS polling in a separate thread if SQS is configured
        if sqs_client_features and feature_agent_state["sqs_status"] == "Connected":
            polling_thread = threading.Thread(target=poll_sqs_queues, daemon=True)
            polling_thread.start()
            print("Feature Agent: SQS polling thread started.")
        
        anvil.server.wait_forever()
        
    except Exception as e:
        print(f"Feature Engineering Agent failed to connect or stay connected to Anvil: {e}")
        feature_agent_state["status"] = "Anvil Connection Failed"

# This check allows the script to be run directly for testing if needed.
if __name__ == "__main__":
    run_feature_engineering_agent()
