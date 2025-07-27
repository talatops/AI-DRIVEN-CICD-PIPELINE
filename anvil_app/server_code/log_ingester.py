# --- Log Ingestion Agent ---
# This agent is responsible for fetching raw text logs for completed jobs.

import anvil.server
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from github import Github, GithubException
import time
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError
import requests

# --- Load Environment Variables ---
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=dotenv_path)

# --- Configuration & State ---
# GitHub Config
GITHUB_PAT = os.getenv("GITHUB_PAT")
g = Github(GITHUB_PAT) if GITHUB_PAT else None

# Anvil Config
ANVIL_UPLINK_KEY = os.getenv("ANVIL_UPLINK_KEY")

# AWS SQS Config
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
LOGS_QUEUE_NAME = os.getenv("LOGS_QUEUE_NAME")

# Agent's internal state
log_agent_state = {
    "agent_name": "Log Ingestion Agent",
    "status": "Idle",
    "last_polled": None,
    "errors": 0,
    "monitoring_repo": "None",
    "sqs_status": "Not Configured"
}

print("Log Ingestion Agent is initializing...")

# --- SQS Client Initialization ---
sqs_client_logs = None
if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and LOGS_QUEUE_NAME:
    try:
        sqs_client_logs = boto3.client(
            'sqs',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )
        sqs_client_logs.get_queue_url(QueueName=LOGS_QUEUE_NAME)
        log_agent_state["sqs_status"] = "Connected"
        print(f"Log Agent: Successfully connected to AWS SQS queue: {LOGS_QUEUE_NAME}")
    except Exception as e:
        log_agent_state["sqs_status"] = "Connection Failed"
        print(f"Log Agent ERROR: Failed to connect to SQS: {e}")
else:
    print("Log Agent WARNING: AWS SQS not configured. Logs will be printed to console.")


# --- Anvil Callable Functions ---

@anvil.server.callable
def get_log_agent_status():
    """Returns the current status of the log ingestion agent."""
    return log_agent_state

@anvil.server.callable
def configure_log_agent_repository(repo_url):
    """Sets the target GitHub repository for the log agent."""
    log_agent_state["monitoring_repo"] = repo_url
    log_agent_state["status"] = f"Configured for {repo_url}"
    return f"Log Agent configured to monitor {repo_url}"

@anvil.server.callable
def trigger_manual_log_collection():
    """Manually triggers a single log collection cycle for the most recent run."""
    print("Manual log collection triggered.")
    repo_url = log_agent_state.get("monitoring_repo")

    if not repo_url or repo_url == "None":
        return "Error: Please configure a repository for the Log Agent first."

    log_agent_state["status"] = "Collecting Logs..."
    log_agent_state["last_polled"] = time.time()

    try:
        repo_name_with_git = '/'.join(repo_url.strip('/').split('/')[-2:])
        repo_name = repo_name_with_git.removesuffix('.git')
        repo = g.get_repo(repo_name)

        # Get the most recent successfully completed workflow run
        run = repo.get_workflow_runs(status="success").get_page(0)[0]
        if not run:
            log_agent_state["status"] = "No recent successful runs found."
            return "No recent successful runs found to fetch logs from."

        print(f"Fetching logs for workflow run ID: {run.id}")
        jobs = run.jobs()

        for job in jobs:
            try:
                # Use the GitHub API to fetch job logs
                # The logs endpoint returns a redirect URL, so we need to follow it
                logs_url = f"https://api.github.com/repos/{repo_name}/actions/jobs/{job.id}/logs"
                headers = {'Authorization': f'token {GITHUB_PAT}', 'Accept': 'application/vnd.github.v3+json'}
                
                response = requests.get(logs_url, headers=headers, allow_redirects=True)
                
                if response.status_code == 200:
                    raw_logs = response.text
                else:
                    raw_logs = f"Error fetching logs: HTTP {response.status_code}"
                    print(f"Error fetching logs for job {job.id}: {response.status_code}")
                    
            except Exception as e:
                raw_logs = f"Error fetching logs: {str(e)}"
                print(f"Error fetching logs for job {job.id}: {e}")
            
            log_message = {
                "event_type": "job_log_processed",
                "data": {
                    "run_id": run.id,
                    "job_id": job.id,
                    "job_name": job.name,
                    "repo": repo_name,
                    "raw_log_content": raw_logs
                },
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # --- Send to SQS or Print to Console ---
            if sqs_client_logs and log_agent_state["sqs_status"] == "Connected":
                try:
                    response = sqs_client_logs.get_queue_url(QueueName=LOGS_QUEUE_NAME)
                    queue_url = response['QueueUrl']
                    sqs_client_logs.send_message(
                        QueueUrl=queue_url,
                        MessageBody=json.dumps(log_message)
                    )
                    print(f"Successfully sent logs for Job ID {job.id} to SQS.")
                except Exception as e:
                    print(f"ERROR: Failed to send log message to SQS for job {job.id}: {e}")
                    log_agent_state["errors"] += 1
            else:
                print(f"--- Collected Logs for Job ID: {job.id} (SQS not connected) ---")
                # Truncate for readability in console
                print(raw_logs[:1000] + "...") 
                print("------------------------------------------------------------------")

        log_agent_state["status"] = f"Log collection complete for run {run.id}"
        return f"Log collection finished for run {run.id}."

    except GithubException as e:
        log_agent_state["status"] = f"GitHub API Error: {e.status}"
        log_agent_state["errors"] += 1
        return f"Error accessing GitHub: {e.data.get('message', 'Unknown Error')}"
    except Exception as e:
        log_agent_state["status"] = "An unexpected error occurred."
        log_agent_state["errors"] += 1
        print(f"An unexpected error in log collection: {e}")
        return "An unexpected error occurred during log collection."


def run_log_ingester():
    """Main function to keep the log ingester agent running."""
    if not ANVIL_UPLINK_KEY or not g:
        print("Log Agent ERROR: Missing GITHUB_PAT or ANVIL_UPLINK_KEY. Agent will not run.")
        return

    try:
        anvil.server.connect(ANVIL_UPLINK_KEY)
        print("Log Ingestion Agent successfully connected to Anvil Uplink.")
        log_agent_state["status"] = "Connected to Anvil"
        anvil.server.wait_forever()
    except Exception as e:
        print(f"Log Ingestion Agent failed to connect or stay connected to Anvil: {e}")
        log_agent_state["status"] = "Anvil Connection Failed"

# This check allows the script to be run directly for testing if needed.
if __name__ == "__main__":
    run_log_ingester()
