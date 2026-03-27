#!/usr/bin/env python3
"""Conversation Analytics Batch Process."""
import os
import logging
import argparse
from datetime import date, datetime, timezone
from decimal import Decimal

import psycopg2
import requests
from dotenv import load_dotenv
from urllib.parse import urlparse


# ============ CONFIGURATION ============
# Default account IDs (can be overridden via ACCOUNT_IDS env var as comma-separated)
DEFAULT_ACCOUNT_IDS = [
    "2d2c5ec3-1611-56cf-b000-05ff109bc4b1",
    "86c3cb12-d1d1-5a0e-ab58-3230ec9fe11f"
]


# ============ LOGGING ============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# ============ DATABASE ============
def get_connection():
    """Create and return database connection."""
    db_url = os.getenv('DATABASE_URL')
    parsed = urlparse(db_url)
    logger.info(f"Connecting to: {parsed.hostname}:{parsed.port}/{parsed.path[1:]}")

    return psycopg2.connect(
        dbname=parsed.path[1:],
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port
    )


# ============ CONFIG STORE API ============
def fetch_chatbot_ids_from_api(account_ids, base_url, api_key):
    """Fetch chatbot IDs from config store API for given account IDs."""
    if not base_url or not api_key:
        raise ValueError("CONFIG_STORE_BASE_URL and CONFIG_STORE_API_KEY must be set in environment variables")

    all_chatbot_ids = []
    headers = {
        'Content-Type': 'application/json',
        'x-api-key': api_key
    }

    for account_id in account_ids:
        try:
            url = f"{base_url.rstrip('/')}/api/v1/configs/chatbots?account_id={account_id}"
            logger.info(f"Fetching chatbots for account_id: {account_id}")
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get('success') and data.get('data'):
                chatbot_ids = [bot['id'] for bot in data['data']]
                all_chatbot_ids.extend(chatbot_ids)
                logger.info(f"Fetched {len(chatbot_ids)} chatbot IDs for account {account_id}")
            else:
                logger.warning(f"No chatbots found for account_id: {account_id}")

        except requests.RequestException as e:
            logger.error(f"Failed to fetch chatbots for account {account_id}: {e}")
            continue

    if not all_chatbot_ids:
        raise ValueError(f"No chatbot IDs fetched from API for accounts: {account_ids}")

    logger.info(f"Total chatbot IDs fetched: {len(all_chatbot_ids)}")
    return all_chatbot_ids


# ============ QUERIES ============
FETCH_QUERY = """
    SELECT
        c.id,
        c.chatbot_id,
        c.conversation_via,
        c.created_at,
        COALESCE(mm.total_messages, 0) AS total_messages,
        mm.first_user_message_at,
        mm.first_bot_response_at,
        mm.average_response_latency_seconds,
        EXTRACT(EPOCH FROM (c.updated_at - c.created_at)) AS handling_time_seconds
    FROM conversations c
    LEFT JOIN (
        SELECT
            conversation_id,
            COUNT(*) AS total_messages,
            MIN(created_at) AS first_user_message_at,
            MIN(updated_at) AS first_bot_response_at,
            AVG(EXTRACT(EPOCH FROM (updated_at - created_at))) AS average_response_latency_seconds
        FROM chat_messages
        GROUP BY conversation_id
    ) mm ON mm.conversation_id = c.id
    WHERE DATE(c.created_at AT TIME ZONE 'UTC' AT TIME ZONE %s) = %s
      AND c.chatbot_id IN ({placeholders})
"""

