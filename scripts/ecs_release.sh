#!/usr/bin/env bash
# ECS Express release helper for dobedub-app, following docs/ecs-express-deployment-runbook.md.
#
# Phases (run in order; each re-runnable):
#   ./scripts/ecs_release.sh preflight      # git/aws identity/service state + current env diff (read-only)
#   ./scripts/ecs_release.sh build          # docker buildx linux/amd64 → ECR push (IMAGE_TAG = git short SHA)
#   ./scripts/ecs_release.sh register       # clone primary task definition, swap image, upsert env vars → new revision
#   ./scripts/ecs_release.sh migrate        # one-off --check; runs --if-needed only when exit code is 2
#   ./scripts/ecs_release.sh deploy         # update-service to the new revision, wait for rollout
#   ./scripts/ecs_release.sh all            # preflight → build → register → migrate → deploy (asks before deploy)
#
# Env vars to upsert into the Main container are declared in ENV_UPSERT below.
# Secrets are never printed; env values containing KEY/SECRET/PASSWORD/TOKEN are masked.
set -euo pipefail

export AWS_REGION="${AWS_REGION:-ap-northeast-2}"
export ECS_CLUSTER="${ECS_CLUSTER:-default}"
export ECS_SERVICE="${ECS_SERVICE:-dobedub-app}"
export ECR_REPOSITORY="${ECR_REPOSITORY:-dobedub-app}"
CONTAINER_NAME="${CONTAINER_NAME:-Main}"
WORK_DIR="${WORK_DIR:-/tmp/dobedub-release}"
mkdir -p "$WORK_DIR"

# --- env vars this release needs in the task definition ------------------------------
# name=value ; "!" prefix forces the value even if the var already exists (otherwise add-if-missing).
ENV_UPSERT=(
  "!RUNPOD_SANDBOX_DEPLOY_NAME=${RUNPOD_SANDBOX_DEPLOY_NAME:-dobedub_comfyUI_Sandbox}"
  "RUNPOD_SANDBOX_GPU_FALLBACK_TYPE_IDS=${RUNPOD_SANDBOX_GPU_FALLBACK_TYPE_IDS:-NVIDIA RTX PRO 4500 Blackwell}"
  "RUNPOD_SANDBOX_START_RETRY_COUNT=${RUNPOD_SANDBOX_START_RETRY_COUNT:-1}"
  "RUNPOD_SANDBOX_CREATE_ATTEMPT_DELAY_SECONDS=${RUNPOD_SANDBOX_CREATE_ATTEMPT_DELAY_SECONDS:-2}"
  "RUNPOD_SANDBOX_MIN_VRAM_GB=${RUNPOD_SANDBOX_MIN_VRAM_GB:-24}"
  "RUNPOD_SANDBOX_STOP_WAIT_SECONDS=${RUNPOD_SANDBOX_STOP_WAIT_SECONDS:-60}"
)
# Vars that must exist (as env or secret) for the deployed service to work.
ENV_REQUIRED=(
  PERSISTENCE_BACKEND
  DATABASE_URL
  STORAGE_BACKEND
  S3_BUCKET
  S3_PREFIX
  RUN_SERVER_AUTO_MIGRATE
  RUNPOD_SANDBOX_NETWORK_VOLUME_ID
  RUNPOD_SANDBOX_TEMPLATE_ID
  RUNPOD_SANDBOX_GPU_TYPE_ID
  RUNPOD_SANDBOX_POD_API_KEY
)

log() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m!! %s\033[0m\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "$1 is required"; }

aws_ids() {
  export AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
  export ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}"
  export IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"
}

current_td() {
  aws ecs describe-services --cluster "$ECS_CLUSTER" --services "$ECS_SERVICE" --region "$AWS_REGION" \
    --query "services[0].deployments[?status=='PRIMARY'].taskDefinition | [0]" --output text
}

fetch_current_td_json() {
  aws ecs describe-task-definition --task-definition "$(current_td)" --region "$AWS_REGION" \
    --query taskDefinition --output json > "$WORK_DIR/current-task-definition.json"
}

mask() { jq -r 'if (.name|test("KEY|SECRET|PASSWORD|TOKEN")) then "\(.name)=<masked>" else "\(.name)=\(.value)" end'; }

