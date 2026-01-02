# Activity Tracker Backend
This is a *Activity Tracker backend* built using AWS Lambda + AWS SAM.
The backend aggregates data from Jira, GitHub and internal databases to expose deterministic metrics APIs and a read-only AI interpretation layer.
## Tech Stack
- *Python 3.10 / 3.11*
- *AWS Lambda*
- *AWS SAM (Serverless Application Model)*
- *PostgreSQL*
- *psycopg2*
- *OpenAI API (gpt-4o-mini) for AI*
- *Swagger*
- *Docker (for SAM local execution)*
  
----
Each feature is implemented as an independent Lambda function


## Setup

### 1. Install dependencies
pip install -r requirements.txt

### 2. Set environment variables
(DB credentials, OpenAI API key,..) via env.json for local use

### 3. Build & Run locally
sam build

sam local start-api --env-vars env.json
