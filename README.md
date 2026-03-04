# Conversation Analytics Batch Process

A Python script to aggregate conversation analytics from PostgreSQL and store daily metrics for reporting.

## 📊 Features

- Extracts conversation data from `conversations` and `chat_messages` tables
- Calculates key metrics:
  - Total messages per conversation
  - First user message timestamp
  - First bot response timestamp
  - Average response latency (seconds)
  - Total handling time (seconds)
- Categorizes conversations:
  - `WITH_BOT_RESPONSE` - Bot responded at least once
  - `WITHOUT_BOT_RESPONSE` - User sent messages but no bot response
  - `EMPTY` - No messages in conversation
- Filters by date and chatbot ID
- Dry-run mode for testing

## 📁 Project Structure

```
batch_process/
├── conversation_analytics.py    # Main script
├── .env                         # Database URL
├── requirements.txt             # Python dependencies
├── Dockerfile                   # Docker configuration
├── README.md                    # This file
└── venv/                        # Virtual environment
```

## 🚀 Quick Start

### Step 1: Navigate to Project Directory

```bash
cd /home/poovi/poovi/bragdeesh/scripts/batch_process
```

### Step 2: Create and Activate Virtual Environment

```bash
# Create virtual environment (if not exists)
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Configure Database Connection

Create a `.env` file in the project directory:

```bash
DATABASE_URL=postgresql://user:password@localhost:5554/database_name
```

### Step 5: Create the Analytics Table

```sql
CREATE TABLE conversation_analytics (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER UNIQUE,
    chatbot_id UUID,
    conversation_status VARCHAR(50),
    total_messages INTEGER,
    first_user_message_at TIMESTAMP,
    first_bot_response_at TIMESTAMP,
    average_response_latency_seconds NUMERIC(10, 2),
    handling_time_seconds NUMERIC(10, 2),
    conversation_via TEXT,
    start_date DATE,
    end_date DATE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### Step 6: Run the Script

```bash
# Test with dry-run (no data inserted)
python conversation_analytics.py --chatbot-ids YOUR_BOT_ID --dry-run

# Run and insert data
python conversation_analytics.py --chatbot-ids YOUR_BOT_ID

# Run for all chatbots
python conversation_analytics.py
```

## 📋 Command Options

| Option | Description | Example |
|--------|-------------|---------|
| `--chatbot-ids` | Filter by specific chatbot ID(s) | `--chatbot-ids bot-1 bot-2` |
| `--dry-run` | Run without inserting data (test mode) | `--dry-run` |

## 📊 Column Meanings - conversation_analytics Table

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `id` | SERIAL | Auto-incrementing primary key | 1, 2, 3... |
| `conversation_id` | INTEGER | References `conversations.id` | 5753 |
| `chatbot_id` | UUID | The bot that handled this conversation | `d66097dc-...` |
| `conversation_status` | VARCHAR(50) | Status: `WITH_BOT_RESPONSE`, `WITHOUT_BOT_RESPONSE`, or `EMPTY` | `WITH_BOT_RESPONSE` |
| `total_messages` | INTEGER | Total number of message exchanges | 3 |
| `first_user_message_at` | TIMESTAMP | When the first user message was sent | `2026-03-04 15:48:56` |
| `first_bot_response_at` | TIMESTAMP | When the bot responded for the first time | `2026-03-04 15:48:57` |
| `average_response_latency_seconds` | NUMERIC(10,2) | Average time for bot to respond (seconds) | 0.61 |
| `handling_time_seconds` | NUMERIC(10,2) | Total conversation duration (seconds) | 247.50 |
| `conversation_via` | TEXT | Channel: `WEB`, `MOBILE`, `WHATSAPP` | `WEB` |
| `start_date` | DATE | Analytics period start date | `2026-03-04` |
| `end_date` | DATE | Analytics period end date | `2026-03-04` |

### 📖 Metric Explanations

**handling_time_seconds**: Time from conversation start to end
```
handling_time_seconds = conversation.updated_at - conversation.created_at
```

**average_response_latency_seconds**: Average time bot took to respond
```
For each message: latency = message.updated_at - message.created_at
average_response_latency_seconds = AVG(all latencies)
```

**conversation_status**:
- `WITH_BOT_RESPONSE` - Bot responded at least once
- `WITHOUT_BOT_RESPONSE` - User sent messages, no bot response
- `EMPTY` - No messages (total_messages = 0)

## 📊 Database Schema

### Source Tables

**conversations:**
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| conversation_id | UUID | Public conversation ID |
| chatbot_id | UUID | Bot identifier |
| conversation_via | TEXT | Channel (WEB, MOBILE...) |
| created_at | TIMESTAMP | Start time |
| updated_at | TIMESTAMP | End time |

**chat_messages:**
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| conversation_id | INTEGER | FK to conversations.id |
| actual_prompt | TEXT | User message |
| actual_prompt_response | TEXT | Bot response |
| created_at | TIMESTAMP | When user sent message |
| updated_at | TIMESTAMP | When bot responded |

## 🐳 Docker Usage

```bash
# Build image
docker build -t conversation-analytics .

# Run with environment variables
docker run --env-file .env conversation-analytics

# Run with specific chatbot
docker run --env-file .env conversation-analytics python conversation_analytics.py --chatbot-ids YOUR_BOT_ID

# Dry run
docker run --env-file .env conversation-analytics python conversation_analytics.py --dry-run
```

## 🔧 Dependencies

```
psycopg2-binary==2.9.9   # PostgreSQL adapter
python-dotenv==1.0.0      # Environment variable management
```
