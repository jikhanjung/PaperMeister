<#
.SYNOPSIS
  Off-machine backup of the live PaperMeister SQLite DB (consistent + gzipped).

.DESCRIPTION
  Takes a consistent snapshot via the SQLite online-backup API (safe while the
  app/extraction is writing — never a torn WAL copy), gzips it, scp's it to the
  server with a timestamped name, and prunes old backups to the newest $Keep.

  Runs daily at 04:00 under Windows Task Scheduler, as your user so ~/.ssh keys
  resolve, and with "run whether logged on or not". Register it this way rather
  than with plain schtasks — the two settings that matter are not available
  there:

    $action   = New-ScheduledTaskAction -Execute 'powershell' `
        -Argument '-NoProfile -ExecutionPolicy Bypass -File C:\path\to\scripts\backup-papermeister.ps1'
    $trigger  = New-ScheduledTaskTrigger -Daily -At 04:00
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName 'PaperMeister DB Backup' -Force `
        -Action $action -Trigger $trigger -Settings $settings

  -StartWhenAvailable runs a missed 04:00 at the next opportunity, and
  -WakeToRun brings the machine out of sleep for it. Neither helps if it is
  powered off or hibernating, and nothing here can: this is a backup that only
  exists while one desktop happens to be awake.

  That is the residual risk, and the place to notice it is the server, which is
  always on. The filenames carry their own timestamps, so a check is one line —
  worth a cron of its own, because the failure mode is silence:

    find /mnt/disk1/backups/papermeister -name 'papermeister-*.db.gz' -mtime -2 \
      | grep -q . || echo 'PaperMeister backup is more than 2 days old'

  The server directory is created on each run, so there is nothing to set up by
  hand. Restore:  gunzip -c papermeister-YYYYmmdd-HHMMSS.db.gz > papermeister.db

.NOTES
  Needs working key-based ssh/scp to $RemoteHost (the manual scp must already
  succeed).

  Sizing: 2.4 GB gzips to ~1.1 GB, one file per day, so $Keep is a count of
  *days* and of gigabytes-and-a-bit. At 24 that is roughly 26 GB standing on
  the server — which is what filled the home partition it used to write to, and
  what will fill anything else given long enough. Whoever changes the schedule
  has to revisit this number: it was written for a 3-hourly cadence, where the
  same 24 meant three days.
#>

$ErrorActionPreference = 'Stop'

# --- config (edit to taste) -------------------------------------------------
$RemoteHost = 'jikhanserver'
# Not the home directory: these are 1.1 GB a day and they filled it. /mnt/disk1
# is the volume with room for them. The path names the application on purpose —
# the admin who found the home partition full could not tell what was writing
# there, which cost more than the disk did.
$RemoteDir  = '/mnt/disk1/backups/papermeister'
$Keep       = 24                 # files kept on the server = days, at one a day
# Task Scheduler does NOT inherit the conda env's PATH, so 'python' won't resolve
# there — call the env's python by full path (only stdlib is needed). Falls back
# to whatever 'python' is on PATH if that exe doesn't exist.
$Python     = Join-Path $env:USERPROFILE 'anaconda3\envs\PaperMeister\python.exe'
if (-not (Test-Path $Python)) { $Python = 'python' }
# ---------------------------------------------------------------------------

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = Split-Path -Parent $scriptDir

# Ask the app where its database is rather than spelling the path out again.
# Hardcoding it is what broke this script when the data directory moved in
# v0.1.4: it kept pointing at ~/.papermeister and the backup quietly stopped.
# Going through paths.py also means PAPERMEISTER_DATA_DIR is honoured here.
$Db = (& $Python -c "import sys; sys.path.insert(0, r'$repoRoot'); from papermeister.paths import DB_PATH; print(DB_PATH)")
if ($LASTEXITCODE -ne 0 -or -not $Db) { throw "could not resolve the database path via $repoRoot\papermeister\paths.py" }
$Db = $Db.Trim()

$stamp     = Get-Date -Format 'yyyyMMdd-HHmmss'
$name      = "papermeister-$stamp.db.gz"
$localGz   = Join-Path $env:TEMP $name

try {
    # 1) consistent + gzipped snapshot (safe while the DB is being written)
    & $Python (Join-Path $scriptDir '_db_snapshot.py') $Db $localGz
    if ($LASTEXITCODE -ne 0) { throw "snapshot step failed (exit $LASTEXITCODE) — check `$Python: $Python" }
    if (-not (Test-Path $localGz)) { throw "snapshot produced no file: $localGz" }

    # 2) ship to the server (timestamped → accumulates one file per run).
    # The directory is made here rather than by hand: this script has moved its
    # destination once already, and a setup step written only in a comment is
    # the step that gets missed. The note beside the backups says who writes
    # them, so the next person to find a full disk does not have to guess.
    $note = "$RemoteDir/WHAT_WRITES_THESE.txt"
    ssh $RemoteHost "mkdir -p '$RemoteDir' && { [ -f '$note' ] || printf '%s\n' 'PaperMeister SQLite backups.' 'Written daily at 04:00 by scripts/backup-papermeister.ps1 on the Windows machine.' 'Keeps the newest $Keep files (~1.1 GB each); older ones are pruned by that script.' > '$note'; }"
    if ($LASTEXITCODE -ne 0) { throw "could not prepare $RemoteDir on $RemoteHost (exit $LASTEXITCODE)" }

    scp $localGz "${RemoteHost}:${RemoteDir}/${name}"
    if ($LASTEXITCODE -ne 0) { throw "scp failed (exit $LASTEXITCODE)" }

    # 3) retention: keep only the newest $Keep on the server
    $skip = $Keep + 1
    ssh $RemoteHost "ls -t '$RemoteDir'/papermeister-*.db.gz 2>/dev/null | tail -n +$skip | xargs -r rm -f"

    Write-Host "Backup OK: $name"
}
finally {
    # 4) always clean up the local temp copy
    if (Test-Path $localGz) { Remove-Item $localGz -Force }
}
