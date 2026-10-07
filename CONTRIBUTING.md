# Contributing

This project follows the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/#summary) specification. Commit messages
are used to automatically calculate version bumps and build the changelog.

---
## Commit Format

```
<type>(<scope>): <short summary>

[optional body]

[optional footer(s)]
```

* scope: (Optional) The module or feature area affected (e.g., auth, api).
* description: A short, imperative-mood description of the change.


## Allowed Commit Types

* feat:     A new feature for the user
* fix:      A bug fix
* refactor: Code changes that neither fix a bug nor add a feature
* docs:     Documentation changes only
* tests:    Adding missing tests or correcting existing tests
* chore:    Maintenance tasks, configuration updates, or tooling changes
* build:    Changes that affect the build system or external dependencies


## Examples

Standard Feature Commit:
  git commit -m "feat(api): add endpoint for user profiles"

Bug Fix Commit:
  git commit -m "fix(auth): correct token expiration logic"

Breaking Changes:
  git commit -m "feat(api)!: re-structure response payload for v2"

---

## Releasing a New Version

This project uses [Commitizen](https://commitizen-tools.github.io/commitizen/) to automate versioning, changelog generation, and git tagging based on conventional commits.

### Automated Release (Recommended)

Run `cz bump` with the appropriate increment flag (`major`, `minor`, or `patch`). This command automatically updates `pyproject.toml`, updates `CHANGELOG.md`, creates a release commit, and creates a tagged git release.

```bash
# Bump major version (e.g., 1.0.0 -> 2.0.0)
cz bump --increment MAJOR

# Bump minor version (e.g., 0.1.0 -> 0.2.0)
cz bump --increment MINOR

# Bump patch version (e.g., 0.1.0 -> 0.1.1)
cz bump --increment PATCH
```
