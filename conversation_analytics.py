#!/usr/bin/env python3
"""Conversation Analytics Batch Process."""
import os
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from dotenv import load_dotenv
import psycopg2
from urllib.parse import urlparse


# Static Chatbot IDs - Add your chatbot IDs here
CHATBOT_IDS = [
    "d66097dc-0bb4-4be9-93d0-d31046566d1c"
]

# Timezone offset - Set your timezone offset here (default: +5:30 for Asia/Kolkata)
# Format: '+HH:MM' or '-HH:MM'
TIMEZONE_OFFSET = '+05:30'


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def get_connection():
    """Create database connection."""
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


def get_conversation_status(row):
    """Determine conversation status based on data."""
    (conv_id, chatbot_id, via, total, first_user, first_bot, avg_lat, handling) = row

    if total == 0 or (first_user is None and first_bot is None):
        return 'EMPTY'
    elif first_bot is None:
        return 'WITHOUT_BOT_RESPONSE'
    else:
        return 'WITH_BOT_RESPONSE'


def fetch_analytics(conn, target_date, chatbot_ids, timezone_offset='+05:30'):
    """Fetch analytics data from database."""
    placeholders = ','.join(['%s'] * len(chatbot_ids))
    query = f"""
        SELECT
            c.id,
            c.chatbot_id,
            c.conversation_via,
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

    with conn.cursor() as cursor:
        cursor.execute(query, [timezone_offset, target_date] + chatbot_ids)
        return cursor.fetchall()


def insert_analytics(conn, analytics_data, target_date, dry_run=False):
    """Insert analytics data into database."""
    if dry_run:
        logger.warning("DRY RUN - Skipping insert")
        return

    now_utc = datetime.now(timezone.utc)
    with conn.cursor() as cursor:
        for row in analytics_data:
            (conv_id, chatbot_id, via, total, first_user, first_bot, avg_lat, handling) = row
            status = get_conversation_status(row)

            cursor.execute("""
                INSERT INTO conversation_analytics (
                    conversation_id, chatbot_id, conversation_status, total_messages,
                    first_user_message_at, first_bot_response_at,
                    average_response_latency_seconds, handling_time_seconds,
                    conversation_via, start_date, end_date, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                conv_id, str(chatbot_id), status, total,
                first_user, first_bot,
                Decimal(str(round(avg_lat, 2))) if avg_lat else None,
                Decimal(str(round(handling, 2))) if handling else None,
                via, str(target_date), str(target_date), now_utc, now_utc
            ))
    conn.commit()
    logger.info(f"Inserted {len(analytics_data)} records")


def main(dry_run=False):
    """Main function."""
    load_dotenv()

    target_date = date.today()
    logger.info(f"Starting analytics for: {target_date}")
    logger.info(f"Timezone offset: {TIMEZONE_OFFSET}")
    logger.info(f"Chatbot IDs: {CHATBOT_IDS}")

    conn = None
    try:
        conn = get_connection()
        logger.info("Database connection established")

        results = fetch_analytics(conn, target_date, CHATBOT_IDS, TIMEZONE_OFFSET)

        # Count by status
        with_bot = sum(1 for r in results if get_conversation_status(r) == 'WITH_BOT_RESPONSE')
        without_bot = sum(1 for r in results if get_conversation_status(r) == 'WITHOUT_BOT_RESPONSE')
        empty = sum(1 for r in results if get_conversation_status(r) == 'EMPTY')

        logger.info(f"Total: {len(results)} | With Bot: {with_bot} | Without Bot: {without_bot} | Empty: {empty}")

        if results:
            insert_analytics(conn, results, target_date, dry_run)

    except psycopg2.Error as e:
        logger.error(f"Database error: {e}")
        raise
    except Exception as e:
        logger.error(f"Error: {e}")
        raise
    finally:
        if conn:
            try:
                if conn.closed == 0:
                    conn.close()
                    logger.info("Database connection closed")
            except psycopg2.Error as e:
                logger.error(f"Error closing connection: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Conversation Analytics Batch Process')
    parser.add_argument('--dry-run', action='store_true', help='Skip insert')
    args = parser.parse_args()

    main(dry_run=args.dry_run)
