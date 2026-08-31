@echo off
REM Read any pending menu photos with the `claude` CLI, on the Max subscription.
REM
REM Posting the proposal is also what asks the Worker to run the auto-approve
REM gate, so a clean read for a venue with no hours publishes itself from here
REM exactly as it would if the Worker had done the reading.
REM
REM Exits immediately when the queue is empty, so a 5-minute schedule costs
REM nothing. Never run directly by Task Scheduler -- read-photos.vbs launches it
REM at window style 0, or it opens a console over whatever is on screen.
cd /d C:\Users\paulm\happy-hour-finder
if not exist logs mkdir logs
python ingest\extract_photo_deals.py >> logs\read-photos.log 2>&1
