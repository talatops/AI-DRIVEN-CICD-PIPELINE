import os
import threading
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Import the agent modules
# We do this after loading .env to ensure they have access to the variables
from anvil_app.server_code import pipeline_monitor
# from anvil_app.server_code import log_ingester # Will be enabled later

def run_pipeline_monitor():
    """
    Runs the pipeline monitoring agent's main loop.
    """
    print("Starting Pipeline Monitoring Agent thread...")
    pipeline_monitor.start()

def run_log_ingester():
    """
    Placeholder function to run the log ingestion agent.
    """
    print("Log Ingestion Agent thread is not yet implemented.")
    # log_ingester.start()

if __name__ == "__main__":
    print("--- Starting AI-Driven CI/CD Data Collection Layer ---")

    # Create and start the thread for the Pipeline Monitoring Agent
    monitor_thread = threading.Thread(target=run_pipeline_monitor, daemon=True)
    monitor_thread.start()

    print("\nPipeline Monitoring Agent is running in the background.")
    print("The script will keep running to maintain the Anvil Uplink connection.")
    print("Press Ctrl+C to stop the agents.")

    # Keep the main thread alive to allow background threads to run
    try:
        while True:
            # You can add main thread tasks here if needed, e.g., health checks
            threading.Event().wait(1) # Wait indefinitely, checking for interrupt
    except KeyboardInterrupt:
        print("\n--- Shutting down agents... ---")
        # The daemon threads will exit automatically when the main thread exits.
        print("Shutdown complete.")
