#!/usr/bin/env python3
"""Conversation Analytics Batch Process."""
import os
import logging
import argparse
from datetime import date, datetime, timezone
from decimal import Decimal

import psycopg2
from dotenv import load_dotenv
from urllib.parse import urlparse


# ============ CONFIGURATION ============


CHATBOT_IDS = [
    "d66097dc-0bb4-4be9-93d0-d31046566d1c",
    "d7cca6ba-2259-4df7-8bf4-674fa8aa194e",
    "9b6e4fd9-f368-402e-8ba1-4085f0ef96d7"
]
TIMEZONE_OFFSET = '+05:30'


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


def fetch_analytics(conn, target_date, chatbot_ids):
    """Fetch analytics data from database."""
    placeholders = ','.join(['%s'] * len(chatbot_ids))
    query = FETCH_QUERY.format(placeholders=placeholders)

    with conn.cursor() as cursor:
        cursor.execute(query, [TIMEZONE_OFFSET, target_date] + chatbot_ids)
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

    target_date = date.today()
    logger.info(f"Starting analytics for: {target_date}")
    logger.info(f"Timezone offset: {TIMEZONE_OFFSET}")
    logger.info(f"Chatbot IDs: {CHATBOT_IDS}")

    conn = None
    try:
        conn = get_connection()
        logger.info("Database connection established")

        results = fetch_analytics(conn, target_date, CHATBOT_IDS)
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
