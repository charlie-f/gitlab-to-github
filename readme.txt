GitLab to GitHub Repository Transfer Tool - Usage Instructions
================================================================

OVERVIEW
--------
This tool transfers complete GitLab repositories to GitHub, preserving all history, 
branches, tags, and metadata. It supports both self-hosted GitLab instances and 
GitHub organizations.

PREREQUISITES
-------------
- Python 3.7 or higher
- GitLab personal access token with 'api' and 'read_repository' scopes
- GitHub personal access token with 'repo' scope
- Network access to both GitLab and GitHub instances

BASIC USAGE INSTRUCTIONS
========================

1. INSTALL DEPENDENCIES
   ---------------------
   pip install -r requirements.txt

2. RUN DRY RUN (RECOMMENDED)
   -------------------------
   Before performing the actual transfer, validate your configuration:
   
   python gittransfer.py --dry-run
   
   This will:
   - Test authentication credentials
   - Check repository access permissions
   - Display repository analysis (size, branches, tags)
   - Verify GitHub repository name availability
   - Show transfer summary without making changes

3. PERFORM ACTUAL TRANSFER
   ----------------------
   After successful dry run validation:
   
   python gittransfer.py

4. FOLLOW INTERACTIVE PROMPTS
   --------------------------
   The tool will ask you for:
   - GitLab instance URL (e.g., https://gitlab.company.com)
   - GitLab personal access token (hidden input)
   - GitHub personal access token (hidden input)
   - GitLab project URL or path (e.g., owner/repo)
   - GitHub organization name (optional, leave empty for personal account)
   - New repository name (optional, leave empty to keep same name)

5. CONFIRM AND EXECUTE
   -------------------
   Review the transfer summary and confirm to proceed.
   The tool will automatically:
   - Clone the GitLab repository with full history
   - Create the GitHub repository
   - Push all branches and tags to GitHub
   - Clean up temporary files

TOKEN SETUP
-----------
GitLab Token: Go to GitLab > User Settings > Access Tokens
Required scopes: api, read_repository

GitHub Token: Go to GitHub > Settings > Developer settings > Personal access tokens
Required scopes: repo, admin:org (if using organizations)

WHAT GETS TRANSFERRED
--------------------
✓ Complete commit history
✓ All branches and tags
✓ Repository metadata (name, description)
✓ Repository settings (issues, projects, wiki enabled)

✗ Issues and merge requests (GitLab-specific)
✗ CI/CD configurations
✗ Repository-specific settings and integrations
✗ Wiki content (structure only)

================================================================================

PYTHON VIRTUAL ENVIRONMENT INSTRUCTIONS
========================================

Using a Python virtual environment is recommended to avoid conflicts with system 
packages and ensure clean dependency management.

SETUP VIRTUAL ENVIRONMENT
-------------------------

1. CREATE VIRTUAL ENVIRONMENT
   --------------------------
   Navigate to the project directory:
   cd /path/to/gittransfer
   
   Create virtual environment:
   python3 -m venv venv
   
   This creates a 'venv' directory containing the isolated Python environment.

2. ACTIVATE VIRTUAL ENVIRONMENT
   ----------------------------
   
   On Linux/macOS:
   source venv/bin/activate
   
   On Windows:
   venv\Scripts\activate
   
   You should see (venv) appear in your command prompt, indicating the virtual 
   environment is active.

3. INSTALL DEPENDENCIES IN VIRTUAL ENVIRONMENT
   -------------------------------------------
   With the virtual environment activated:
   pip install -r requirements.txt
   
   This installs all required packages only within the virtual environment.

4. VERIFY INSTALLATION
   -------------------
   Check installed packages:
   pip list
   
   You should see the packages from requirements.txt installed.

USING THE APPLICATION WITH VIRTUAL ENVIRONMENT
----------------------------------------------

1. ACTIVATE VIRTUAL ENVIRONMENT (if not already active)
   --------------------------------------------------
   source venv/bin/activate    # Linux/macOS
   venv\Scripts\activate       # Windows

2. RUN DRY RUN
   -----------
   python gittransfer.py --dry-run

3. RUN ACTUAL TRANSFER
   ------------------
   python gittransfer.py

4. DEACTIVATE VIRTUAL ENVIRONMENT (when finished)
   ----------------------------------------------
   deactivate

VIRTUAL ENVIRONMENT BENEFITS
----------------------------
- Isolated dependencies: Packages don't conflict with system Python
- Clean uninstall: Just delete the venv directory to remove everything
- Reproducible environment: Same dependencies across different machines
- Version control: Can be recreated from requirements.txt on any system

TROUBLESHOOTING VIRTUAL ENVIRONMENT
-----------------------------------
- If 'python3 -m venv' doesn't work, try 'python -m venv' or install venv package
- If activation script not found, check the path to your virtual environment
- If packages not found after activation, ensure virtual environment is activated
- To recreate virtual environment: delete venv directory and repeat setup steps

ALTERNATIVE: USING VIRTUALENV (older Python versions)
----------------------------------------------------
If python3 -m venv doesn't work:

1. Install virtualenv:
   pip install virtualenv

2. Create virtual environment:
   virtualenv venv

3. Activate and use as described above

ALTERNATIVE: USING CONDA
------------------------
If you prefer conda environments:

1. Create conda environment:
   conda create -n gittransfer python=3.9

2. Activate environment:
   conda activate gittransfer

3. Install dependencies:
   pip install -r requirements.txt

4. Use application as normal

5. Deactivate when finished:
   conda deactivate

NOTES
-----
- Always activate the virtual environment before running the application
- The virtual environment needs to be activated each time you open a new terminal
- Virtual environment files (venv directory) should not be committed to version control
- Requirements.txt allows others to recreate the same environment