# --- Anomaly Detection Agent (Pipeline Performance) ---
# This agent identifies unusual deviations in CI/CD pipeline performance metrics

import anvil.server
import os
import json
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv
import time
import boto3
from botocore.exceptions import ClientError
from sklearn.ensemble import IsolationForest
from sklearn.svm import OneClassSVM
from sklearn.preprocessing import StandardScaler
import threading
from collections import defaultdict, deque
import pickle

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
anomaly_agent_state = {
    "agent_name": "Anomaly Detection Agent",
    "status": "Idle",
    "last_processed": None,
    "errors": 0,
    "messages_processed": 0,
    "anomalies_detected": 0,
    "sqs_status": "Not Configured",
    "model_status": "Not Trained"
}

print("Anomaly Detection Agent is initializing...")

# --- SQS Client Initialization ---
sqs_client_anomaly = None
if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
    try:
        sqs_client_anomaly = boto3.client(
            'sqs',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )
        anomaly_agent_state["sqs_status"] = "Connected"
        print(f"Anomaly Agent: Successfully connected to SQS.")
    except Exception as e:
        anomaly_agent_state["sqs_status"] = "Connection Failed"
        print(f"Anomaly Agent ERROR: Failed to initialize SQS client: {e}")
else:
    print("Anomaly Agent WARNING: AWS SQS not configured.")

# --- ML Models and Data Storage ---
isolation_forest_model = None
oneclasssvm_model = None
scaler = StandardScaler()
historical_data = deque(maxlen=1000)  # Store last 1000 feature sets for training
feature_columns = [
    'duration_seconds', 'job_count', 'files_changed', 'code_churn',
    'avg_job_duration', 'failed_job_count', 'success_rate',
    'avg_duration_last_5', 'failure_rate_last_5', 'hour_of_day', 'day_of_week'
]

def extract_numeric_features(feature_data):
    """Extract numeric features for anomaly detection."""
    try:
        features = []
        for col in feature_columns:
            value = feature_data.get(col, 0)
            # Handle None values and convert to float
            if value is None:
                value = 0
            features.append(float(value))
        return np.array(features).reshape(1, -1)
    except Exception as e:
        print(f"Error extracting numeric features: {e}")
        return None

def train_anomaly_models():
    """Train anomaly detection models with historical data."""
    global isolation_forest_model, oneclasssvm_model, scaler
    
    if len(historical_data) < 50:  # Need minimum data for training
        print("Anomaly Agent: Insufficient data for model training.")
        return False
    
    try:
        # Prepare training data
        X_train = []
        for data_point in historical_data:
            features = extract_numeric_features(data_point)
            if features is not None:
                X_train.append(features.flatten())
        
        if len(X_train) < 20:
            print("Anomaly Agent: Not enough valid feature vectors for training.")
            return False
        
        X_train = np.array(X_train)
        
        # Scale features
        X_train_scaled = scaler.fit_transform(X_train)
        
        # Train Isolation Forest
        isolation_forest_model = IsolationForest(
            contamination=0.1,  # Expect 10% anomalies
            random_state=42,
            n_estimators=100
        )
        isolation_forest_model.fit(X_train_scaled)
        
        # Train One-Class SVM
        oneclasssvm_model = OneClassSVM(
            kernel='rbf',
            gamma='scale',
            nu=0.1  # Expected fraction of anomalies
        )
        oneclasssvm_model.fit(X_train_scaled)
        
        anomaly_agent_state["model_status"] = f"Trained on {len(X_train)} samples"
        print(f"Anomaly Agent: Models trained successfully on {len(X_train)} samples.")
        return True
        
    except Exception as e:
        print(f"Anomaly Agent: Error training models: {e}")
        anomaly_agent_state["errors"] += 1
        return False

