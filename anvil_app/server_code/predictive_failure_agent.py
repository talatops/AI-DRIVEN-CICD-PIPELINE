# --- Predictive Failure Agent ---
# This agent forecasts pipeline failures before they occur using ML models

import anvil.server
import os
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
import time
import boto3
from botocore.exceptions import ClientError
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score
import threading
from collections import deque
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
predictive_agent_state = {
    "agent_name": "Predictive Failure Agent",
    "status": "Idle",
    "last_processed": None,
    "errors": 0,
    "messages_processed": 0,
    "predictions_made": 0,
    "high_risk_predictions": 0,
    "sqs_status": "Not Configured",
    "model_status": "Not Trained",
    "model_accuracy": 0.0
}

print("Predictive Failure Agent is initializing...")

# --- SQS Client Initialization ---
sqs_client_predictive = None
if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
    try:
        sqs_client_predictive = boto3.client(
            'sqs',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )
        predictive_agent_state["sqs_status"] = "Connected"
        print(f"Predictive Agent: Successfully connected to SQS.")
    except Exception as e:
        predictive_agent_state["sqs_status"] = "Connection Failed"
        print(f"Predictive Agent ERROR: Failed to initialize SQS client: {e}")
else:
    print("Predictive Agent WARNING: AWS SQS not configured.")

# --- ML Models and Data Storage ---
random_forest_model = None
logistic_regression_model = None
scaler = StandardScaler()
training_data = deque(maxlen=2000)  # Store last 2000 feature sets for training

# Feature columns for prediction
PREDICTION_FEATURES = [
    'duration_seconds', 'job_count', 'files_changed', 'code_churn', 'change_ratio',
    'avg_job_duration', 'max_job_duration', 'failed_job_count', 'success_rate',
    'avg_duration_last_5', 'duration_std_last_5', 'duration_trend',
    'failure_rate_last_5', 'hour_of_day', 'day_of_week', 'is_weekend', 'is_business_hours'
]

def extract_prediction_features(feature_data):
    """Extract features for prediction model."""
    try:
        features = []
        for feature_name in PREDICTION_FEATURES:
            value = feature_data.get(feature_name, 0)
            if value is None:
                value = 0
            features.append(float(value))
        return np.array(features).reshape(1, -1)
    except Exception as e:
        print(f"Error extracting prediction features: {e}")
        return None

def determine_failure_label(feature_data):
    """Determine if this workflow run resulted in failure (for training)."""
    # Check various indicators of failure
    success_rate = feature_data.get("success_rate", 1.0)
    failed_job_count = feature_data.get("failed_job_count", 0)
    
    # Simple heuristic: failure if success rate < 1.0 or any jobs failed
    is_failure = (success_rate < 1.0) or (failed_job_count > 0)
    
    return 1 if is_failure else 0

def train_prediction_models():
    """Train prediction models with historical data."""
    global random_forest_model, logistic_regression_model, scaler
    
    if len(training_data) < 100:  # Need minimum data for training
        print("Predictive Agent: Insufficient data for model training.")
        return False
    
    try:
        # Prepare training data
        X_train = []
        y_train = []
        
        for data_point in training_data:
            features = extract_prediction_features(data_point)
            if features is not None:
                label = determine_failure_label(data_point)
                X_train.append(features.flatten())
                y_train.append(label)
        
        if len(X_train) < 50:
            print("Predictive Agent: Not enough valid feature vectors for training.")
            return False
        
        X_train = np.array(X_train)
        y_train = np.array(y_train)
        
        # Check if we have both classes
        unique_labels = np.unique(y_train)
        if len(unique_labels) < 2:
            print("Predictive Agent: Need both success and failure examples for training.")
            return False
        
        # Split data for validation
        X_train_split, X_val_split, y_train_split, y_val_split = train_test_split(
            X_train, y_train, test_size=0.2, random_state=42, stratify=y_train
        )
        
        # Scale features
        X_train_scaled = scaler.fit_transform(X_train_split)
        X_val_scaled = scaler.transform(X_val_split)
        
        # Train Random Forest
        random_forest_model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            random_state=42,
            class_weight='balanced'  # Handle class imbalance
        )
        random_forest_model.fit(X_train_scaled, y_train_split)
        
        # Train Logistic Regression
        logistic_regression_model = LogisticRegression(
            random_state=42,
            class_weight='balanced',
            max_iter=1000
        )
        logistic_regression_model.fit(X_train_scaled, y_train_split)
        
        # Evaluate models
        rf_predictions = random_forest_model.predict(X_val_scaled)
        lr_predictions = logistic_regression_model.predict(X_val_scaled)
        
        rf_accuracy = accuracy_score(y_val_split, rf_predictions)
        lr_accuracy = accuracy_score(y_val_split, lr_predictions)
        
        # Use the better performing model as primary
        if rf_accuracy >= lr_accuracy:
            primary_accuracy = rf_accuracy
            predictive_agent_state["model_status"] = f"Random Forest (Acc: {rf_accuracy:.2f})"
        else:
            primary_accuracy = lr_accuracy
            predictive_agent_state["model_status"] = f"Logistic Regression (Acc: {lr_accuracy:.2f})"
        
        predictive_agent_state["model_accuracy"] = primary_accuracy
        
        print(f"Predictive Agent: Models trained successfully.")
        print(f"Random Forest Accuracy: {rf_accuracy:.2f}")
        print(f"Logistic Regression Accuracy: {lr_accuracy:.2f}")
        
        return True
        
    except Exception as e:
        print(f"Predictive Agent: Error training models: {e}")
        predictive_agent_state["errors"] += 1
        return False

