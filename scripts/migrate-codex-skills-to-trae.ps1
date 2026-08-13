$ErrorActionPreference = 'Stop'

$source = 'C:\Users\Administrator\.codex\skills'
$targets = @(
  'C:\Users\Administrator\.trae\skills',
  'C:\Users\Administrator\.trae-cn\skills'
)
$configs = @(
  'C:\Users\Administrator\.trae\skill-config.json',
  'C:\Users\Administrator\.trae-cn\skill-config.json'
)
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$report = [System.Collections.Generic.List[string]]::new()

if (-not (Test-Path $source)) {
  throw "Codex skills source not found: $source"
}

$skills = Get-ChildItem -Path $source -Directory | Where-Object { $_.Name -ne '.system' }
if (-not $skills) {
  throw 'No personal skills found under Codex skills directory.'
}

foreach ($target in $targets) {
  if (-not (Test-Path $target)) {
    New-Item -ItemType Directory -Force -Path $target | Out-Null
  }
  $backupRoot = Join-Path (Split-Path $target -Parent) "skills_backup_codex_$stamp"

  foreach ($skillDir in $skills) {
    $skillName = $skillDir.Name
    $dest = Join-Path $target $skillName

    if (Test-Path $dest) {
      $backupDest = Join-Path $backupRoot $skillName
      New-Item -ItemType Directory -Force -Path (Split-Path $backupDest -Parent) | Out-Null
      Copy-Item -Path $dest -Destination $backupDest -Recurse -Force
      $report.Add("backed up existing $skillName -> $backupDest")
    }

    Copy-Item -Path $skillDir.FullName -Destination $dest -Recurse -Force
    $report.Add("copied $skillName -> $target")
  }
}

foreach ($config in $configs) {
  if (-not (Test-Path $config)) {
    $report.Add("skip config (not found): $config")
    continue
  }
  Copy-Item -Path $config -Destination "$config.bak_$stamp" -Force
  $raw = [System.IO.File]::ReadAllText($config, [System.Text.Encoding]::UTF8)
  $json = $raw | ConvertFrom-Json

  if ($null -eq $json.managedSkills) {
    $json | Add-Member -NotePropertyName 'managedSkills' -NotePropertyValue ([ordered]@{})
  }

  foreach ($skillDir in $skills) {
    $name = $skillDir.Name
    $existing = $json.managedSkills.PSObject.Properties.Name
    if ($existing -notcontains $name) {
      $json.managedSkills | Add-Member -NotePropertyName $name -NotePropertyValue 'user_upload'
      $report.Add("registered $name in $config")
    }
  }

  $output = $json | ConvertTo-Json -Depth 10
  [System.IO.File]::WriteAllText($config, $output, [System.Text.UTF8Encoding]::new($false))
}

$report | ForEach-Object { Write-Output $_ }
Write-Output "Done. Backups/config backups use stamp: $stamp"
