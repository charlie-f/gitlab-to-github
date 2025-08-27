# GitLab to GitHub Repository Transfer Tool

A Python application that transfers complete GitLab repositories to GitHub, preserving all history, branches, tags, and metadata.

## Features

- 🔄 **Complete Transfer**: Preserves all commit history, branches, and tags
- 🔐 **Secure Authentication**: Uses personal access tokens for both platforms
- 🏢 **Organization Support**: Transfer to GitHub organizations or personal accounts
- 📝 **Flexible Naming**: Option to rename repository during transfer
- 🌐 **Self-hosted GitLab**: Works with dedicated GitLab instances
- 🎨 **Rich CLI Interface**: Beautiful command-line interface with progress indicators
- 🧹 **Automatic Cleanup**: Cleans up temporary files after transfer

## Requirements

- Python 3.7+
- GitLab personal access token with `api` and `read_repository` scopes
- GitHub personal access token with `repo` scope

## Installation

1. Clone this repository:
```bash
git clone <this-repo>
cd gittransfer
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Make the script executable:
```bash
chmod +x gittransfer.py
```

## Usage

### Basic Usage

Run the transfer tool:

```bash
python gittransfer.py
```

### Dry Run (Recommended)

Before performing the actual transfer, run a dry run to validate your configuration:

```bash
python gittransfer.py --dry-run
```

The dry run will:
- ✅ Validate authentication credentials
- ✅ Check repository access permissions  
- ✅ Analyze repository size, branches, and tags
- ✅ Verify GitHub repository name availability
- ✅ Display detailed transfer summary
- ❌ **Make no actual changes**

### Interactive Options

The tool will prompt you for:

1. **GitLab instance URL** - The full URL of your GitLab instance (e.g., `https://gitlab.company.com`)
2. **GitLab personal access token** - Token with `api` and `read_repository` permissions
3. **GitHub personal access token** - Token with `repo` permissions
4. **GitLab project URL/path** - Either full URL or just `owner/repo` format
5. **GitHub organization** - Target organization (leave empty for personal account)
6. **Repository name** - Option to rename the repository

## Token Setup

### GitLab Personal Access Token

1. Go to GitLab → User Settings → Access Tokens
2. Create a new token with these scopes:
   - `api` - Full API access
   - `read_repository` - Read repository contents

### GitHub Personal Access Token

1. Go to GitHub → Settings → Developer settings → Personal access tokens
2. Generate a new token (classic) with these scopes:
   - `repo` - Full repository access
   - `admin:org` - If transferring to organizations

## What Gets Transferred

✅ **Transferred:**
- Complete commit history
- All branches and tags
- Repository metadata (name, description)
- Repository settings (issues, projects, wiki enabled)

❌ **Not Transferred:**
- Issues and merge requests (GitLab-specific)
- CI/CD configurations
- Repository-specific settings and integrations
- Wiki content (structure only)

## Examples

### Dry Run Example

```bash
$ python gittransfer.py --dry-run

GitLab instance URL: https://gitlab.company.com
GitLab personal access token: ****
GitHub personal access token: ****
GitLab project URL: https://gitlab.company.com/team/awesome-project
GitHub organization: my-github-org
Do you want to use a different name? (y/N): y
New repository name: awesome-project-migrated

Dry Run Analysis Summary:
📤 From: https://gitlab.company.com/team/awesome-project  
📥 To: GitHub organization: my-github-org
📝 New name: awesome-project-migrated
🔍 Mode: Validation only (no changes will be made)

Proceed with the dry run analysis? (y/N): y

🔍 Starting dry run analysis...
✅ GitLab authentication successful
✅ GitHub authentication successful (User: johndoe)
✅ Found GitLab project: awesome-project

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                   GitLab Project Analysis                   ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Name              │ awesome-project                       │
│ Description       │ An awesome project for demonstration  │
│ Visibility        │ private                              │
│ Default Branch    │ main                                 │
│ Repository Size   │ 15.3 MB                              │
│ Total Commits     │ 247                                  │
│ Total Branches    │ 5                                    │
│ Total Tags        │ 12                                   │
│ Issues Enabled    │ ✅                                   │
│ MRs Enabled       │ ✅                                   │
│ Wiki Enabled      │ ✅                                   │
└───────────────────┴──────────────────────────────────────┘

Branches to transfer:
  • main
  • develop  
  • feature/user-auth
  • hotfix/security-patch
  • release/v2.0

Tags to transfer:
  • v1.0.0
  • v1.1.0
  • v1.2.0
  • v1.2.1
  • v2.0.0-beta1
  ... and 7 more

Transfer destination: my-github-org/awesome-project-migrated
✅ GitHub repository name 'awesome-project-migrated' is available

✅ Dry run completed successfully! All validations passed.

💡 The transfer should proceed without issues.

🎯 To perform the actual transfer, run the command again without --dry-run
```

### Actual Transfer Example

```bash
$ python gittransfer.py

# ... (same prompts as dry run) ...

Transfer Summary:
📤 From: https://gitlab.company.com/team/awesome-project  
📥 To: GitHub organization: my-github-org
📝 New name: awesome-project-migrated

Proceed with the transfer? (y/N): y

🚀 Starting GitLab to GitHub repository transfer...
✅ GitLab authentication successful
✅ GitHub authentication successful  
✅ Found GitLab project: awesome-project
📁 Using temporary directory: /tmp/git_transfer_xyz
✅ Repository cloned successfully
✅ GitHub repository created: my-github-org/awesome-project-migrated
✅ Repository pushed to GitHub successfully
🧹 Cleaned up temporary directory

🎉 Repository transfer completed successfully!
📍 New GitHub repository: https://github.com/my-github-org/awesome-project-migrated
```

## Troubleshooting

**Authentication Issues:**
- Ensure tokens have correct permissions
- Check that GitLab URL is accessible
- Verify organization membership for GitHub

**Clone Issues:**  
- Check repository exists and is accessible
- Ensure GitLab token has read access to the repository
- Verify network connectivity to GitLab instance

**Push Issues:**
- Confirm GitHub token has write access
- Check organization permissions
- Ensure repository name doesn't conflict with existing repos

## Security Notes

- Tokens are handled securely and not stored
- Temporary directories are automatically cleaned up
- Repository is cloned locally during transfer (ensure sufficient disk space)
- Private repositories remain private by default

## License

MIT License - see LICENSE file for details.