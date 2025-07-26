import anvil.server
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from github import Github, GithubException
import time
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError

# This is a server module. It runs on a computer, not in a browser.

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
METRICS_QUEUE_NAME = os.getenv("METRICS_QUEUE_NAME")

# Agent's internal state
state = {
    "agent_name": "Pipeline Monitoring Agent",
    "status": "Idle",
    "last_polled": None,
    "errors": 0,
    "monitoring_repo": "None",
    "sqs_status": "Not Configured"
}

print("Pipeline Monitoring Agent is initializing...")

# --- SQS Client Initialization ---
sqs_client = None
if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and METRICS_QUEUE_NAME:
    try:
        sqs_client = boto3.client(
            'sqs',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )
        # Test credentials by getting queue URL at startup
        sqs_client.get_queue_url(QueueName=METRICS_QUEUE_NAME)
        state["sqs_status"] = "Connected"
        print(f"Successfully connected to AWS SQS queue: {METRICS_QUEUE_NAME}")
    except (NoCredentialsError, PartialCredentialsError):
        state["sqs_status"] = "Invalid Credentials"
        print("ERROR: AWS credentials not found or incomplete.")
    except ClientError as e:
        if e.response['Error']['Code'] == 'AWS.SimpleQueueService.NonExistentQueue':
            state["sqs_status"] = "Queue Not Found"
            print(f"ERROR: SQS Queue '{METRICS_QUEUE_NAME}' does not exist.")
        else:
            state["sqs_status"] = f"Connection Error: {e.response['Error']['Code']}"
            print(f"ERROR: Failed to connect to SQS: {e}")
    except Exception as e:
        state["sqs_status"] = "Connection Failed"
        print(f"An unexpected error occurred during SQS initialization: {e}")
else:
    print("WARNING: AWS SQS not configured. Data will be printed to console instead.")

# --- Anvil Uplink Connection ---
try:
    anvil.server.connect(ANVIL_UPLINK_KEY)
    print("Successfully connected to Anvil Uplink.")
    state["status"] = "Connected to Anvil"
except Exception as e:
    print(f"Failed to connect to Anvil Uplink: {e}")
    state["status"] = "Anvil Connection Failed"


# --- Anvil Callable Functions ---
# These functions can be called from our Anvil frontend.

@anvil.server.callable
def get_collection_status():
    """Returns the current status of the agent."""
    print("Frontend requested agent status.")
    return state

@anvil.server.callable
def configure_repository(repo_url):
    """Sets the target GitHub repository to monitor."""
    print(f"Received request to monitor repository: {repo_url}")
    state["monitoring_repo"] = repo_url
    state["status"] = f"Configured for {repo_url}"
    # In the future, we will validate the repo here
    return f"Successfully configured to monitor {repo_url}"

