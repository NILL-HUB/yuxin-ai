$ErrorActionPreference = 'Stop'

$source = 'C:\Users\Administrator\.codex\skills'
$workTarget = 'C:\Users\Administrator\.trae-cn\builtin\work\default\skills'
$backupStamp = '20260813_144848'

# 1) 撤销之前误迁到 IDE 的 skills（用备份恢复覆盖项，删除新增项）
$ideTargets = @(
  'C:\Users\Administrator\.trae\skills',
  'C:\Users\Administrator\.trae-cn\skills'
)
$ideConfigs = @(
  'C:\Users\Administrator\.trae\skill-config.json',
  'C:\Users\Administrator\.trae-cn\skill-config.json'
)

$skills = Get-ChildItem -Path $source -Directory | Where-Object { $_.Name -ne '.system' }
foreach ($target in $ideTargets) {
  $backupRoot = Join-Path (Split-Path $target -Parent) "skills_backup_codex_$backupStamp"
  foreach ($skillDir in $skills) {
    $name = $skillDir.Name
    $dest = Join-Path $target $name
    $backupDest = Join-Path $backupRoot $name
    if (Test-Path $backupDest) {
      Copy-Item -Path $backupDest -Destination $dest -Recurse -Force
      Write-Output "restored $name -> $target (from backup)"
    } elseif (Test-Path $dest) {
      Remove-Item -Path $dest -Recurse -Force
      Write-Output "removed migrated $name from $target"
    }
  }
}

foreach ($config in $ideConfigs) {
  $backupConfig = "$config.bak_$backupStamp"
  if (Test-Path $backupConfig) {
    Copy-Item -Path $backupConfig -Destination $config -Force
    Write-Output "restored config $config"
  }
}

# 2) 迁移到 Trae Work CN（default 模型目录，内置同名 skill 不覆盖）
if (-not (Test-Path $workTarget)) {
  New-Item -ItemType Directory -Force -Path $workTarget | Out-Null
}

$existingWorkSkills = @(Get-ChildItem -Path $workTarget -Directory | Select-Object -ExpandProperty Name)
$copied = 0
$skipped = 0
foreach ($skillDir in $skills) {
  $name = $skillDir.Name
  if ($existingWorkSkills -contains $name) {
    Write-Output "skip builtin $name (already exists in Trae Work)"
    $skipped++
    continue
  }
  Copy-Item -Path $skillDir.FullName -Destination (Join-Path $workTarget $name) -Recurse -Force
  $copied++
  Write-Output "copied $name -> Trae Work CN default"
}

Write-Output "Done. copied=$copied skippedBuiltin=$skipped target=$workTarget"
