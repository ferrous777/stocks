#!/bin/bash
#
# Daily Market Data Collection Cron Job Setup
# 
# This script sets up cron jobs for automated daily market data collection
# Run this script once to install the cron jobs

# Get the absolute path to the project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Create the cron job command
CRON_COMMAND="cd $PROJECT_DIR && python scheduler_cli.py run >> logs/cron.log 2>&1"

# Create logs directory if it doesn't exist
mkdir -p "$PROJECT_DIR/logs"

# Function to install cron job
install_cron_job() {
    local schedule="$1"
    local description="$2"
    
    echo "Installing cron job: $description"
    echo "Schedule: $schedule"
    echo "Command: $CRON_COMMAND"
    echo ""
    
    # Check if cron job already exists
    if crontab -l 2>/dev/null | grep -q "$PROJECT_DIR.*scheduler_cli.py"; then
        echo "⚠️  Cron job already exists. Removing old job first..."
        # Remove existing job
        crontab -l 2>/dev/null | grep -v "$PROJECT_DIR.*scheduler_cli.py" | crontab -
    fi
    
    # Add new cron job
    (crontab -l 2>/dev/null; echo "$schedule $CRON_COMMAND") | crontab -
    
    echo "✅ Cron job installed successfully!"
    echo ""
}

# Function to show current cron jobs
show_cron_jobs() {
    echo "Current cron jobs:"
    echo "=================="
    crontab -l 2>/dev/null | grep -E "(scheduler_cli|market|stock)" || echo "No market-related cron jobs found"
    echo ""
}

# Function to remove cron jobs
remove_cron_jobs() {
    echo "Removing market data cron jobs..."
    crontab -l 2>/dev/null | grep -v "$PROJECT_DIR.*scheduler_cli.py" | crontab -
    echo "✅ Cron jobs removed"
    echo ""
}

# Main menu
echo "🕐 Daily Market Data Scheduler - Cron Job Setup"
echo "==============================================="
echo ""
echo "Project Directory: $PROJECT_DIR"
echo ""
echo "Options:"
echo "1. Install daily cron job (runs at 6:00 PM EST on weekdays)"
echo "2. Install test cron job (runs every 15 minutes for testing)"
echo "3. Show current cron jobs"
echo "4. Remove all market data cron jobs"
echo "5. Manual test run"
echo "6. Exit"
echo ""

read -p "Choose an option (1-6): " choice

case $choice in
    1)
        # Daily job at 6:00 PM EST on weekdays (after market close)
        # Cron format: minute hour day month dayofweek
        # 0 18 = 6:00 PM, 1-5 = Monday through Friday
        install_cron_job "0 18 * * 1-5" "Daily market data collection (6:00 PM EST, weekdays)"
        ;;
    2)
        # Test job every 15 minutes
        install_cron_job "*/15 * * * *" "Test job (every 15 minutes)"
        echo "⚠️  This is a test schedule that runs every 15 minutes."
        echo "   Remember to remove it after testing!"
        ;;
    3)
        show_cron_jobs
        ;;
    4)
        remove_cron_jobs
        ;;
    5)
        echo "Running manual test..."
        cd "$PROJECT_DIR"
        python scheduler_cli.py test
        echo ""
        echo "Test completed. Check the output above for any issues."
        ;;
    6)
        echo "Exiting..."
        exit 0
        ;;
    *)
        echo "Invalid option. Please choose 1-6."
        exit 1
        ;;
esac

echo "Setup completed!"
echo ""
echo "📝 Notes:"
echo "- Cron jobs will run in the background automatically"
echo "- Check logs/cron.log for cron job output"
echo "- Check logs/daily_scheduler.log for detailed scheduler logs"
echo "- Use 'crontab -l' to view all cron jobs"
echo "- Use 'crontab -e' to manually edit cron jobs"
echo ""
echo "To view recent log activity:"
echo "  tail -f logs/cron.log"
echo "  tail -f logs/daily_scheduler.log"
