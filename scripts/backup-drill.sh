#!/bin/bash

################################################################################
# Backup Drill Script
#
# Purpose:
#   Tests Neon database backup and restore workflow by:
#   1. Dumping the staging database to a gzip-compressed SQL file
#   2. Restoring the dump into a temporary Neon branch
#   3. Verifying schema integrity with alembic current
#   4. Cleaning up the temporary branch
#
# Usage:
#   ./backup-drill.sh
#
# Required Environment Variables:
#   NEON_STAGING_DATABASE_URL  - Neon staging database connection string
#   NEON_PROJECT_ID            - Neon project ID for branch operations
#
# Optional Environment Variables:
#   ALEMBIC_DIR                - Path to alembic directory (default: <script_dir>/../platform)
#
# Cron Example:
#   0 3 * * 0  /path/to/backup-drill.sh >> /var/log/agentx-backup.log 2>&1
#
################################################################################

set -euo pipefail

# Configuration — resolve script directory so paths stay portable across users/machines
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALEMBIC_DIR="${ALEMBIC_DIR:-${SCRIPT_DIR}/../platform}"
BACKUP_FILE="/tmp/agentx-backup-$(date +%F).sql.gz"
RESTORE_BRANCH_NAME="restore-test"

# Cleanup trap
cleanup() {
  if [[ -f "$BACKUP_FILE" ]]; then
    echo "Cleaning up backup file: $BACKUP_FILE"
    rm -f "$BACKUP_FILE"
  fi
}
trap cleanup EXIT

# Validate required environment variables
if [[ -z "${NEON_STAGING_DATABASE_URL:-}" ]]; then
  echo "ERROR: NEON_STAGING_DATABASE_URL environment variable is not set" >&2
  exit 1
fi

if [[ -z "${NEON_PROJECT_ID:-}" ]]; then
  echo "ERROR: NEON_PROJECT_ID environment variable is not set" >&2
  exit 1
fi

################################################################################
# Step 1: Dump staging database to gzip file
################################################################################
echo "=========================================="
echo "Step 1: Dumping staging database..."
echo "=========================================="

pg_dump "$NEON_STAGING_DATABASE_URL" | gzip > "$BACKUP_FILE"

BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "✓ Backup created successfully"
echo "  File: $BACKUP_FILE"
echo "  Size: $BACKUP_SIZE"

################################################################################
# Step 2: Restore into temporary branch
################################################################################
echo ""
echo "=========================================="
echo "Step 2: Creating and restoring to branch..."
echo "=========================================="

# Delete existing restore-test branch if it exists
if neon branches list --project-id "$NEON_PROJECT_ID" | grep -q "$RESTORE_BRANCH_NAME"; then
  echo "Deleting existing branch: $RESTORE_BRANCH_NAME"
  neon branches delete "$RESTORE_BRANCH_NAME" --project-id "$NEON_PROJECT_ID" || true
fi

# Create new restore branch
echo "Creating branch: $RESTORE_BRANCH_NAME"
neon branches create --name "$RESTORE_BRANCH_NAME" --project-id "$NEON_PROJECT_ID" > /dev/null

# Get connection string for the restore branch
echo "Retrieving connection string for restore branch..."
RESTORE_URL=$(neon connection-string "$RESTORE_BRANCH_NAME" --project-id "$NEON_PROJECT_ID")
echo "✓ Branch created and connection string retrieved"

# Decompress and restore the dump
echo "Restoring database from dump..."
gunzip -c "$BACKUP_FILE" | psql "$RESTORE_URL" > /dev/null 2>&1
echo "✓ Database restored successfully"

################################################################################
# Step 3: Verify schema integrity with alembic
################################################################################
echo ""
echo "=========================================="
echo "Step 3: Verifying schema integrity..."
echo "=========================================="

cd "$ALEMBIC_DIR"
DATABASE_URL="$RESTORE_URL" alembic current
echo "✓ Schema verification passed"

################################################################################
# Step 4: Delete temporary branch
################################################################################
echo ""
echo "=========================================="
echo "Step 4: Cleaning up temporary branch..."
echo "=========================================="

neon branches delete "$RESTORE_BRANCH_NAME" --project-id "$NEON_PROJECT_ID"
echo "✓ Temporary branch deleted"

################################################################################
# Complete
################################################################################
echo ""
echo "=========================================="
echo "Backup drill completed successfully!"
echo "=========================================="
