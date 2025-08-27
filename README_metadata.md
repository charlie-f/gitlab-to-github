# GitLab to GitHub Metadata Transfer Tool

A comprehensive tool for transferring GitLab repository metadata (issues, merge requests, labels, milestones, and comments) to GitHub repositories while preserving original context and timestamps.

## Overview

This tool is designed to complement the main `gittransfer.py` tool by transferring the metadata that can't be moved with just a git repository transfer. It handles:

- **Issues** → GitHub Issues (with all comments, labels, assignees, milestones)
- **Merge Requests** → Exported for reference (GitHub doesn't allow creating closed PRs)
- **Labels** → GitHub Labels (with colors and descriptions)
- **Milestones** → GitHub Milestones (with due dates and states)
- **Comments** → Preserved with original timestamps and author attribution
- **User Mapping** → Maps GitLab users to GitHub users with fallback handling

## Prerequisites

### Required Permissions

**GitLab Token Requirements:**
- `read_api` - Read project metadata
- `read_repository` - Access repository information  
- `read_user` - Read user information for mapping

**GitHub Token Requirements:**
- `repo` - Full repository access (read/write issues, labels, etc.)
- `read:org` - Read organization information (if transferring to org repo)

### Installation

Install required dependencies:

```bash
pip install -r requirements.txt
```

The tool uses the same dependencies as `gittransfer.py`:
- requests
- gitpython  
- python-gitlab
- pygithub
- rich
- click

## Usage

### Basic Transfer

```bash
python gittransfer-metadata.py transfer \
  --gitlab-url https://gitlab.company.com \
  --gitlab-token your_gitlab_token \
  --github-token your_github_token \
  --gitlab-project owner/repo \
  --github-repo owner/repo
```

### Dry Run (Analysis Only)

Always recommended to run first to see what will be transferred:

```bash
python gittransfer-metadata.py transfer \
  --gitlab-url https://gitlab.company.com \
  --gitlab-token your_gitlab_token \
  --github-token your_github_token \
  --gitlab-project owner/repo \
  --github-repo owner/repo \
  --dry-run
```

### Custom Export Directory

```bash
python gittransfer-metadata.py transfer \
  --export-dir my_export_folder \
  # ... other options
```

## Transfer Process

The tool follows a careful, resumable process:

### 1. Validation Phase
- Verifies both repositories exist and are accessible
- Compares repository metadata to ensure they match
- Validates that GitHub repo appears to be a transfer of the GitLab repo
- Checks required permissions on both platforms

### 2. Export Phase
- Extracts all issues with comments, labels, assignees, milestones
- Extracts merge requests (closed/merged ones for reference)
- Extracts all labels with colors and descriptions
- Extracts all milestones with due dates and states
- Collects all unique users involved
- Saves everything to local JSON files

### 3. User Mapping Phase
- Creates `user_mapping.json` file with all GitLab users found
- **Manual step**: Edit this file to map GitLab users to GitHub users
- Tool will use fallback names if GitHub mappings aren't provided

### 4. Import Phase
- Creates labels in GitHub (skips existing ones)
- Creates milestones in GitHub (skips existing ones)  
- Creates issues in GitHub with all original metadata preserved
- Adds comments to issues with original timestamps and authors
- Applies labels and milestones to issues
- Closes issues that were closed in GitLab

## User Mapping

The tool creates a `user_mapping.json` file that looks like:

```json
{
  "gitlab_user": {
    "gitlab_id": 123,
    "gitlab_username": "gitlab_user",
    "fallback_name": "GitLab User Name",
    "email": "user@example.com",
    "github_username": "",    // Edit this
    "github_id": null         // Auto-resolved
  }
}
```

**To set up user mapping:**

1. Run the transfer once to generate the mapping file
2. Edit `user_mapping.json` and fill in the `github_username` fields
3. Run the transfer again to complete the import with proper user attribution

## Data Preservation

### Original Metadata
- All GitLab URLs are preserved in issue descriptions
- Original creation timestamps are noted
- Original author information is maintained
- Comment threads are preserved with proper attribution

### GitHub Integration
- Issues are created with proper labels and milestones
- Comments maintain original timestamps in their content
- GitHub users are @mentioned when mappings are available
- Issues are closed if they were closed in GitLab

### What's Not Transferred
- **Open Merge Requests** (GitHub doesn't allow creating open PRs retroactively)
- **Wiki pages** (different structure between platforms)
- **CI/CD pipelines** (platform-specific)
- **File attachments** (API limitations)

## Rate Limiting

The tool includes comprehensive rate limiting protection:

- Monitors GitHub API rate limits automatically
- Waits when rate limits are approached
- Implements exponential backoff for retries
- Preserves rate limit buffer for other operations

Typical transfer rates:
- **Small projects** (< 100 issues): 5-10 minutes
- **Medium projects** (100-500 issues): 15-30 minutes  
- **Large projects** (> 500 issues): 1+ hours

## Resume Capability

The tool supports resuming interrupted transfers:

1. Export data is saved locally before import begins
2. If import fails partway through, you can re-run the same command
3. Already-created items are skipped automatically
4. Progress is tracked and displayed

## Error Handling

### Common Issues

**GitLab Authentication Errors:**
```
❌ GitLab authentication failed: 401 Unauthorized
```
- Check your GitLab token has required permissions
- Verify the GitLab URL is correct
- Ensure token isn't expired

**GitHub Repository Not Found:**
```  
❌ Failed to access GitHub repository: 404 Not Found
```
- Verify the repository exists and is accessible
- Check your GitHub token has repo permissions
- Ensure repository name format is `owner/repo`

**Rate Limiting:**
```
⚠️ GitHub rate limit low (15 requests remaining)  
🕐 Rate limit exceeded. Waiting 3600 seconds...
```
- The tool will automatically wait and retry
- Consider running during off-peak hours for large transfers

### Rollback Options

If something goes wrong during import:

1. **Delete created items manually** via GitHub web interface
2. **Use GitHub API** to bulk delete (advanced users)
3. **Re-run with corrected settings** (tool skips existing items)

## File Structure

After running the tool, your export directory contains:

```
metadata_export/
├── metadata_export.json      # Main export data
├── user_mapping.json         # User mappings (edit this!)
├── export_summary.txt        # Export summary report
└── import_summary.txt        # Import results (after import)
```

## Advanced Usage

### Programmatic Usage

```python
from gittransfer_metadata import MetadataTransferTool

tool = MetadataTransferTool(dry_run=False, export_dir="my_export")
success = tool.transfer_metadata(
    gitlab_url="https://gitlab.com",
    gitlab_token="your_token",
    github_token="your_token", 
    gitlab_project_url="owner/repo",
    github_repo_name="owner/repo"
)
```

### Custom User Mappings

You can pre-create the user mapping file to avoid the manual step:

```python
import json

mappings = {
    "gitlab_user": {
        "gitlab_id": 123,
        "gitlab_username": "gitlab_user", 
        "github_username": "github_user",
        "fallback_name": "User Name"
    }
}

with open("metadata_export/user_mapping.json", "w") as f:
    json.dump(mappings, f, indent=2)
```

## Best Practices

### Before Transfer
1. **Always run dry-run first** to validate setup
2. **Verify repository compatibility** (same codebase)
3. **Check available API rate limits** on both platforms
4. **Plan for user mapping** - collect GitHub usernames in advance

### During Transfer  
1. **Monitor progress** - tool provides detailed logging
2. **Don't interrupt** - let the tool complete or use resume capability
3. **Check rate limits** - transfers can take time for large projects

### After Transfer
1. **Verify results** - check imported issues, labels, milestones
2. **Test issue links** - ensure GitLab references still work
3. **Update documentation** - note the transfer for team members
4. **Archive export data** - keep for records/rollback if needed

## Troubleshooting

### Permission Issues

If you get permission errors:

1. **GitLab**: Ensure token has `read_api`, `read_repository`, `read_user` scopes
2. **GitHub**: Ensure token has full `repo` scope
3. **Organization repos**: Ensure token has appropriate org permissions

### Repository Validation Failures

If repository validation fails:

1. **Check names match** - repositories should have similar names
2. **Verify it's a transfer** - GitHub repo should have commits
3. **Manual override** - use `--force` flag (if implemented) for edge cases

### Large Dataset Issues

For very large projects:

1. **Increase timeout settings** in the code if needed
2. **Run during off-peak hours** to avoid rate limits
3. **Consider breaking into smaller batches** (modify source if needed)

## Contributing

To extend or modify the tool:

1. **Follow existing patterns** from `gittransfer.py`
2. **Add comprehensive error handling** for new features
3. **Update documentation** and help text
4. **Test with dry-run mode** extensively

## Security Considerations

- **Tokens are handled securely** - not logged or stored permanently
- **Export files may contain sensitive data** - secure your export directory  
- **User mappings reveal associations** - protect user mapping files
- **GitLab URLs are preserved** - ensure original GitLab remains accessible

## Limitations

- **No attachment transfer** - file attachments in issues/comments aren't moved
- **No PR creation** - closed merge requests are exported for reference only
- **No advanced formatting** - some GitLab-specific markdown may not render perfectly
- **No real-time sync** - this is a one-time transfer tool

## License

Same license as the main gittransfer project.