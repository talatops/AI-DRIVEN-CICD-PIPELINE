# Layer-2 Real Data Usage Guide

## 🎯 How to Use Real Data Instead of Dummy Data

### Current Status:
- Layer-2 agents currently use sample/dummy data for demonstration
- To use real data, you need actual CI/CD pipeline failures, test results, and logs

### 🔄 Steps to Enable Real Data Processing:

#### 1. **Get Real Pipeline Data**
```bash
# In Anvil frontend, configure a real GitHub repository
# Click "Set Repository" and enter: https://github.com/your-username/your-repo
# Click "Trigger Manual Data Collection" to collect real pipeline data
```

#### 2. **Modify Layer-2 Agents to Use Real Data**
The agents are designed to automatically process real data from SQS queues. When you:
- Configure AWS SQS credentials in `.env`
- Set up the 4 SQS queues
- Layer-1 agents will send real data to queues
- Layer-2 agents will automatically process that real data

#### 3. **Manual Testing with Real Data**
To test Layer-2 agents with real data immediately:

**A. Feature Engineering with Real Data:**
- First collect real pipeline data using "Trigger Manual Data Collection"
- The Feature Engineering agent will process that real data automatically

**B. Anomaly Detection with Real Data:**
- Needs processed features from Feature Engineering agent
- Will detect real anomalies in your actual pipeline performance

**C. Flaky Test Analysis with Real Data:**
- Requires test result data from your actual CI/CD runs
- Will identify real flaky tests in your test suite

**D. Root Cause Analysis with Real Data:**
- Needs actual failure logs from your pipeline
- Will analyze real error patterns and provide actionable insights

**E. Predictive Failure Analysis with Real Data:**
- Uses real historical pipeline data
- Predicts actual failure probability for upcoming runs

### 🚀 Quick Start with Real Data:

1. **Configure a real GitHub repository** in the Anvil frontend
2. **Trigger manual data collection** to get real pipeline data
3. **Wait for Layer-1 to collect data** (check terminal output)
4. **Trigger Layer-2 agents** - they'll process the real data automatically

### 📊 Real Data Flow:
```
Real GitHub Repo → Layer-1 Agents → SQS Queues → Layer-2 Agents → AI Analysis
```

### ⚠️ Current Limitations:
- Without AWS SQS configured, agents use console output
- Manual triggers currently use sample data for immediate demonstration
- Real data processing happens automatically when SQS is configured

### 🔧 To Enable Full Real Data Processing:
1. Configure AWS credentials in `.env`
2. Create the 4 SQS queues in AWS
3. Layer-2 agents will automatically switch to processing real data