INSERT_QUERY = """
    INSERT INTO conversation_analytics (
        conversation_id, chatbot_id, conversation_status, total_messages,
        first_user_message_at, first_bot_response_at,
        average_response_latency_seconds, handling_time_seconds,
        conversation_via, start_date, end_date, created_at, updated_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


# ============ BUSINESS LOGIC ============
def get_status(total_messages, first_bot_response):
    """Return conversation status based on message data."""
    if total_messages == 0:
        return 'EMPTY'
    return 'WITH_BOT_RESPONSE' if first_bot_response else 'WITHOUT_BOT_RESPONSE'


def round_decimal(value):
    """Round value to 2 decimal places or return None."""
    return Decimal(str(round(value, 2))) if value is not None else None


def fetch_analytics(conn, target_date, chatbot_ids, timezone_offset):
    """Fetch analytics data from database."""
    placeholders = ','.join(['%s'] * len(chatbot_ids))
    query = FETCH_QUERY.format(placeholders=placeholders)

    with conn.cursor() as cursor:
        cursor.execute(query, [timezone_offset, target_date] + chatbot_ids)
        return cursor.fetchall()


def insert_analytics(conn, analytics_data, target_date):
    """Insert analytics data into database."""
    now_utc = datetime.now(timezone.utc)

    with conn.cursor() as cursor:
        for row in analytics_data:
            conv_id, chatbot_id, via, created_at, total, first_user, first_bot, avg_lat, handling = row
            status = get_status(total, first_bot)

            cursor.execute(INSERT_QUERY, (
                conv_id, str(chatbot_id), status, total,
                first_user, first_bot,
                round_decimal(avg_lat),
                round_decimal(handling),
                via, str(target_date), str(target_date), created_at, now_utc
            ))

    conn.commit()
    logger.info(f"Inserted {len(analytics_data)} records")


def log_summary(results):
    """Log summary of fetched results."""
    counts = {'WITH_BOT_RESPONSE': 0, 'WITHOUT_BOT_RESPONSE': 0, 'EMPTY': 0}

    for row in results:
        total = row[4]
        first_bot = row[6]
        counts[get_status(total, first_bot)] += 1

    logger.info(
        f"Total: {len(results)} | "
        f"With Bot: {counts['WITH_BOT_RESPONSE']} | "
        f"Without Bot: {counts['WITHOUT_BOT_RESPONSE']} | "
        f"Empty: {counts['EMPTY']}"
    )


# ============ MAIN ============
def main(dry_run=False):
    """Main execution function."""
    load_dotenv()

    # Get configuration from environment variables
    timezone_offset = os.getenv('TIMEZONE_OFFSET', '+05:30')
    config_store_base_url = os.getenv('CONFIG_STORE_BASE_URL', '')
    config_store_api_key = os.getenv('CONFIG_STORE_API_KEY', '')
    account_ids_env = os.getenv('ACCOUNT_IDS', '')

    # Parse account IDs from env or use defaults
    account_ids = account_ids_env.split(',') if account_ids_env else DEFAULT_ACCOUNT_IDS
    account_ids = [aid.strip() for aid in account_ids if aid.strip()]

    # Fetch chatbot IDs dynamically from API
    chatbot_ids = fetch_chatbot_ids_from_api(account_ids, config_store_base_url, config_store_api_key)

    target_date = date.today()
    logger.info(f"Starting analytics for: {target_date}")
    logger.info(f"Timezone offset: {timezone_offset}")
    logger.info(f"Account IDs: {account_ids}")
    logger.info(f"Chatbot IDs count: {len(chatbot_ids)}")
    if logger.level <= logging.DEBUG:
        logger.debug(f"Chatbot IDs: {chatbot_ids}")

    conn = None
    try:
        conn = get_connection()
        logger.info("Database connection established")

        results = fetch_analytics(conn, target_date, chatbot_ids, timezone_offset)
        log_summary(results)

        if results and not dry_run:
            insert_analytics(conn, results, target_date)
        elif dry_run:
            logger.warning("DRY RUN - Skipping insert")

    except Exception as e:
        logger.error(f"Error: {e}")
        raise
    finally:
        if conn and conn.closed == 0:
            conn.close()
            logger.info("Database connection closed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Conversation Analytics Batch Process')
    parser.add_argument('--dry-run', action='store_true', help='Skip insert')
    args = parser.parse_args()

    main(dry_run=args.dry_run)
