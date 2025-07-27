# --- This is the FINAL corrected code for Form1 in the Anvil Editor ---
from ._anvil_designer import Form1Template
from anvil import *
import anvil.server

class Form1(Form1Template):
  def __init__(self, **properties):
    # Set Form properties and Data Bindings.
    self.init_components(**properties)

    # --- UI Component Setup ---
    self.add_component(Label(text="AI-Driven CI/CD - Multi-Layer Intelligence System", role="headline", align="center"))
    self.add_component(Label(text="Layer-1: Data Collection & Ingestion | Layer-2: Intelligence & Analysis", align="center", italic=True))

    # --- Layer-1 Status Card ---
    layer1_status_card = ColumnPanel(role="card")
    layer1_status_card.add_component(Label(text="Layer-1: Data Collection & Ingestion", role="title"))
    # Pipeline Monitor Status
    self.status_label = Label(text="Pipeline Agent: Connecting...", align="left", bold=True)
    layer1_status_card.add_component(self.status_label)
    self.last_polled_label = Label(text="Last Polled: Never", align="left")
    layer1_status_card.add_component(self.last_polled_label)
    # Log Ingester Status
    self.log_agent_status_label = Label(text="Log Agent: Connecting...", align="left", bold=True)
    layer1_status_card.add_component(self.log_agent_status_label)
    # General Info
    self.monitoring_repo_label = Label(text="Monitoring: None", align="left")
    layer1_status_card.add_component(self.monitoring_repo_label)
    self.refresh_button = Button(text="Refresh Layer-1 Status", icon="fa:refresh")
    self.refresh_button.set_event_handler('click', self.update_status)
    layer1_status_card.add_component(self.refresh_button)
    self.add_component(layer1_status_card)

    # --- Layer-2 Intelligence Dashboard ---
    layer2_status_card = ColumnPanel(role="card")
    layer2_status_card.add_component(Label(text="Layer-2: Intelligence & Analysis", role="title"))
    
    # Feature Engineering Agent
    self.feature_agent_status = Label(text="Feature Engineering: Connecting...", align="left", bold=True)
    layer2_status_card.add_component(self.feature_agent_status)
    
    # Anomaly Detection Agent
    self.anomaly_agent_status = Label(text="Anomaly Detection: Connecting...", align="left", bold=True)
    layer2_status_card.add_component(self.anomaly_agent_status)
    
    # Flaky Test Agent
    self.flaky_test_status = Label(text="Flaky Test Detection: Connecting...", align="left", bold=True)
    layer2_status_card.add_component(self.flaky_test_status)
    
    # RCA Agent
    self.rca_agent_status = Label(text="Root Cause Analysis: Connecting...", align="left", bold=True)
    layer2_status_card.add_component(self.rca_agent_status)
    
    # Predictive Agent
    self.predictive_agent_status = Label(text="Predictive Failure: Connecting...", align="left", bold=True)
    layer2_status_card.add_component(self.predictive_agent_status)
    
    # Layer-2 Refresh Button
    self.refresh_layer2_button = Button(text="Refresh Layer-2 Status", icon="fa:brain")
    self.refresh_layer2_button.set_event_handler('click', self.update_layer2_status)
    layer2_status_card.add_component(self.refresh_layer2_button)
    self.add_component(layer2_status_card)

    # --- Configuration Card ---
    config_card = ColumnPanel(role="card")
    config_card.add_component(Label(text="Configuration", role="title"))
    config_card.add_component(Label(text="Enter GitHub Repository URL:"))
    self.repo_url_textbox = TextBox(placeholder="e.g., https://github.com/anvil-works/anvil-runtime")
    config_card.add_component(self.repo_url_textbox)
    self.configure_button = Button(text="Set Repository", role="primary-color")
    self.configure_button.set_event_handler('click', self.configure_button_click)
    config_card.add_component(self.configure_button)
    self.add_component(config_card)

    # --- Manual Actions Card ---
    actions_card = ColumnPanel(role="card")
    actions_card.add_component(Label(text="Manual Actions", role="title"))
    # Metrics Collection Button
    self.manual_collect_button = Button(text="Trigger Manual Data Collection")
    self.manual_collect_button.set_event_handler('click', self.manual_collect_button_click)
    actions_card.add_component(self.manual_collect_button)
    # Log Collection Button
    self.manual_log_collect_button = Button(text="Trigger Manual Log Collection")
    self.manual_log_collect_button.set_event_handler('click', self.manual_log_collect_button_click)
    actions_card.add_component(self.manual_log_collect_button)
    self.add_component(actions_card)

    # --- Layer-2 Intelligence Actions Card ---
    layer2_actions_card = ColumnPanel(role="card")
    layer2_actions_card.add_component(Label(text="Layer-2 Intelligence Actions", role="title"))
    
    # Feature Engineering Manual Trigger
    self.trigger_feature_button = Button(text="Trigger Feature Engineering", icon="fa:cogs")
    self.trigger_feature_button.set_event_handler('click', self.trigger_feature_engineering)
    layer2_actions_card.add_component(self.trigger_feature_button)
    
    # Anomaly Detection Manual Trigger
    self.trigger_anomaly_button = Button(text="Run Anomaly Detection", icon="fa:exclamation-triangle")
    self.trigger_anomaly_button.set_event_handler('click', self.trigger_anomaly_detection)
    layer2_actions_card.add_component(self.trigger_anomaly_button)
    
    # Flaky Test Analysis
    self.trigger_flaky_button = Button(text="Analyze Flaky Tests", icon="fa:bug")
    self.trigger_flaky_button.set_event_handler('click', self.trigger_flaky_analysis)
    layer2_actions_card.add_component(self.trigger_flaky_button)
    
    # Root Cause Analysis
    self.trigger_rca_button = Button(text="Run Root Cause Analysis", icon="fa:search")
    self.trigger_rca_button.set_event_handler('click', self.trigger_rca_analysis)
    layer2_actions_card.add_component(self.trigger_rca_button)
    
    # Predictive Failure Analysis
    self.trigger_predictive_button = Button(text="Run Predictive Analysis", icon="fa:crystal-ball")
    self.trigger_predictive_button.set_event_handler('click', self.trigger_predictive_analysis)
    layer2_actions_card.add_component(self.trigger_predictive_button)
    
    self.add_component(layer2_actions_card)

    # Initialize status on load
    self.update_status() # Initial status update

  def update_status(self, **event_args):
    """Called by buttons to get the latest status from all backend agents."""
    try:
      # Get status from Pipeline Monitoring Agent
      pipeline_status = anvil.server.call('get_collection_status')
      self.status_label.text = f"Pipeline Agent: {pipeline_status['status']}"
      self.monitoring_repo_label.text = f"Monitoring: {pipeline_status['monitoring_repo']}"
      if pipeline_status['last_polled']:
        from datetime import datetime
        ts = datetime.fromtimestamp(pipeline_status['last_polled']).strftime('%Y-%m-%d %H:%M:%S')
        self.last_polled_label.text = f"Last Metrics Poll: {ts}"
      
      # Get status from Log Ingestion Agent
      log_status = anvil.server.call('get_log_agent_status')
      self.log_agent_status_label.text = f"Log Agent: {log_status['status']}"

    except Exception as e:
      self.status_label.text = "Agents Disconnected"
      self.log_agent_status_label.text = f"Log Agent: Error - {str(e)}"
      print(f"Error in manual log collection: {e}")

  def update_layer2_status(self, **event_args):
    """Update Layer-2 agent status information."""
    try:
      # Feature Engineering Agent Status
      feature_status = anvil.server.call('get_feature_engineering_status')
      self.feature_agent_status.text = f"Feature Engineering: {feature_status.get('status', 'Unknown')}"
      
      # Anomaly Detection Agent Status
      anomaly_status = anvil.server.call('get_anomaly_detection_status')
      self.anomaly_agent_status.text = f"Anomaly Detection: {anomaly_status.get('status', 'Unknown')}"
      
      # Flaky Test Agent Status
      flaky_status = anvil.server.call('get_flaky_test_status')
      self.flaky_test_status.text = f"Flaky Test Detection: {flaky_status.get('status', 'Unknown')}"
      
      # RCA Agent Status
      rca_status = anvil.server.call('get_rca_status')
      self.rca_agent_status.text = f"Root Cause Analysis: {rca_status.get('status', 'Unknown')}"
      
      # Predictive Agent Status
      predictive_status = anvil.server.call('get_predictive_status')
      self.predictive_agent_status.text = f"Predictive Failure: {predictive_status.get('status', 'Unknown')}"
      
    except Exception as e:
      print(f"Error updating Layer-2 status: {e}")
      self.feature_agent_status.text = "Feature Engineering: Connection Error"
      self.anomaly_agent_status.text = "Anomaly Detection: Connection Error"
      self.flaky_test_status.text = "Flaky Test Detection: Connection Error"
      self.rca_agent_status.text = "Root Cause Analysis: Connection Error"
      self.predictive_agent_status.text = "Predictive Failure: Connection Error"

  def trigger_feature_engineering(self, **event_args):
    """Trigger manual feature engineering."""
    try:
      self.feature_agent_status.text = "Feature Engineering: Processing..."
      response = anvil.server.call('trigger_manual_feature_engineering')
      self.feature_agent_status.text = f"Feature Engineering: {response.get('message', 'Completed')}"
    except Exception as e:
      self.feature_agent_status.text = f"Feature Engineering: Error - {str(e)}"

  def trigger_anomaly_detection(self, **event_args):
    """Trigger manual anomaly detection."""
    try:
      self.anomaly_agent_status.text = "Anomaly Detection: Analyzing..."
      response = anvil.server.call('trigger_manual_anomaly_detection')
      self.anomaly_agent_status.text = f"Anomaly Detection: {response.get('message', 'Completed')}"
    except Exception as e:
      self.anomaly_agent_status.text = f"Anomaly Detection: Error - {str(e)}"

  def trigger_flaky_analysis(self, **event_args):
    """Trigger manual flaky test analysis."""
    try:
      self.flaky_test_status.text = "Flaky Test Detection: Analyzing..."
      response = anvil.server.call('trigger_manual_flaky_analysis')
      self.flaky_test_status.text = f"Flaky Test Detection: {response.get('message', 'Completed')}"
    except Exception as e:
      self.flaky_test_status.text = f"Flaky Test Detection: Error - {str(e)}"

  def trigger_rca_analysis(self, **event_args):
    """Trigger manual root cause analysis."""
    try:
      self.rca_agent_status.text = "Root Cause Analysis: Processing..."
      response = anvil.server.call('trigger_manual_rca')
      self.rca_agent_status.text = f"Root Cause Analysis: {response.get('message', 'Completed')}"
    except Exception as e:
      self.rca_agent_status.text = f"Root Cause Analysis: Error - {str(e)}"

  def trigger_predictive_analysis(self, **event_args):
    """Trigger manual predictive failure analysis."""
    try:
      self.predictive_agent_status.text = "Predictive Failure: Predicting..."
      response = anvil.server.call('trigger_manual_prediction')
      self.predictive_agent_status.text = f"Predictive Failure: {response.get('message', 'Completed')}"
    except Exception as e:
      self.predictive_agent_status.text = f"Predictive Failure: Error - {str(e)}"

  def configure_button_click(self, **event_args):
    """Called when the 'Set Repository' button is clicked. Configures BOTH agents."""
    repo_url = self.repo_url_textbox.text
    if repo_url:
      try:
        # Configure both agents with the same repository URL
        anvil.server.call('configure_repository', repo_url)
        anvil.server.call('configure_log_agent_repository', repo_url)
        alert(f"Successfully configured both agents to monitor {repo_url}")
        self.update_status()
      except Exception as e:
        alert(f"Error configuring repository: {e}")
    else:
      alert("Please enter a repository URL.")

  def manual_collect_button_click(self, **event_args):
    """Called when the 'Trigger Manual Data Collection' button is clicked."""
    try:
      self.status_label.text = "Pipeline Agent: Manual collection triggered..."
      response = anvil.server.call('trigger_manual_collection')
      alert(response)
      self.update_status()
    except Exception as e:
      alert(f"Error triggering metrics collection: {e}")
      self.update_status()

  def manual_log_collect_button_click(self, **event_args):
    """Called when the 'Trigger Manual Log Collection' button is clicked."""
    try:
      self.log_agent_status_label.text = "Log Agent: Manual collection triggered..."
      response = anvil.server.call('trigger_manual_log_collection')
      alert(response)
      self.update_status()
    except Exception as e:
      alert(f"Error triggering log collection: {e}")
      self.update_status()