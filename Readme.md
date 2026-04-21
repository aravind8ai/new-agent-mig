# AWS Migration Assistant

This repository now keeps a single canonical deployment stack:

- `migration_assistant_final` (main stack)

It includes all required configuration and code for:

- Lambda tools deployment (`infrastructure/create_tools_lambda.py`)
- ECS Fargate infrastructure deployment (`infrastructure/provision.py`)
- App build and rollout (`deploy.sh`)

## Main Deployment Path

Use only `migration_assistant_final` for deployment.

```bash
cd migration_assistant_final
python infrastructure/create_tools_lambda.py
python infrastructure/provision.py
./deploy.sh
```

## Notes

- Frontend code is in `migration_assistant_final/frontend`.
- Backend agent code is in `migration_assistant_final/backend`.
- Infrastructure scripts are in `migration_assistant_final/infrastructure`.
