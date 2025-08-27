GitLab to GitHub Metadata Transfer Tool - Quick Start Guide
==============================================================

WHAT THIS TOOL DOES
-------------------
Transfers GitLab issues, labels, milestones, and comments to GitHub while 
preserving original timestamps, authors, and context. Complements the main 
gittransfer.py tool by moving the metadata that can't be transferred with 
just git repository copying.

WHAT YOU NEED
-------------
1. GitLab personal access token with permissions:
   - read_api (read project metadata)
   - read_repository (access repo info)
   - read_user (read user information)

2. GitHub personal access token with permissions:
   - repo (full repository access)
   - read:org (if transferring to organization repo)

3. Both repositories should already exist (use gittransfer.py first for the code)

QUICK START
-----------

Step 1: Install dependencies (if not already done for gittransfer.py)
    pip install -r requirements.txt

Step 2: Run dry-run analysis first (RECOMMENDED)
    python gittransfer-metadata.py transfer \
        --gitlab-url https://your.gitlab.com \
        --gitlab-token your_gitlab_token \
        --github-token your_github_token \
        --gitlab-project owner/repo-name \
        --github-repo owner/repo-name \
        --dry-run

    This shows you exactly what will be transferred without making changes.

Step 3: Run the actual transfer
    python gittransfer-metadata.py transfer \
        --gitlab-url https://your.gitlab.com \
        --gitlab-token your_gitlab_token \
        --github-token your_github_token \
        --gitlab-project owner/repo-name \
        --github-repo owner/repo-name

Step 4: Handle user mappings (optional but recommended)
    - Tool creates metadata_export/user_mapping.json
    - Edit this file to map GitLab users to GitHub users
    - Re-run the transfer to apply proper user attributions

WHAT GETS TRANSFERRED
--------------------
✓ Issues → GitHub Issues (with all metadata)
✓ Issue comments → GitHub issue comments  
✓ Labels → GitHub Labels (with colors)
✓ Milestones → GitHub Milestones
✓ Original timestamps (preserved in descriptions)
✓ Author information (with user mapping)

✗ Merge Requests → Exported for reference only (GitHub limitation)
✗ Wiki pages → Not supported
✗ File attachments → API limitations
✗ CI/CD pipelines → Platform specific

COMMON SCENARIOS
---------------

For gitlab.com to GitHub:
    python gittransfer-metadata.py transfer \
        --gitlab-url https://gitlab.com \
        --gitlab-token glpat-xxxxxxxxxxxxxxxxxxxx \
        --github-token ghp_xxxxxxxxxxxxxxxxxxxx \
        --gitlab-project mycompany/myproject \
        --github-repo mycompany/myproject

For self-hosted GitLab:
    python gittransfer-metadata.py transfer \
        --gitlab-url https://gitlab.mycompany.com \
        --gitlab-token glpat-xxxxxxxxxxxxxxxxxxxx \
        --github-token ghp_xxxxxxxxxxxxxxxxxxxx \
        --gitlab-project team/project \
        --github-repo mycompany/project

With custom export directory:
    python gittransfer-metadata.py transfer \
        --export-dir my_transfer_data \
        [... other options ...]

TYPICAL WORKFLOW
---------------
1. Transfer your git repository first using gittransfer.py
2. Run metadata transfer with --dry-run to validate
3. Run actual metadata transfer
4. Edit user_mapping.json if you want proper GitHub user attribution
5. Re-run transfer to apply user mappings
6. Verify results in GitHub repository

TIME ESTIMATES
--------------
Small projects (<50 issues): 2-5 minutes
Medium projects (50-200 issues): 10-20 minutes  
Large projects (200+ issues): 30+ minutes
(Times depend on GitHub API rate limits)

FILES CREATED
-------------
metadata_export/
├── metadata_export.json      # All exported data
├── user_mapping.json         # Edit this for user mappings
├── export_summary.txt        # What was exported
└── import_summary.txt        # What was imported

TROUBLESHOOTING
--------------

"GitLab authentication failed":
- Check your token has read_api, read_repository, read_user permissions
- Verify GitLab URL is correct
- Make sure token isn't expired

"GitHub authentication failed":
- Check your token has repo permissions
- For organization repos, ensure you have appropriate access

"Repository not found":
- Verify repository names are exactly right
- Format should be: owner/repo-name
- Make sure you have access to both repositories

"Rate limit exceeded":
- Tool will automatically wait and retry
- Consider running during off-peak hours for large transfers
- GitHub allows 5000 requests per hour for authenticated users

"Repository validation failed":
- Repositories should have similar names
- GitHub repo should already have commits (transfer the code first)
- Make sure GitHub repo is actually a copy of the GitLab repo

USER MAPPING EXPLAINED
---------------------
The tool creates user_mapping.json that looks like:

{
  "gitlab_username": {
    "gitlab_id": 123,
    "gitlab_username": "gitlab_user",  
    "fallback_name": "User Full Name",
    "email": "user@email.com",
    "github_username": "",             ← EDIT THIS
    "github_id": null
  }
}

Fill in the "github_username" fields with actual GitHub usernames.
If you don't, the tool uses fallback names instead.

SAFETY FEATURES
--------------
- Dry-run mode shows exactly what will happen
- All data exported locally before import begins
- Resume capability if transfer gets interrupted  
- Rate limit protection prevents API abuse
- Comprehensive error handling and recovery
- Original GitLab links preserved in all transferred items

ADVANCED OPTIONS
---------------
--export-dir: Specify where to save export files (default: metadata_export)
--dry-run: Analysis only, no changes made
--help: Show all available options

GETTING HELP
-----------
- Run with --help to see all options
- Check the generated summary files for detailed reports
- Look at export files to understand what's being transferred
- All errors are logged with suggestions for resolution

SECURITY NOTES
--------------
- Tokens are never stored permanently
- Export directory may contain sensitive project data
- User mapping file reveals GitLab/GitHub user associations
- Keep export directory secure and clean up when done

That's it! The tool is designed to be straightforward - most users just need 
the basic transfer command with their tokens and repository information.