def predict_failure_probability(feature_data):
    """Predict the probability of failure for the given features."""
    global random_forest_model, logistic_regression_model, scaler
    
    if random_forest_model is None or logistic_regression_model is None:
        return None
    
    try:
        # Extract and scale features
        features = extract_prediction_features(feature_data)
        if features is None:
            return None
        
        features_scaled = scaler.transform(features)
        
        # Get predictions from both models
        rf_proba = random_forest_model.predict_proba(features_scaled)[0]
        lr_proba = logistic_regression_model.predict_proba(features_scaled)[0]
        
        # Combine probabilities (ensemble approach)
        rf_failure_prob = rf_proba[1] if len(rf_proba) > 1 else 0.0
        lr_failure_prob = lr_proba[1] if len(lr_proba) > 1 else 0.0
        
        combined_failure_prob = (rf_failure_prob + lr_failure_prob) / 2
        
        # Get feature importance from Random Forest
        feature_importance = random_forest_model.feature_importances_
        top_features_idx = np.argsort(feature_importance)[-3:]  # Top 3 features
        
        contributing_factors = []
        for idx in reversed(top_features_idx):
            feature_name = PREDICTION_FEATURES[idx]
            importance = feature_importance[idx]
            if importance > 0.05:  # Only include significant features
                contributing_factors.append(f"{feature_name} (importance: {importance:.2f})")
        
        return {
            "failure_probability": float(combined_failure_prob),
            "rf_probability": float(rf_failure_prob),
            "lr_probability": float(lr_failure_prob),
            "contributing_factors": contributing_factors[:3]  # Top 3 factors
        }
        
    except Exception as e:
        print(f"Predictive Agent: Error making prediction: {e}")
        predictive_agent_state["errors"] += 1
        return None

def send_prediction_result(prediction_result, original_data):
    """Send prediction result to analysis results queue."""
    if not prediction_result:
        return False
    
    failure_prob = prediction_result["failure_probability"]
    
    # Determine risk level
    if failure_prob >= 0.7:
        risk_level = "high"
        analysis_type = "predicted_failure"
    elif failure_prob >= 0.4:
        risk_level = "medium"
        analysis_type = "predicted_risk"
    else:
        risk_level = "low"
        analysis_type = "low_risk_prediction"
    
    message = {
        "analysis_type": analysis_type,
        "run_id": original_data.get("run_id"),
        "repo": original_data.get("repo", "unknown"),
        "predicted_probability_of_failure": failure_prob,
        "risk_level": risk_level,
        "contributing_factors": prediction_result["contributing_factors"],
        "model_details": {
            "rf_probability": prediction_result["rf_probability"],
            "lr_probability": prediction_result["lr_probability"],
            "model_accuracy": predictive_agent_state["model_accuracy"]
        },
        "timestamp": datetime.utcnow().isoformat(),
        "message": f"{risk_level.title()} risk of failure detected (probability: {failure_prob:.2f})",
        "agent": "predictive_failure_agent"
    }
    
    if sqs_client_predictive and predictive_agent_state["sqs_status"] == "Connected":
        try:
            response = sqs_client_predictive.get_queue_url(QueueName=ANALYSIS_RESULTS_QUEUE_NAME)
            queue_url = response['QueueUrl']
            sqs_client_predictive.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(message)
            )
            print(f"Prediction result sent to SQS for run {original_data.get('run_id', 'unknown')} (risk: {risk_level})")
            return True
        except Exception as e:
            print(f"ERROR: Failed to send prediction result to SQS: {e}")
            predictive_agent_state["errors"] += 1
            return False
    else:
        print(f"--- Failure Prediction Result (SQS not connected) ---")
        print(json.dumps(message, indent=2))
        print("------------------------------------------------------------------")
        return True

