Requirements: AI-Driven CI/CD Pipeline Optimization & Self-Healing - Data Collection & Ingestion Layer
1. Project Overview
This document outlines the requirements for the initial "Data Collection and Ingestion Layer" of our AI-driven CI/CD optimization and self-healing system. The primary goal of this layer is to establish a robust, real-time (or near real-time) pipeline for gathering comprehensive data from GitHub Actions. This data will then be published to a central message queue, serving as the foundation for subsequent analytical and action-oriented AI agents.

Key Principle: This layer is solely responsible for data acquisition and initial ingestion. It will not perform any analysis, decision-making, or automated changes to the CI/CD pipelines. Its output is raw, structured data sent to an event bus.

2. Core Functionality
The system in this layer will perform the following core functions:

Connect to GitHub API: Securely authenticate and interact with the GitHub API to retrieve CI/CD related data.

Monitor GitHub Actions Workflows: Continuously poll for new and updated workflow run data.

Collect Detailed Workflow Metrics: Extract granular data about workflow runs, jobs, steps, and associated code.

Ingest Raw Logs: Download and forward raw logs from GitHub Actions jobs.

Publish to Message Queue: Send all collected data as structured messages to a designated message queue.

Provide Frontend Visibility (Anvil): Offer a basic Anvil application to display the status of data collection and a rudimentary view of ingested data.

3. Technical Stack
Backend Agents: Python 3.9+

GitHub API Interaction: PyGithub library

Message Queue: AWS Simple Queue Service (SQS) (or Azure Service Bus / Google Cloud Pub/Sub as alternatives if preferred for cloud environment)

Python SDK for SQS: boto3

Frontend: Anvil (Python-based web framework)

Authentication: GitHub Personal Access Token (PAT) for initial prototyping. For production, consider a GitHub App for more secure and granular permissions. AWS Access Key ID and Secret Access Key for SQS.

4. Agent Details
4.1. Pipeline Monitoring Agent (Python)
Purpose: To continuously fetch structured data about GitHub Actions workflow runs, jobs, steps, and related code changes.

Interaction with GitHub Actions:

Authentication:

The agent must authenticate with GitHub using a Personal Access Token (PAT).

The PAT must have repo scope (or more specific actions:read, contents:read permissions) to access repository and workflow data.

The PAT should be stored securely (e.g., as an environment variable or Anvil App Secret).

Data Collection Mechanism:

Implement a polling mechanism that periodically (e.g., every 30-60 seconds) queries the GitHub API for new or updated workflow runs.

Maintain state (e.g., last updated_at timestamp or last run_id processed) to avoid re-processing old data and efficiently fetch only new events.

Data Points to Collect (for each relevant workflow run):

Workflow Run Details:

run_id (unique identifier for the workflow run)

workflow_id (ID of the workflow definition)

workflow_name (Name of the workflow, e.g., "CI Build")

status (e.g., "queued", "in_progress", "completed")

conclusion (e.g., "success", "failure", "cancelled", "skipped")

created_at (Timestamp when the run was created)

updated_at (Timestamp when the run was last updated)

run_started_at (Timestamp when the run actually started)

duration_seconds (Calculated: completed_at - run_started_at if completed)

head_branch (Branch name that triggered the run)

head_sha (Commit SHA that triggered the run)

event (e.g., "push", "pull_request", "workflow_dispatch")

html_url (Link to the workflow run in GitHub UI)

Job Details (for each job within a workflow run):

job_id

job_name

status, conclusion, started_at, completed_at, duration_seconds

html_url (Link to the job in GitHub UI)

runner_name (if applicable, for self-hosted runners)

Step Details (for each step within a job):

step_name

status, conclusion, started_at, completed_at, duration_seconds

number (step order)

Code Metrics (associated with the head_sha):

commit_sha

commit_message

commit_author

files_changed_count (number of files changed in the commit that triggered the run)

additions, deletions (lines added/deleted in the triggering commit)

pull_request_id (if triggered by a PR, link to PR details)

Output: Each collected data point (workflow run, job, step, or aggregated commit info) should be formatted as a JSON message and published to the Event Bus (SQS).

4.2. Log Ingestion Agent (Python)
Purpose: To fetch raw text logs for each GitHub Actions job and push them to the Event Bus.

Interaction with GitHub Actions:

Authentication: Uses the same GitHub PAT as the Pipeline Monitoring Agent.

Data Collection Mechanism:

This agent should subscribe to messages from the Event Bus (e.g., a github.jobs.completed or github.jobs.in_progress event) to know when to fetch logs for a specific job.

It will then use the GitHub API to download the raw logs for that job.

Data Points to Collect:

run_id, job_id, repo_name (to link logs back to the run/job)

