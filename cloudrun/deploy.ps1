<#
.SYNOPSIS
  One-command deploy of the Shorts Autopilot to Google Cloud Run (Windows PowerShell).

.DESCRIPTION
  PowerShell mirror of cloudrun/deploy.sh, for when you can't use Git Bash/WSL/Cloud Shell.
  Idempotent: safe to re-run (redeploys latest code, refreshes changed secrets).

  Expects secret material in cloudrun/secrets/ (gitignored):
    youtube_token.json          -> secret shorts-youtube-token
    instagram_access_token.txt  -> secret shorts-instagram-token
    facebook_access_token.txt   -> secret shorts-facebook-token
    ytdlp-cookies.txt           -> secret shorts-ytdlp-cookies
  Any file you leave out is skipped; that platform auto-disables at boot.

.EXAMPLE
  .\cloudrun\deploy.ps1 -Project your-project-id
  .\cloudrun\deploy.ps1 -Project your-project-id -Region asia-south1 -Cpu 2 -Memory 4Gi
#>
param(
  [string]$Project = "",
  [string]$Region  = "us-central1",
  [string]$Service = "shorts-autopilot",
  [string]$Bucket  = "",
  [string]$ArRepo  = "shorts",
  [string]$SaName  = "shorts-autopilot-sa",
  [string]$Cpu     = "2",
  [string]$Memory  = "4Gi",
  [string]$SecretsDir = "cloudrun/secrets"
)

# NOTE: deliberately NOT setting ErrorActionPreference=Stop — Windows PowerShell 5.1
# turns gcloud's stderr output into spurious errors. We check exit codes explicitly.
function Assert-LastExitCode([string]$Step) {
  if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit code $LASTEXITCODE). See the gcloud output above." }
}

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
  throw "gcloud not found. Install the Google Cloud SDK first: https://cloud.google.com/sdk/docs/install"
}

if (-not $Project) { $Project = (gcloud config get-value project 2>$null) }
if (-not $Project) { throw "No project set. Run: gcloud config set project YOUR_PROJECT_ID  (or pass -Project)" }
if (-not $Bucket)  { $Bucket = "$Project-shorts-state" }

$Image = "$Region-docker.pkg.dev/$Project/$ArRepo/${Service}:latest"
$Sa    = "$SaName@$Project.iam.gserviceaccount.com"

Write-Host "==> project=$Project region=$Region service=$Service bucket=gs://$Bucket"
gcloud config set project $Project | Out-Null
Assert-LastExitCode "gcloud config set project"

Write-Host "==> enabling APIs"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com storage.googleapis.com secretmanager.googleapis.com iam.googleapis.com | Out-Null
Assert-LastExitCode "enable APIs"

Write-Host "==> Artifact Registry repo"
gcloud artifacts repositories describe $ArRepo --location $Region 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
  gcloud artifacts repositories create $ArRepo --repository-format=docker --location $Region | Out-Null
  Assert-LastExitCode "create Artifact Registry repo"
}

Write-Host "==> state bucket gs://$Bucket"
gcloud storage buckets describe "gs://$Bucket" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
  gcloud storage buckets create "gs://$Bucket" --location="$Region" --uniform-bucket-level-access | Out-Null
  Assert-LastExitCode "create bucket"
}

Write-Host "==> runtime service account"
gcloud iam service-accounts describe $Sa 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
  gcloud iam service-accounts create $SaName --display-name="Shorts Autopilot (Cloud Run)" | Out-Null
  Assert-LastExitCode "create service account"
}
gcloud storage buckets add-iam-policy-binding "gs://$Bucket" --member="serviceAccount:$Sa" --role=roles/storage.objectAdmin | Out-Null
gcloud projects add-iam-policy-binding $Project --member="serviceAccount:$Sa" --role=roles/secretmanager.secretAccessor | Out-Null
gcloud projects add-iam-policy-binding $Project --member="serviceAccount:$Sa" --role=roles/logging.logWriter | Out-Null
gcloud projects add-iam-policy-binding $Project --member="serviceAccount:$Sa" --role=roles/monitoring.metricWriter | Out-Null

Write-Host "==> secrets from $SecretsDir"
function Push-Secret([string]$Name, [string]$File) {
  gcloud secrets describe $Name 2>$null | Out-Null
  if ($LASTEXITCODE -eq 0) {
    gcloud secrets versions add $Name --data-file="$File" | Out-Null
  } else {
    gcloud secrets create $Name --replication-policy=automatic --data-file="$File" | Out-Null
  }
  Assert-LastExitCode "create/update secret $Name"
  Write-Host "    $Name <- $File"
}
$secretRefs = @()
if (Test-Path "$SecretsDir/youtube_token.json")          { Push-Secret shorts-youtube-token   "$SecretsDir/youtube_token.json";          $secretRefs += "YOUTUBE_TOKEN_JSON=shorts-youtube-token:latest" }
if (Test-Path "$SecretsDir/instagram_access_token.txt")  { Push-Secret shorts-instagram-token "$SecretsDir/instagram_access_token.txt";  $secretRefs += "INSTAGRAM_ACCESS_TOKEN=shorts-instagram-token:latest" }
if (Test-Path "$SecretsDir/facebook_access_token.txt")   { Push-Secret shorts-facebook-token  "$SecretsDir/facebook_access_token.txt";   $secretRefs += "FACEBOOK_ACCESS_TOKEN=shorts-facebook-token:latest" }
if (Test-Path "$SecretsDir/ytdlp-cookies.txt")           { Push-Secret shorts-ytdlp-cookies   "$SecretsDir/ytdlp-cookies.txt";           $secretRefs += "YTDLP_COOKIES_TXT=shorts-ytdlp-cookies:latest" }
if ($secretRefs.Count -eq 0) {
  Write-Host "    (no secret files found - publishing platforms will auto-disable until you add them)"
}

Write-Host "==> building image (clones + installs HotClip; first build is slow)"
gcloud builds submit --config cloudbuild.yaml --substitutions="_IMAGE=$Image" .
Assert-LastExitCode "Cloud Build"

Write-Host "==> deploying Cloud Run service"
$deployArgs = @(
  "run", "deploy", $Service,
  "--image", $Image,
  "--region", $Region,
  "--service-account", $Sa,
  "--no-cpu-throttling",
  "--min-instances", "1",
  "--max-instances", "1",
  "--cpu", $Cpu,
  "--memory", $Memory,
  "--timeout", "3600",
  "--allow-unauthenticated",
  "--quiet",
  "--add-volume", "name=data,type=cloud-storage,bucket=$Bucket",
  "--add-volume-mount", "volume=data,mount-path=/data",
  "--env-vars-file", "cloudrun/autopilot.env.yaml"
)
if ($secretRefs.Count -gt 0) { $deployArgs += @("--set-secrets", ($secretRefs -join ",")) }
gcloud @deployArgs
Assert-LastExitCode "Cloud Run deploy"

$url = (gcloud run services describe $Service --region $Region --format="value(status.url)")
Write-Host ""
Write-Host "Deployed."
Write-Host "   Dashboard : $url"
Write-Host "   State     : gs://$Bucket"
Write-Host "   Logs      : gcloud run services logs read $Service --region $Region --follow"
Write-Host "   Runbook   : cloudrun/README.md"
