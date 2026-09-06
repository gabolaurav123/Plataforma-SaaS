param([Parameter(Mandatory=$true)][string]$BackupDirectory)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$backupTarget = [System.IO.Path]::GetFullPath($BackupDirectory)
New-Item -ItemType Directory -Force -Path $backupTarget | Out-Null
$backupName = 'creator-platform-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.dump'
$containerBackup = '/tmp/' + $backupName
Push-Location $projectRoot
try {
    docker compose exec -T db pg_dump -U platform_system -d creator_platform -Fc -f $containerBackup
    if ($LASTEXITCODE -ne 0) { throw 'Database backup failed' }
    docker compose cp ('db:' + $containerBackup) (Join-Path $backupTarget $backupName)
    if ($LASTEXITCODE -ne 0) { throw 'Copying backup failed' }
    Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $backupTarget $backupName) | Format-List
    $receiptName = $backupName.Replace('.dump', '-receipts.tar.gz')
    docker compose exec -T api tar -C /app/storage -czf ('/tmp/' + $receiptName) .
    if ($LASTEXITCODE -ne 0) { throw 'Receipt backup failed' }
    docker compose cp ('api:/tmp/' + $receiptName) (Join-Path $backupTarget $receiptName)
    if ($LASTEXITCODE -ne 0) { throw 'Copying receipt backup failed' }
    Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $backupTarget $receiptName) | Format-List
} finally { Pop-Location }
# Use an encrypted backup destination; back up the keyring separately via your secret vault.