def detect_anomalies(feature_data):
    """Detect anomalies in the given feature data."""
    global isolation_forest_model, oneclasssvm_model, scaler
    
    if isolation_forest_model is None or oneclasssvm_model is None:
        return None
    
    try:
        # Extract and scale features
        features = extract_numeric_features(feature_data)
        if features is None:
            return None
        
        features_scaled = scaler.transform(features)
        
        # Get predictions from both models
        iso_prediction = isolation_forest_model.predict(features_scaled)[0]
        iso_score = isolation_forest_model.decision_function(features_scaled)[0]
        
        svm_prediction = oneclasssvm_model.predict(features_scaled)[0]
        svm_score = oneclasssvm_model.decision_function(features_scaled)[0]
        
        # Combine predictions (anomaly if either model detects it)
        is_anomaly = (iso_prediction == -1) or (svm_prediction == -1)
        
        # Calculate combined anomaly score (normalized)
        combined_score = (abs(iso_score) + abs(svm_score)) / 2
        
        if is_anomaly:
            # Determine severity based on score
            if combined_score > 1.0:
                severity = "high"
            elif combined_score > 0.5:
                severity = "medium"
            else:
                severity = "low"
            
            # Identify which metric is most anomalous
            feature_values = extract_numeric_features(feature_data).flatten()
            feature_scores = np.abs(features_scaled.flatten())
            most_anomalous_idx = np.argmax(feature_scores)
            anomalous_metric = feature_columns[most_anomalous_idx]
            anomalous_value = feature_values[most_anomalous_idx]
            
            return {
                "is_anomaly": True,
                "anomaly_score": float(combined_score),
                "severity": severity,
                "anomalous_metric": anomalous_metric,
                "anomalous_value": float(anomalous_value),
                "iso_score": float(iso_score),
                "svm_score": float(svm_score)
            }
        
        return {
            "is_anomaly": False,
            "anomaly_score": float(combined_score)
        }
        
    except Exception as e:
        print(f"Anomaly Agent: Error detecting anomalies: {e}")
        anomaly_agent_state["errors"] += 1
        return None

def send_anomaly_result(anomaly_result, original_data):
    """Send anomaly detection result to analysis results queue."""
    if not anomaly_result:
        return False
    
    message = {
        "analysis_type": "anomaly_detected" if anomaly_result["is_anomaly"] else "normal_behavior",
        "run_id": original_data.get("run_id"),
        "job_id": original_data.get("job_id"),
        "repo": original_data.get("repo", "unknown"),
        "anomaly_score": anomaly_result["anomaly_score"],
        "timestamp": datetime.utcnow().isoformat(),
        "agent": "anomaly_detection_agent"
    }
    
    if anomaly_result["is_anomaly"]:
        message.update({
            "severity": anomaly_result["severity"],
            "metric": anomaly_result["anomalous_metric"],
            "actual_value": anomaly_result["anomalous_value"],
            "message": f"Anomaly detected in {anomaly_result['anomalous_metric']}: {anomaly_result['anomalous_value']:.2f}"
        })
    
    if sqs_client_anomaly and anomaly_agent_state["sqs_status"] == "Connected":
        try:
            response = sqs_client_anomaly.get_queue_url(QueueName=ANALYSIS_RESULTS_QUEUE_NAME)
            queue_url = response['QueueUrl']
            sqs_client_anomaly.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(message)
            )
            print(f"Anomaly result sent to SQS for run {original_data.get('run_id', 'unknown')}")
            return True
        except Exception as e:
            print(f"ERROR: Failed to send anomaly result to SQS: {e}")
            anomaly_agent_state["errors"] += 1
            return False
    else:
        print(f"--- Anomaly Detection Result (SQS not connected) ---")
        print(json.dumps(message, indent=2))
        print("------------------------------------------------------------------")
        return True

def process_feature_message(message_body):
    """Process a feature message from the features queue."""
    try:
        data = json.loads(message_body)
        feature_data = data.get("data", {})
        feature_type = data.get("feature_set_type", "")
        
        # Only process workflow run features for anomaly detection
        if feature_type != "workflow_run_features":
            return False
        
        # Add to historical data for model training
        historical_data.append(feature_data.copy())
        
        # Retrain models periodically
        if len(historical_data) % 100 == 0 and len(historical_data) >= 50:
            print("Anomaly Agent: Retraining models with new data...")
            train_anomaly_models()
        
        # Detect anomalies if models are trained
        if anomaly_agent_state["model_status"] != "Not Trained":
            anomaly_result = detect_anomalies(feature_data)
            if anomaly_result:
                success = send_anomaly_result(anomaly_result, feature_data)
                if success and anomaly_result["is_anomaly"]:
                    anomaly_agent_state["anomalies_detected"] += 1
                return success
        
        return True
        
    except Exception as e:
        print(f"Anomaly Agent: Error processing feature message: {e}")
        anomaly_agent_state["errors"] += 1
        return False