@anvil.server.callable
def trigger_manual_collection():
    """Manually triggers a single data collection cycle."""
    print("Manual data collection triggered.")
    repo_url = state.get("monitoring_repo")

    if not repo_url or repo_url == "None":
        print("Error: No repository configured.")
        return "Error: Please configure a repository first."

    state["status"] = "Collecting..."
    state["last_polled"] = time.time()

    try:
        # --- Parse Repository URL ---
        # --- Parse Repository URL ---
        # Example: https://github.com/owner/repo.git -> owner/repo
        repo_name_with_git = '/'.join(repo_url.strip('/').split('/')[-2:])
        repo_name = repo_name_with_git.removesuffix('.git')
        
        print(f"Accessing repository: {repo_name}")
        repo = g.get_repo(repo_name)

        print("Fetching recent workflow runs...")
        # Get the 5 most recent workflow runs
        all_runs = repo.get_workflow_runs()
        print(f"[DIAGNOSTIC] Total workflow runs found by API: {all_runs.totalCount}")
        runs = all_runs.get_page(0)[:5]
        print(f"Found {len(runs)} runs to process for this page.")

        for run in runs:
            # --- Collect Workflow Run Details ---
            run_data = {
                "run_id": run.id,
                "workflow_id": run.workflow_id,
                "workflow_name": run.name,
                "status": run.status,
                "conclusion": run.conclusion,
                "created_at": run.created_at.isoformat(),
                "updated_at": run.updated_at.isoformat(),
                "run_started_at": run.run_started_at.isoformat() if run.run_started_at else None,
                "duration_seconds": (run.updated_at - run.run_started_at).total_seconds() if run.run_started_at else 0,
                "head_branch": run.head_branch,
                "head_sha": run.head_sha,
                "event": run.event,
                "html_url": run.html_url,
                "repo": repo.full_name
            }

            # --- Collect Associated Commit Metrics ---
            try:
                commit = repo.get_commit(sha=run.head_sha)
                code_metrics = {
                    "commit_sha": commit.sha,
                    "commit_message": commit.commit.message,
                    "commit_author": commit.commit.author.name,
                    "files_changed_count": commit.files.totalCount,
                    "additions": commit.stats.additions,
                    "deletions": commit.stats.deletions
                }
                run_data["code_metrics"] = code_metrics
            except GithubException as e:
                print(f"Could not fetch commit details for {run.head_sha}: {e}")
                run_data["code_metrics"] = {}

            # --- Collect Job and Step Details ---
            jobs_data = []
            try:
                jobs = run.jobs()
                for job in jobs:
                    job_data = {
                        "job_id": job.id,
                        "job_name": job.name,
                        "status": job.status,
                        "conclusion": job.conclusion,
                        "started_at": job.started_at.isoformat(),
                        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                        "duration_seconds": (job.completed_at - job.started_at).total_seconds() if job.completed_at else 0,
                        "html_url": job.html_url,
                        "steps": [s.name for s in job.steps] # Simplified for now
                    }
                    jobs_data.append(job_data)
            except GithubException as e:
                print(f"Could not fetch job details for run {run.id}: {e}")
            
            run_data["jobs"] = jobs_data

            # --- Format Final Message ---
            # This is the message we will eventually send to SQS
            final_message = {
                "event_type": "workflow_run_processed",
                "data": run_data,
                "timestamp": datetime.utcnow().isoformat()
            }

            # --- Send to SQS or Print to Console ---
            if sqs_client and state["sqs_status"] == "Connected":
                try:
                    response = sqs_client.get_queue_url(QueueName=METRICS_QUEUE_NAME)
                    queue_url = response['QueueUrl']
                    sqs_client.send_message(
                        QueueUrl=queue_url,
                        MessageBody=json.dumps(final_message)
                    )
                    print(f"Successfully sent data for Run ID {run.id} to SQS.")
                except Exception as e:
                    print(f"ERROR: Failed to send message to SQS for run {run.id}: {e}")
                    state["errors"] += 1
            else:
                print(f"--- Collected Data for Run ID: {run.id} (SQS not connected) ---")
                print(json.dumps(final_message, indent=4))
                print("------------------------------------------------------------------")

        state["status"] = f"Collection complete for {repo_name}"
        print("Manual data collection finished.")
        return "Collection cycle completed successfully."

    except GithubException as e:
        state["status"] = "Error: GitHub API Issue"
        state["errors"] += 1
        print(f"GitHub API Error: {e}")
        return f"Error: Failed to access repository or its data. Please check the URL and your PAT permissions. Details: {e.data}"
    except Exception as e:
        state["status"] = "Error: An unexpected error occurred"
        state["errors"] += 1
        print(f"An unexpected error occurred: {e}")
        return f"An unexpected error occurred during collection: {e}"


# --- Main Loop ---
# This function will be called from main.py to start the agent's listening loop.
def start():
    print("Agent is running and waiting for calls from the Anvil frontend...")
    # This call will block forever, keeping the script alive to listen for Anvil calls.
    anvil.server.wait_forever()

# This check allows the script to be run directly for testing if needed.
if __name__ == "__main__":
    start()