def process_feature_message(message_body):
    """Process a feature message from the features queue."""
    try:
        data = json.loads(message_body)
        feature_data = data.get("data", {})
        feature_type = data.get("feature_set_type", "")
        
        # Only process workflow run features for prediction
        if feature_type != "workflow_run_features":
            return False
        
        # Add to training data
        training_data.append(feature_data.copy())
        
        # Retrain models periodically
        if len(training_data) % 200 == 0 and len(training_data) >= 100:
            print("Predictive Agent: Retraining models with new data...")
            train_prediction_models()
        
        # Make prediction if models are trained
        if predictive_agent_state["model_status"] != "Not Trained":
            prediction_result = predict_failure_probability(feature_data)
            if prediction_result:
                success = send_prediction_result(prediction_result, feature_data)
                if success:
                    predictive_agent_state["predictions_made"] += 1
                    if prediction_result["failure_probability"] >= 0.7:
                        predictive_agent_state["high_risk_predictions"] += 1
                return success
        
        return True
        
    except Exception as e:
        print(f"Predictive Agent: Error processing feature message: {e}")
        predictive_agent_state["errors"] += 1
        return False

def poll_features_queue():
    """Continuously poll the features queue for new messages."""
    if not sqs_client_predictive:
        print("Predictive Agent: SQS client not available.")
        return
    
    try:
        response = sqs_client_predictive.get_queue_url(QueueName=FEATURES_QUEUE_NAME)
        queue_url = response['QueueUrl']
    except Exception as e:
        print("Predictive Agent: Cannot access features queue: {e}")
        return
    
    print("Predictive Agent: Starting to poll features queue...")
    predictive_agent_state["status"] = "Polling Features Queue"
    
    while True:
        try:
            response = sqs_client_predictive.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=5
            )
            
            messages = response.get('Messages', [])
            for message in messages:
                success = process_feature_message(message['Body'])
                
                if success:
                    predictive_agent_state["messages_processed"] += 1
                    predictive_agent_state["last_processed"] = time.time()
                    
                    # Delete message from queue
                    sqs_client_predictive.delete_message(
                        QueueUrl=queue_url,
                        ReceiptHandle=message['ReceiptHandle']
                    )
            
            time.sleep(1)
            
        except KeyboardInterrupt:
            print("Predictive Agent: Stopping queue polling...")
            break
        except Exception as e:
            print(f"Predictive Agent: Error during polling: {e}")
            predictive_agent_state["errors"] += 1
            time.sleep(5)

# --- Anvil Callable Functions ---

@anvil.server.callable
def get_predictive_status():
    """Returns the current status of the predictive failure agent."""
    return {
        "status": predictive_agent_state["status"],
        "predictions_made": predictive_agent_state["predictions_made"],
        "messages_processed": predictive_agent_state["messages_processed"],
        "errors": predictive_agent_state["errors"],
        "last_prediction": predictive_agent_state.get("last_prediction", "Never")
    }

