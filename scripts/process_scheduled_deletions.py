#!/usr/bin/env python3
"""
Background script to process scheduled account deletions
This script should be run periodically (e.g., every hour) via cron job

Usage:
    python scripts/process_scheduled_deletions.py

Cron example (run every hour):
    0 * * * * cd /path/to/tartanilla_admin && python scripts/process_scheduled_deletions.py
"""

import os
import sys
import django
from datetime import datetime

# Add the project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tartanilla_admin.settings')
django.setup()

from api.account_deletion import AccountDeletionAPI


def main():
    """Main function to process scheduled deletions"""
    print(f"[{datetime.now()}] Starting scheduled deletion processing...")
    
    try:
        result = AccountDeletionAPI.process_scheduled_deletions()
        
        if result.get('success'):
            processed = result.get('processed', 0)
            failed = result.get('failed', 0)
            
            print(f"[{datetime.now()}] Processed {processed} deletions, {failed} failed")
            
            if processed > 0:
                print(f"[{datetime.now()}] Successfully deleted {processed} accounts")
            
            if failed > 0:
                print(f"[{datetime.now()}] Failed to delete {failed} accounts")
                # In production, you might want to send alerts for failed deletions
            
            if processed == 0 and failed == 0:
                print(f"[{datetime.now()}] No scheduled deletions to process")
        else:
            print(f"[{datetime.now()}] Error processing deletions: {result.get('error')}")
            sys.exit(1)
            
    except Exception as e:
        print(f"[{datetime.now()}] Unexpected error: {str(e)}")
        sys.exit(1)
    
    print(f"[{datetime.now()}] Scheduled deletion processing completed")


if __name__ == "__main__":
    main()