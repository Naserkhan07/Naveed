#!/usr/bin/env bash
# One-command deploy of the Shorts Autopilot to Google Cloud Run.
#
# Idempotent and safe to re-run (re-running redeploys the latest code + refreshes
# any changed secrets). Reads secret material from cloudrun/secrets/ (gitignored):
#
#   cloudrun/secrets/youtube_token.json        -> secret shorts-youtube-token
#   cloudrun/secrets/instagram_access_token.txt -> secret shorts-instagram-token
#   cloudrun/secrets/facebook_access_token.txt  -> secret shorts-facebook-token
#   cloudrun/secrets/ytdlp-cookies.txt          -> secret shorts-ytdlp-cookies
#
# Any file you leave out is simply skipped (the matching platform auto-disables).
#
# Usage:
#   bash cloudrun/deploy.sh                       # uses gcloud's current project
#   bash cloudrun/deploy.sh --project my-proj --region us-central1
set -euo pipefail

# ---- configuration (override with flags or env) ------------------------------
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-shorts-autopilot}"
AR_REPO="${AR_REPO:-shorts}"
BUCKET="${BUCKET:-}"                       # default: ${PROJECT_ID}-shorts-state
SECRETS_DIR="${SECRETS_DIR:-cloudrun/secrets}"
SA_NAME="${SA_NAME:-shorts-autopilot-sa}"
CPU="${CPU:-2}"
MEMORY="${MEMORY:-4Gi}"

while [ $# -gt 0 ]; do
  case "$1" in
    --project) PROJECT_ID="$2"; shift 2;;
    --region)  REGION="$2"; shift 2;;
    --service) SERVICE="$2"; shift 2;;
    --bucket)  BUCKET="$2"; shift 2;;
    --cpu)     CPU="$2"; shift 2;;
    --memory)  MEMORY="$2"; shift 2;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done

if [ -z "$PROJECT_ID" ]; then
  echo "No project set. Run:  gcloud config set project YOUR_PROJECT_ID   (or pass --project)" >&2
  exit 1
fi
[ -n "$BUCKET" ] || BUCKET="${PROJECT_ID}-shorts-state"

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${SERVICE}:latest"
SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "==> project=$PROJECT_ID region=$REGION service=$SERVICE bucket=gs://$BUCKET"
gcloud config set project "$PROJECT_ID" >/dev/null

echo "==> enabling APIs"
gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  storage.googleapis.com secretmanager.googleapis.com iam.googleapis.com >/dev/null

echo "==> Artifact Registry repo"
if ! gcloud artifacts repositories describe "$AR_REPO" --location "$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$AR_REPO" \
    --repository-format=docker --location "$REGION" >/dev/null
fi

echo "==> state bucket gs://$BUCKET"
if ! gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://$BUCKET" \
    --location="$REGION" --uniform-bucket-level-access >/dev/null
fi

echo "==> runtime service account"
if ! gcloud iam service-accounts describe "$SA" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name="Shorts Autopilot (Cloud Run)" >/dev/null
fi
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:${SA}" --role=roles/storage.objectAdmin >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA}" --role=roles/secretmanager.secretAccessor >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA}" --role=roles/logging.logWriter >/dev/null || true
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA}" --role=roles/monitoring.metricWriter >/dev/null || true

echo "==> secrets from $SECRETS_DIR"
create_secret_from_file() { # name file
  local name="$1" file="$2"
  if gcloud secrets describe "$name" >/dev/null 2>&1; then
    gcloud secrets versions add "$name" --data-file="$file" >/dev/null
  else
    gcloud secrets create "$name" --replication-policy=automatic --data-file="$file" >/dev/null
  fi
  echo "    $name <- $file"
}
SECRET_REFS=()
[ -f "$SECRETS_DIR/youtube_token.json" ]        && { create_secret_from_file shorts-youtube-token   "$SECRETS_DIR/youtube_token.json";        SECRET_REFS+=("YOUTUBE_TOKEN_JSON=shorts-youtube-token:latest"); }
[ -f "$SECRETS_DIR/instagram_access_token.txt" ] && { create_secret_from_file shorts-instagram-token "$SECRETS_DIR/instagram_access_token.txt"; SECRET_REFS+=("INSTAGRAM_ACCESS_TOKEN=shorts-instagram-token:latest"); }
[ -f "$SECRETS_DIR/facebook_access_token.txt" ]  && { create_secret_from_file shorts-facebook-token  "$SECRETS_DIR/facebook_access_token.txt";  SECRET_REFS+=("FACEBOOK_ACCESS_TOKEN=shorts-facebook-token:latest"); }
[ -f "$SECRETS_DIR/ytdlp-cookies.txt" ]          && { create_secret_from_file shorts-ytdlp-cookies   "$SECRETS_DIR/ytdlp-cookies.txt";          SECRET_REFS+=("YTDLP_COOKIES_TXT=shorts-ytdlp-cookies:latest"); }
if [ ${#SECRET_REFS[@]} -eq 0 ]; then
  echo "    (no secret files found — publishing platforms will auto-disable until you add them)"
fi

echo "==> building image (clones + installs HotClip; first build is slow)"
gcloud builds submit --config cloudbuild.yaml --substitutions=_IMAGE="$IMAGE" .

echo "==> deploying Cloud Run service"
DEPLOY_ARGS=(
  run deploy "$SERVICE"
  --image "$IMAGE"
  --region "$REGION"
  --service-account "$SA"
  --no-cpu-throttling
  --min-instances 1
  --max-instances 1
  --cpu "$CPU"
  --memory "$MEMORY"
  --timeout 3600
  --allow-unauthenticated
  --add-volume "name=data,type=cloud-storage,bucket=${BUCKET}"
  --add-volume-mount "volume=data,mount-path=/data"
  --env-vars-file cloudrun/autopilot.env.yaml
)
if [ ${#SECRET_REFS[@]} -gt 0 ]; then
  joined="$(IFS=,; echo "${SECRET_REFS[*]}")"
  DEPLOY_ARGS+=(--set-secrets "$joined")
fi
gcloud "${DEPLOY_ARGS[@]}"

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
cat <<EOF

✅  Deployed.

   Dashboard : $URL
   State     : gs://$BUCKET   (mounted at /data: queue DB, watch + export folders, links)
   Logs      : gcloud run services logs read $SERVICE --region $REGION --follow

   Notes:
   • The first clip downloads HotClip's ML models into the bucket, so clipping is
     slow at first and faster afterwards.
   • Cloud Run egress is a datacenter IP — add cloudrun/secrets/ytdlp-cookies.txt
     (a Netscape-format export from a signed-in browser) if YouTube downloads fail.
   • Meta long-lived tokens expire ~60 days; refresh and re-run this script.
   • Full runbook + caveats: cloudrun/README.md
EOF