log_content (the full raw text content of the job's log)

timestamp (when the log was fetched)

Output: Each job's raw log content, along with identifying metadata, should be formatted as a JSON message and published to the Event Bus (SQS).

5. Event Bus / Message Queue (AWS SQS)
Purpose: To act as a central, decoupled communication channel for all collected data. This ensures scalability, reliability, and asynchronous processing.

Setup:

Create at least two SQS queues:

ci_cd_metrics_queue: For structured workflow, job, step, and code metrics.

ci_cd_logs_queue: For raw job logs.

Configure appropriate IAM policies for the Python agents to send messages to these queues.

Message Structure: All messages published to SQS should be JSON objects.

Example ci_cd_metrics_queue message:

{
    "event_type": "workflow_run_completed",
    "data": {
        "run_id": 12345,
        "workflow_name": "Build & Deploy",
        "status": "completed",
        "conclusion": "success",
        "duration_seconds": 300,
        "repo": "my-org/my-app",
        "head_sha": "abcdef12345...",
        "jobs": [
            {
                "job_id": 67890,
                "job_name": "Build Frontend",
                "status": "completed",
                "conclusion": "success",
                "duration_seconds": 120,
                "steps": [
                    {"step_name": "Checkout", "status": "completed"},
                    {"step_name": "Install Deps", "status": "completed"}
                ]
            }
        ],
        "code_metrics": {
            "commit_author": "John Doe",
            "files_changed_count": 5,
            "additions": 20,
            "deletions": 5
        }
    },
    "timestamp": "2025-07-26T14:30:00Z"
}

Example ci_cd_logs_queue message:

{
    "event_type": "job_log_fetched",
    "data": {
        "run_id": 12345,
        "job_id": 67890,
        "repo": "my-org/my-app",
        "log_content": "..." // Large string of raw log data
    },
    "timestamp": "2025-07-26T14:30:05Z"
}

6. Anvil Frontend Requirements
Purpose: To provide a simple web interface for monitoring the data collection process and viewing raw ingested data.

Components:

Main Dashboard (Anvil Form):

Display the status of the Pipeline Monitoring Agent (e.g., "Running", "Last Polled: X seconds ago", "Errors: Y").

Display the status of the Log Ingestion Agent.

Show a count of messages sent to ci_cd_metrics_queue and ci_cd_logs_queue.

Allow users to input a GitHub repository URL (e.g., https://github.com/owner/repo) to configure which repository the agents should monitor.

A button to manually trigger a data collection cycle (for testing/demonstration).

Data Viewer (Anvil Form/Component):

A simple table or list to display the most recent 10-20 workflow run metrics ingested into SQS (by consuming messages from ci_cd_metrics_queue or a temporary storage if direct SQS consumption in Anvil is too complex).

A separate section or modal to view raw job logs. Users should be able to select a run_id and job_id to retrieve and display its raw log content.

Interaction with Python Backend (Anvil Uplink):

The Python agents (Pipeline Monitoring, Log Ingestion) will run as Anvil Uplink servers. This allows the Anvil frontend to directly call functions exposed by these Python processes.

Anvil Server Functions:

get_collection_status(): Returns current status of agents (running, last polled, error counts).

configure_repository(repo_url): Instructs the agents to start monitoring a specific GitHub repository.

trigger_manual_collection(): Initiates an immediate data collection run.

get_recent_metrics(): Fetches a small batch of recent metrics from SQS or a temporary cache for display.

get_job_logs(run_id, job_id): Fetches specific job logs from SQS or a temporary cache.

Styling: Use Anvil's built-in themes and components for a clean, functional UI.

7. Deployment Considerations (for Windsurf)
Python Agents Deployment:

The Python agents should be deployed as long-running processes that connect to Anvil via Uplink.

They need persistent access to the internet to reach GitHub API and AWS SQS.

Secrets Management:

GitHub PAT and AWS credentials (Access Key ID, Secret Access Key) must be securely managed. Anvil App Secrets are a suitable mechanism for this.

Scalability (Future): While this layer focuses on collection, consider that the agents might need to scale horizontally if monitoring many repositories or high-volume pipelines. The use of SQS already facilitates this.

Error Handling: Agents should implement try-except blocks for API calls and SQS interactions, logging errors gracefully without crashing.

8. Deliverables
A functional Anvil web application demonstrating:

Configuration of GitHub repositories for monitoring.

Real-time status of data collection agents.

A basic view of ingested GitHub Actions workflow run metrics.

Ability to retrieve and display raw job logs.

Python code for the Pipeline Monitoring Agent and Log Ingestion Agent that:

Connects to GitHub API using PyGithub.

Sends data to AWS SQS using boto3.

Exposes functions via Anvil Uplink for frontend interaction.

Clear instructions on how to set up GitHub PAT and AWS SQS queues.