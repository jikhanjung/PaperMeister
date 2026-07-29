<#
.SYNOPSIS
  Off-machine backup of the live PaperMeister SQLite DB (consistent + gzipped).

.DESCRIPTION
  Takes a consistent snapshot via the SQLite online-backup API (safe while the
  app/extraction is writing — never a torn WAL copy), gzips it, scp's it to the
  server with a timestamped name, and prunes old backups to the newest $Keep.

  Run every 3 hours with Windows Task Scheduler (run AS your user so ~/.ssh keys
  resolve; "run whether logged on or not"):

    schtasks /Create /TN "PaperMeister DB Backup" /SC HOURLY /MO 3 `
      /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\path\to\scripts\backup-papermeister.ps1"

  One-time on the server:  ssh jikhanserver "mkdir -p ~/backups"
  Restore:                 gunzip -c papermeister-YYYYmmdd-HHMMSS.db.gz > papermeister.db

.NOTES
  Needs working key-based ssh/scp to $RemoteHost (the manual scp must already
  succeed). 2.4 GB gzips to ~1 GB; at 3 h intervals, $Keep=24 ≈ 3 days retained.
#>

$ErrorActionPreference = 'Stop'

# --- config (edit to taste) -------------------------------------------------
$RemoteHost = 'jikhanserver'
$RemoteDir  = '~/backups'        # server-side directory (created once, see above)
$Keep       = 24                 # number of recent backups to retain on the server
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

    # 2) ship to the server (timestamped → accumulates one file per run)
    scp $localGz "${RemoteHost}:${RemoteDir}/${name}"
    if ($LASTEXITCODE -ne 0) { throw "scp failed (exit $LASTEXITCODE)" }

    # 3) retention: keep only the newest $Keep on the server
    $skip = $Keep + 1
    ssh $RemoteHost "ls -t $RemoteDir/papermeister-*.db.gz 2>/dev/null | tail -n +$skip | xargs -r rm -f"

    Write-Host "Backup OK: $name"
}
finally {
    # 4) always clean up the local temp copy
    if (Test-Path $localGz) { Remove-Item $localGz -Force }
}
