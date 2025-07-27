import threading
import time
import os
from dotenv import load_dotenv

# Load environment variables from .env file at the very beginning
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=dotenv_path)

# Now import the agent modules
# Layer-1 Agents (Data Collection & Ingestion)
from anvil_app.server_code import pipeline_monitor, log_ingester
# Layer-2 Agents (Intelligence & Analysis)
from anvil_app.server_code import feature_engineering_agent, anomaly_detection_agent, flaky_test_agent, log_analysis_agent, predictive_failure_agent

def main():
    """Main function to start and manage all backend agents."""
    print("--- Starting AI-Driven CI/CD Multi-Layer System ---")
    print("Layer-1: Data Collection & Ingestion")
    print("Layer-2: Intelligence & Analysis")

    # --- Layer-1 Agents (Data Collection & Ingestion) ---
    
    # 1. Pipeline Monitoring Agent Thread
    print("\nCreating Pipeline Monitoring Agent thread...")
    pipeline_thread = threading.Thread(target=pipeline_monitor.run_pipeline_monitor, daemon=True)
    pipeline_thread.start()
    print("Pipeline Monitoring Agent thread started.")

    # 2. Log Ingestion Agent Thread
    time.sleep(2)
    print("\nCreating Log Ingestion Agent thread...")
    log_ingester_thread = threading.Thread(target=log_ingester.run_log_ingester, daemon=True)
    log_ingester_thread.start()
    print("Log Ingestion Agent thread started.")

    # --- Layer-2 Agents (Intelligence & Analysis) ---
    
    # 3. Feature Engineering Agent Thread
    time.sleep(2)
    print("\nCreating Feature Engineering Agent thread...")
    feature_thread = threading.Thread(target=feature_engineering_agent.run_feature_engineering_agent, daemon=True)
    feature_thread.start()
    print("Feature Engineering Agent thread started.")

    # 4. Anomaly Detection Agent Thread
    time.sleep(2)
    print("\nCreating Anomaly Detection Agent thread...")
    anomaly_thread = threading.Thread(target=anomaly_detection_agent.run_anomaly_detection_agent, daemon=True)
    anomaly_thread.start()
    print("Anomaly Detection Agent thread started.")

    # 5. Flaky Test Identification Agent Thread
    time.sleep(2)
    print("\nCreating Flaky Test Identification Agent thread...")
    flaky_test_thread = threading.Thread(target=flaky_test_agent.run_flaky_test_agent, daemon=True)
    flaky_test_thread.start()
    print("Flaky Test Identification Agent thread started.")

    # 6. Log Analysis & RCA Agent Thread
    time.sleep(2)
    print("\nCreating Log Analysis & RCA Agent thread...")
    rca_thread = threading.Thread(target=log_analysis_agent.run_log_analysis_agent, daemon=True)
    rca_thread.start()
    print("Log Analysis & RCA Agent thread started.")

    # 7. Predictive Failure Agent Thread
    time.sleep(2)
    print("\nCreating Predictive Failure Agent thread...")
    predictive_thread = threading.Thread(target=predictive_failure_agent.run_predictive_failure_agent, daemon=True)
    predictive_thread.start()
    print("Predictive Failure Agent thread started.")

    print("\n=== All Multi-Layer Agents Running ===")
    print("Layer-1: Pipeline Monitor + Log Ingester")
    print("Layer-2: Feature Engineering + Anomaly Detection + Flaky Test + RCA + Predictive")
    print("The script will keep running to maintain connections.")
    print("Press Ctrl+C to stop all agents.")

    # Store all threads for monitoring
    all_threads = [pipeline_thread, log_ingester_thread, feature_thread, anomaly_thread, flaky_test_thread, rca_thread, predictive_thread]
    thread_names = ["Pipeline Monitor", "Log Ingester", "Feature Engineering", "Anomaly Detection", "Flaky Test", "RCA", "Predictive"]

    try:
        # Keep the main thread alive to allow background threads to run
        while True:
            # Check if any thread has stopped
            for i, thread in enumerate(all_threads):
                if not thread.is_alive():
                    print(f"WARNING: {thread_names[i]} thread has stopped unexpectedly.")
                    return
            time.sleep(5)
    except KeyboardInterrupt:
        print("\nShutting down all agents...")

if __name__ == "__main__":
    main()