def poll_features_queue():
    """Continuously poll the features queue for new messages."""
    if not sqs_client_anomaly:
        print("Anomaly Agent: SQS client not available.")
        return
    
    try:
        response = sqs_client_anomaly.get_queue_url(QueueName=FEATURES_QUEUE_NAME)
        queue_url = response['QueueUrl']
    except Exception as e:
        print(f"Anomaly Agent: Cannot access features queue: {e}")
        return
    
    print("Anomaly Agent: Starting to poll features queue...")
    anomaly_agent_state["status"] = "Polling Features Queue"
    
    while True:
        try:
            response = sqs_client_anomaly.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=5
            )
            
            messages = response.get('Messages', [])
            for message in messages:
                success = process_feature_message(message['Body'])
                
                if success:
                    anomaly_agent_state["messages_processed"] += 1
                    anomaly_agent_state["last_processed"] = time.time()
                    
                    # Delete message from queue
                    sqs_client_anomaly.delete_message(
                        QueueUrl=queue_url,
                        ReceiptHandle=message['ReceiptHandle']
                    )
            
            time.sleep(1)
            
        except KeyboardInterrupt:
            print("Anomaly Agent: Stopping queue polling...")
            break
        except Exception as e:
            print(f"Anomaly Agent: Error during polling: {e}")
            anomaly_agent_state["errors"] += 1
            time.sleep(5)

# --- Anvil Callable Functions ---

@anvil.server.callable
def get_anomaly_detection_status():
    """Returns the current status of the anomaly detection agent."""
    return {
        "status": anomaly_agent_state["status"],
        "anomalies_detected": anomaly_agent_state["anomalies_detected"],
        "messages_processed": anomaly_agent_state["messages_processed"],
        "errors": anomaly_agent_state["errors"],
        "last_analysis": anomaly_agent_state.get("last_analysis", "Never")
    }