phase_preflight() {
  need aws; need jq; need git; need docker
  log "git"
  git status --short | grep -v '^??' | head -20 || true
  echo "HEAD: $(git rev-parse --short HEAD)  branch: $(git rev-parse --abbrev-ref HEAD)"
  log "aws identity"
  aws sts get-caller-identity --query '{account:Account,arn:Arn}' --output json
  aws_ids
  log "service state"
  aws ecs describe-services --cluster "$ECS_CLUSTER" --services "$ECS_SERVICE" --region "$AWS_REGION" \
    --query 'services[0].{status:status,desired:desiredCount,running:runningCount,taskDefinition:taskDefinition,deployments:deployments[*].{status:status,rollout:rolloutState,taskDefinition:taskDefinition}}' --output json
  fetch_current_td_json
  log "current Main environment (masked)"
  jq -c ".containerDefinitions[] | select(.name==\"$CONTAINER_NAME\") | .environment[]" "$WORK_DIR/current-task-definition.json" | mask | sort
  log "current Main secrets"
  jq -r ".containerDefinitions[] | select(.name==\"$CONTAINER_NAME\") | .secrets[]?.name" "$WORK_DIR/current-task-definition.json" | sort
  log "required vars check"
  local missing=0
  for name in "${ENV_REQUIRED[@]}"; do
    if jq -e --arg n "$name" ".containerDefinitions[] | select(.name==\"$CONTAINER_NAME\") | ((.environment[]?|select(.name==\$n)), (.secrets[]?|select(.name==\$n)))" "$WORK_DIR/current-task-definition.json" >/dev/null; then
      echo "  OK  $name"
    else
      echo "  !!  $name (missing)"; missing=1
    fi
  done
  log "env upsert plan"
  for entry in "${ENV_UPSERT[@]}"; do
    local force=0; [[ "$entry" == !* ]] && { force=1; entry="${entry#!}"; }
    local name="${entry%%=*}" value="${entry#*=}"
    local cur; cur="$(jq -r --arg n "$name" ".containerDefinitions[] | select(.name==\"$CONTAINER_NAME\") | .environment[]? | select(.name==\$n) | .value" "$WORK_DIR/current-task-definition.json")"
    if [[ -z "$cur" ]]; then echo "  ADD    $name=$value"
    elif [[ "$cur" == "$value" ]]; then echo "  KEEP   $name=$value"
    elif [[ $force == 1 ]]; then echo "  SET    $name: '$cur' -> '$value'"
    else echo "  KEEP   $name='$cur' (differs from default '$value'; not forced)"; fi
  done
  [[ $missing == 0 ]] || die "required env/secret missing in the current task definition"
  log "migration files vs alembic head"
  ls backend/app/db/migrations/versions/*.py | tail -3
}

phase_build() {
  need docker; aws_ids
  log "build & push ${ECR_URI}:${IMAGE_TAG} (linux/amd64)"
  aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
  docker buildx build --platform linux/amd64 --push -t "${ECR_URI}:${IMAGE_TAG}" .
  aws ecr describe-images --repository-name "$ECR_REPOSITORY" --image-ids imageTag="$IMAGE_TAG" --region "$AWS_REGION" \
    --query 'imageDetails[0].{tag:imageTags,pushedAt:imagePushedAt,sizeMB:imageSizeInBytes}' --output json
}

phase_register() {
  aws_ids; fetch_current_td_json
  log "register new revision from $(current_td) with image ${ECR_URI}:${IMAGE_TAG}"
  # Build a JSON array of {name,value,force} for jq.
  local upserts="[]"
  for entry in "${ENV_UPSERT[@]}"; do
    local force=false; [[ "$entry" == !* ]] && { force=true; entry="${entry#!}"; }
    upserts="$(jq -c --arg n "${entry%%=*}" --arg v "${entry#*=}" --argjson f "$force" '. + [{name:$n,value:$v,force:$f}]' <<<"$upserts")"
  done
  jq --arg image "${ECR_URI}:${IMAGE_TAG}" --arg c "$CONTAINER_NAME" --argjson ups "$upserts" '
    del(.taskDefinitionArn,.revision,.status,.requiresAttributes,.compatibilities,.registeredAt,.registeredBy,.deregisteredAt)
    | .containerDefinitions |= map(
        if .name == $c then
          .image = $image
          | .environment = (
              (.environment // []) as $env
              | ($ups | map(. as $u
                  | ($env | map(select(.name == $u.name)) | .[0]) as $existing
                  | if $existing == null then {name:$u.name, value:$u.value}
                    elif $u.force then {name:$u.name, value:$u.value}
                    else $existing end)) as $merged
              | ($env | map(select([.name] | inside($ups | map(.name)) | not))) + $merged
              | sort_by(.name)
            )
        else . end)
  ' "$WORK_DIR/current-task-definition.json" > "$WORK_DIR/next-task-definition.json"
  jq '{family,cpu,memory,volumes,main:(.containerDefinitions[]|select(.name=="'"$CONTAINER_NAME"'")|{image,mountPoints,secrets:[.secrets[]?.name]})}' "$WORK_DIR/next-task-definition.json"
  jq -c ".containerDefinitions[] | select(.name==\"$CONTAINER_NAME\") | .environment[]" "$WORK_DIR/next-task-definition.json" | mask | sort
  jq -e ".containerDefinitions[] | select(.name==\"$CONTAINER_NAME\") | .environment[] | select(.name==\"AUTH_TRUST_PROXY_HEADERS\")" "$WORK_DIR/next-task-definition.json" >/dev/null && die "AUTH_TRUST_PROXY_HEADERS must not be present"
  jq -e ".containerDefinitions[] | select(.name==\"$CONTAINER_NAME\") | .environment[] | select(.name==\"RUN_SERVER_AUTO_MIGRATE\" and .value==\"0\")" "$WORK_DIR/next-task-definition.json" >/dev/null || die "RUN_SERVER_AUTO_MIGRATE=0 must be kept"
  export NEW_TASK_DEFINITION="$(aws ecs register-task-definition --region "$AWS_REGION" --cli-input-json "file://$WORK_DIR/next-task-definition.json" --query 'taskDefinition.taskDefinitionArn' --output text)"
  echo "$NEW_TASK_DEFINITION" > "$WORK_DIR/new-task-definition.arn"
  log "registered: $NEW_TASK_DEFINITION"
}

network_config() {
  local task eni
  task="$(aws ecs list-tasks --cluster "$ECS_CLUSTER" --service-name "$ECS_SERVICE" --desired-status RUNNING --region "$AWS_REGION" --query 'taskArns[0]' --output text)"
  eni="$(aws ecs describe-tasks --cluster "$ECS_CLUSTER" --tasks "$task" --region "$AWS_REGION" \
    --query 'tasks[0].attachments[?type==`ElasticNetworkInterface`].details[?name==`networkInterfaceId`].value | [0]' --output text)"
  local subnet sgs
  subnet="$(aws ec2 describe-network-interfaces --network-interface-ids "$eni" --region "$AWS_REGION" --query 'NetworkInterfaces[0].SubnetId' --output text)"
  sgs="$(aws ec2 describe-network-interfaces --network-interface-ids "$eni" --region "$AWS_REGION" --query 'NetworkInterfaces[0].Groups[*].GroupId' --output text | tr '\t' ',')"
  local public
  public="$(aws ecs describe-services --cluster "$ECS_CLUSTER" --services "$ECS_SERVICE" --region "$AWS_REGION" --query 'services[0].networkConfiguration.awsvpcConfiguration.assignPublicIp' --output text)"
  echo "awsvpcConfiguration={subnets=[${subnet}],securityGroups=[${sgs}],assignPublicIp=${public:-DISABLED}}"
}

run_oneoff() {  # $1 = command JSON array
  local td="${NEW_TASK_DEFINITION:-$(cat "$WORK_DIR/new-task-definition.arn")}"
  local net; net="$(network_config)"
  local arn
  arn="$(aws ecs run-task --cluster "$ECS_CLUSTER" --task-definition "$td" --launch-type FARGATE --network-configuration "$net" \
    --overrides "{\"containerOverrides\":[{\"name\":\"$CONTAINER_NAME\",\"command\":$1}]}" --region "$AWS_REGION" --query 'tasks[0].taskArn' --output text)"
  echo "task: $arn" >&2
  aws ecs wait tasks-stopped --cluster "$ECS_CLUSTER" --tasks "$arn" --region "$AWS_REGION"
  aws ecs describe-tasks --cluster "$ECS_CLUSTER" --tasks "$arn" --region "$AWS_REGION" --query 'tasks[0].containers[0].exitCode' --output text
}

phase_migrate() {
  aws_ids
  log "migration gate: --check"
  local code; code="$(run_oneoff '["python3","scripts/upgrade_database.py","--check"]')"
  echo "check exit code: $code"
  case "$code" in
    0) log "no migration required" ;;
    2) log "migration pending → --if-needed"
       local apply; apply="$(run_oneoff '["python3","scripts/upgrade_database.py","--if-needed"]')"
       echo "apply exit code: $apply"
       [[ "$apply" == "0" ]] || die "migration apply failed (exit $apply) — do not deploy" ;;
    *) die "migration check failed (exit $code) — check RDS SG / secret / CA before deploying" ;;
  esac
}

phase_deploy() {
  aws_ids
  local td="${NEW_TASK_DEFINITION:-$(cat "$WORK_DIR/new-task-definition.arn")}"
  log "update-service → $td"
  aws ecs update-service --cluster "$ECS_CLUSTER" --service "$ECS_SERVICE" --task-definition "$td" --region "$AWS_REGION" \
    --query 'service.deployments[*].{status:status,rollout:rolloutState,taskDefinition:taskDefinition,running:runningCount,pending:pendingCount}' --output json
  log "waiting for services-stable (canary bake included)"
  aws ecs wait services-stable --cluster "$ECS_CLUSTER" --services "$ECS_SERVICE" --region "$AWS_REGION"
  aws ecs describe-services --cluster "$ECS_CLUSTER" --services "$ECS_SERVICE" --region "$AWS_REGION" \
    --query 'services[0].deployments[*].{status:status,rollout:rolloutState,taskDefinition:taskDefinition,running:runningCount}' --output json
}

case "${1:-}" in
  preflight) phase_preflight ;;
  build) phase_build ;;
  register) phase_register ;;
  migrate) phase_migrate ;;
  deploy) phase_deploy ;;
  all)
    phase_preflight; phase_build; phase_register; phase_migrate
    read -r -p "Proceed with update-service? [y/N] " yn; [[ "$yn" == y* ]] || die "aborted before deploy"
    phase_deploy ;;
  *) sed -n '2,14p' "$0"; exit 1 ;;
esac
