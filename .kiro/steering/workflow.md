# Workflow Rules

## Git Workflow
- Never commit or push directly to the `main` branch.
- Always create a feature or bugfix branch for changes.
- Push branches and raise PRs for review.

## Testing
- Always run tests (`npm run test:run`) after making changes and before marking a task as complete.
- Fix any test failures before committing.

## Versioning
- Update `custom_components/climate_timer/manifest.json` version when making changes on feature/bugfix branches.