@anvil.server.callable
def trigger_manual_prediction():
    """Manually trigger predictive analysis for testing."""
    print("\n=== Manual Predictive Failure Analysis Triggered ===")
    predictive_agent_state["status"] = "Manual Prediction..."
    
    try:
        # Create sample feature data for demonstration
        sample_features = [
            {
                "run_id": "run_001",
                "duration_seconds": 120,
                "success_rate": 0.95,
                "failed_job_count": 0,
                "files_changed_count": 3,
                "avg_duration_last_5": 115,
                "failure_rate_last_5": 0.0,
                "hour_of_day": 14,
                "day_of_week": 2
            },
            {
                "run_id": "run_002",
                "duration_seconds": 450,
                "success_rate": 0.60,
                "failed_job_count": 2,
                "files_changed_count": 25,
                "avg_duration_last_5": 200,
                "failure_rate_last_5": 0.4,
                "hour_of_day": 23,
                "day_of_week": 5
            },
            {
                "run_id": "run_003",
                "duration_seconds": 95,
                "success_rate": 1.0,
                "failed_job_count": 0,
                "files_changed_count": 1,
                "avg_duration_last_5": 100,
                "failure_rate_last_5": 0.0,
                "hour_of_day": 10,
                "day_of_week": 1
            }
        ]
        
        print("Analyzing sample feature data for failure prediction...")
        
        predictions_made = []
        
        for features in sample_features:
            run_id = features["run_id"]
            
            print(f"\nPredicting failure risk for {run_id}:")
            print(f"  Duration: {features['duration_seconds']}s")
            print(f"  Success Rate: {features['success_rate']:.1%}")
            print(f"  Failed Jobs: {features['failed_job_count']}")
            print(f"  Files Changed: {features['files_changed_count']}")
            
            # Perform failure prediction
            prediction_result = predict_failure_risk(features) if features else None
            
            if prediction_result:
                prediction_result["run_id"] = run_id
                predictions_made.append(prediction_result)
                
                risk_level = "HIGH" if prediction_result['failure_probability'] > 0.7 else "MEDIUM" if prediction_result['failure_probability'] > 0.3 else "LOW"
                
                print(f"  → Failure Probability: {prediction_result['failure_probability']:.1%}")
                print(f"  → Risk Level: {risk_level}")
                print(f"  → Key Risk Factors: {', '.join(prediction_result['risk_factors'])}")
                print(f"  → Recommendation: {prediction_result['recommendation']}")
        
        # Display comprehensive results
        print(f"\n--- PREDICTIVE FAILURE ANALYSIS RESULTS ---")
        print(f"Analyzed {len(sample_features)} pipeline runs")
        print(f"Generated {len(predictions_made)} failure predictions")
        
        # Categorize by risk level
        high_risk = [p for p in predictions_made if p['failure_probability'] > 0.7]
        medium_risk = [p for p in predictions_made if 0.3 < p['failure_probability'] <= 0.7]
        low_risk = [p for p in predictions_made if p['failure_probability'] <= 0.3]
        
        print(f"\nRisk Distribution:")
        print(f"  HIGH Risk: {len(high_risk)} runs")
        print(f"  MEDIUM Risk: {len(medium_risk)} runs")
        print(f"  LOW Risk: {len(low_risk)} runs")
        
        if high_risk:
            print(f"\nHIGH RISK RUNS (Immediate Attention Required):")
            for pred in high_risk:
                print(f"  - {pred['run_id']}: {pred['failure_probability']:.1%} failure risk")
                print(f"    Risk Factors: {', '.join(pred['risk_factors'])}")
        
        # Send results to analysis queue
        analysis_result = {
            "analysis_type": "predictive_failure_analysis",
            "predictions_made": len(predictions_made),
            "total_runs_analyzed": len(sample_features),
            "high_risk_count": len(high_risk),
            "medium_risk_count": len(medium_risk),
            "low_risk_count": len(low_risk),
            "predictions": predictions_made,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Send results to analysis queue (or print if SQS not available)
        print(f"--- Analysis Result (SQS not connected) ---")
        print(json.dumps(analysis_result, indent=2)[:500] + "...")
        print("-" * 50)
        success = True
        
        predictive_agent_state["status"] = "Manual prediction completed"
        predictive_agent_state["last_prediction"] = time.time()
        predictive_agent_state["predictions_made"] += len(predictions_made)
        
        print("\n=== Predictive Failure Analysis Complete ===")
        return {"message": f"Generated {len(predictions_made)} failure predictions ({len(high_risk)} high-risk)"}
        
    except Exception as e:
        print(f"Error in manual predictive analysis: {e}")
        predictive_agent_state["status"] = "Manual prediction error"
        predictive_agent_state["errors"] += 1
        return {"message": f"Error: {str(e)}"}

@anvil.server.callable
def get_prediction_statistics():
    """Get prediction statistics."""
    return {
        "total_processed": predictive_agent_state["messages_processed"],
        "predictions_made": predictive_agent_state["predictions_made"],
        "high_risk_predictions": predictive_agent_state["high_risk_predictions"],
        "high_risk_rate": predictive_agent_state["high_risk_predictions"] / max(predictive_agent_state["predictions_made"], 1),
        "training_data_size": len(training_data),
        "model_accuracy": predictive_agent_state["model_accuracy"],
        "model_status": predictive_agent_state["model_status"]
    }

@anvil.server.callable
def predict_sample_failure(sample_features):
    """Make a prediction on sample features for testing."""
    print("Manual failure prediction triggered.")
    
    if predictive_agent_state["model_status"] == "Not Trained":
        return {"error": "Models not trained yet"}
    
    result = predict_failure_probability(sample_features)
    return result if result else {"error": "Failed to make prediction"}

# --- Main Agent Function ---

def run_predictive_failure_agent():
    """Main function to keep the predictive failure agent running."""
    if not ANVIL_UPLINK_KEY:
        print("Predictive Agent ERROR: Missing ANVIL_UPLINK_KEY.")
        return
    
    try:
        anvil.server.connect(ANVIL_UPLINK_KEY)
        print("Predictive Failure Agent successfully connected to Anvil Uplink.")
        predictive_agent_state["status"] = "Connected to Anvil"
        
        # Start SQS polling if available
        if sqs_client_predictive and predictive_agent_state["sqs_status"] == "Connected":
            polling_thread = threading.Thread(target=poll_features_queue, daemon=True)
            polling_thread.start()
            print("Predictive Agent: SQS polling thread started.")
        
        anvil.server.wait_forever()
        
    except Exception as e:
        print(f"Predictive Failure Agent failed to connect: {e}")
        predictive_agent_state["status"] = "Anvil Connection Failed"

if __name__ == "__main__":
    run_predictive_failure_agent()