@anvil.server.callable
def trigger_manual_anomaly_detection():
    """Manually trigger anomaly detection for testing."""
    print("\n=== Manual Anomaly Detection Triggered ===")
    anomaly_agent_state["status"] = "Manual Analysis..."
    
    try:
        # Create sample feature data for demonstration
        sample_features = [
            {"duration_seconds": 120, "success_rate": 1.0, "failed_job_count": 0, "files_changed_count": 2},
            {"duration_seconds": 135, "success_rate": 1.0, "failed_job_count": 0, "files_changed_count": 3},
            {"duration_seconds": 890, "success_rate": 0.5, "failed_job_count": 2, "files_changed_count": 15},  # Anomaly
            {"duration_seconds": 110, "success_rate": 1.0, "failed_job_count": 0, "files_changed_count": 1},
            {"duration_seconds": 125, "success_rate": 1.0, "failed_job_count": 0, "files_changed_count": 4}
        ]
        
        print("Analyzing sample feature data for anomalies...")
        
        # Simple anomaly detection logic
        anomalies_found = []
        
        # Calculate basic statistics
        durations = [f["duration_seconds"] for f in sample_features]
        success_rates = [f["success_rate"] for f in sample_features]
        
        avg_duration = sum(durations) / len(durations)
        duration_threshold = avg_duration * 2  # Simple threshold
        
        print(f"Average duration: {avg_duration:.1f}s, Anomaly threshold: {duration_threshold:.1f}s")
        
        for i, features in enumerate(sample_features):
            anomaly_score = 0
            reasons = []
            
            # Check duration anomaly
            if features["duration_seconds"] > duration_threshold:
                anomaly_score += 0.7
                reasons.append(f"Excessive duration: {features['duration_seconds']}s")
            
            # Check success rate anomaly
            if features["success_rate"] < 0.8:
                anomaly_score += 0.5
                reasons.append(f"Low success rate: {features['success_rate']:.1%}")
            
            # Check failed jobs
            if features["failed_job_count"] > 0:
                anomaly_score += 0.3
                reasons.append(f"Failed jobs: {features['failed_job_count']}")
            
            if anomaly_score > 0.5:  # Anomaly threshold
                anomaly = {
                    "sample_id": i + 1,
                    "anomaly_score": anomaly_score,
                    "reasons": reasons,
                    "features": features
                }
                anomalies_found.append(anomaly)
        
        # Display results
        print(f"\n--- ANOMALY DETECTION RESULTS ---")
        print(f"Analyzed {len(sample_features)} feature samples")
        print(f"Found {len(anomalies_found)} anomalies")
        
        for anomaly in anomalies_found:
            print(f"\nANOMALY #{anomaly['sample_id']}:")
            print(f"  Score: {anomaly['anomaly_score']:.2f}")
            print(f"  Reasons: {', '.join(anomaly['reasons'])}")
            print(f"  Duration: {anomaly['features']['duration_seconds']}s")
            print(f"  Success Rate: {anomaly['features']['success_rate']:.1%}")
        
        # Send results to analysis queue
        analysis_result = {
            "analysis_type": "anomaly_detection",
            "anomalies_detected": len(anomalies_found),
            "total_samples": len(sample_features),
            "anomalies": anomalies_found,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Send results to analysis queue (or print if SQS not available)
        if sqs_client_analysis and anomaly_agent_state["sqs_status"] == "Connected":
            try:
                response = sqs_client_analysis.get_queue_url(QueueName=ANALYSIS_RESULTS_QUEUE_NAME)
                queue_url = response['QueueUrl']
                sqs_client_analysis.send_message(
                    QueueUrl=queue_url,
                    MessageBody=json.dumps(analysis_result)
                )
                print("Successfully sent analysis results to SQS.")
                success = True
            except Exception as e:
                print(f"ERROR: Failed to send analysis results to SQS: {e}")
                success = False
        else:
            print(f"--- Analysis Result (SQS not connected) ---")
            print(json.dumps(analysis_result, indent=2)[:500] + "...")
            print("-" * 50)
            success = True
        
        anomaly_agent_state["status"] = "Manual analysis completed"
        anomaly_agent_state["last_analysis"] = time.time()
        anomaly_agent_state["anomalies_detected"] += len(anomalies_found)
        
        print("\n=== Anomaly Detection Complete ===")
        return {"message": f"Detected {len(anomalies_found)} anomalies in {len(sample_features)} samples"}
        
    except Exception as e:
        print(f"Error in manual anomaly detection: {e}")
        anomaly_agent_state["status"] = "Manual analysis error"
        anomaly_agent_state["errors"] += 1
        return {"message": f"Error: {str(e)}"}

@anvil.server.callable
def get_anomaly_statistics():
    """Get anomaly detection statistics."""
    return {
        "total_processed": anomaly_agent_state["messages_processed"],
        "anomalies_detected": anomaly_agent_state["anomalies_detected"],
        "detection_rate": anomaly_agent_state["anomalies_detected"] / max(anomaly_agent_state["messages_processed"], 1),
        "historical_data_size": len(historical_data),
        "model_status": anomaly_agent_state["model_status"]
    }

# --- Main Agent Function ---

def run_anomaly_detection_agent():
    """Main function to keep the anomaly detection agent running."""
    if not ANVIL_UPLINK_KEY:
        print("Anomaly Agent ERROR: Missing ANVIL_UPLINK_KEY.")
        return
    
    try:
        anvil.server.connect(ANVIL_UPLINK_KEY)
        print("Anomaly Detection Agent successfully connected to Anvil Uplink.")
        anomaly_agent_state["status"] = "Connected to Anvil"
        
        # Start SQS polling if available
        if sqs_client_anomaly and anomaly_agent_state["sqs_status"] == "Connected":
            polling_thread = threading.Thread(target=poll_features_queue, daemon=True)
            polling_thread.start()
            print("Anomaly Agent: SQS polling thread started.")
        
        anvil.server.wait_forever()
        
    except Exception as e:
        print(f"Anomaly Detection Agent failed to connect: {e}")
        anomaly_agent_state["status"] = "Anvil Connection Failed"

if __name__ == "__main__":
    run_anomaly_detection_agent()
