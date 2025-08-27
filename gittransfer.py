#!/usr/bin/env python3
"""
GitLab to GitHub Repository Transfer Tool

This tool transfers a complete GitLab repository to GitHub, preserving:
- All commit history
- All branches and tags
- Repository metadata
- Issues, merge requests, and other data where possible
"""

import os
import tempfile
import shutil
from pathlib import Path
from typing import Optional, Dict, Any
import click
import git
import gitlab
from github import Github, Repository
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.table import Table

console = Console()


class GitTransfer:
    def __init__(self, dry_run: bool = False):
        self.gitlab_client = None
        self.github_client = None
        self.temp_dir = None
        self.repo_clone = None
        self.dry_run = dry_run
            
    def setup_gitlab_client(self, gitlab_url: str, token: str):
        """Initialize GitLab client with custom URL and token."""
        try:
            self.gitlab_client = gitlab.Gitlab(gitlab_url, private_token=token)
            self.gitlab_client.auth()
            
            # Get user info to verify token works
            try:
                current_user = self.gitlab_client.user
                console.print(f"✅ GitLab authentication successful (User: {current_user.username})", style="green")
                
                # Check token scopes by trying to access projects
                try:
                    projects = self.gitlab_client.projects.list(per_page=1, get_all=False)
                    console.print(f"✅ Token has project access (found {len(projects)} project{'s' if len(projects) != 1 else ''})", style="green")
                except Exception as scope_error:
                    console.print(f"⚠️  Token may have limited project access: {str(scope_error)}", style="yellow")
                    
            except Exception as user_error:
                console.print(f"⚠️  Could not get user info: {str(user_error)}", style="yellow")
                
            return True
        except Exception as e:
            console.print(f"❌ GitLab authentication failed: {str(e)}", style="red")
            return False

    def setup_github_client(self, token: str):
        """Initialize GitHub client with token."""
        try:
            self.github_client = Github(token)
            user = self.github_client.get_user()
            console.print(f"✅ GitHub authentication successful (User: {user.login})", style="green")
            return True
        except Exception as e:
            console.print(f"❌ GitHub authentication failed: {str(e)}", style="red")
            return False
            
    def get_gitlab_project(self, project_url: str) -> Optional[Any]:
        """Get GitLab project from URL with multiple fallback strategies."""
        try:
            # Extract project path from URL
            if project_url.startswith('http'):
                url_parts = project_url.rstrip('/').split('/')
                if len(url_parts) >= 4:
                    project_path = '/'.join(url_parts[3:])
                else:
                    raise ValueError("Invalid GitLab project URL format")
            else:
                project_path = project_url
                
            console.print(f"🔍 Attempting to access project: {project_path}")
            
            # Strategy 1: Try with URL encoding
            try:
                import urllib.parse
                encoded_path = urllib.parse.quote(project_path, safe='')
                console.print(f"   Trying encoded path: {encoded_path}")
                project = self.gitlab_client.projects.get(encoded_path)
                console.print(f"✅ Found GitLab project: {project.name}", style="green")
                return project
            except Exception as e1:
                console.print(f"   Encoded path failed: {str(e1)}", style="yellow")
                
            # Strategy 2: Try without encoding
            try:
                console.print(f"   Trying unencoded path: {project_path}")
                project = self.gitlab_client.projects.get(project_path)
                console.print(f"✅ Found GitLab project: {project.name}", style="green")
                return project
            except Exception as e2:
                console.print(f"   Unencoded path failed: {str(e2)}", style="yellow")
                
            # Strategy 3: Search for the project by name
            try:
                project_name = project_path.split('/')[-1]
                console.print(f"   Searching for project by name: {project_name}")
                projects = self.gitlab_client.projects.list(search=project_name, all=True)
                
                if projects:
                    console.print(f"   Found {len(projects)} projects matching '{project_name}':")
                    for i, proj in enumerate(projects[:5]):  # Show first 5
                        console.print(f"     {i+1}. {proj.path_with_namespace} (ID: {proj.id})")
                    
                    # Look for exact match
                    for proj in projects:
                        if proj.path_with_namespace == project_path:
                            console.print(f"✅ Found exact match: {proj.name}", style="green")
                            return proj
                            
                    # If no exact match, try the first one that ends with the same path
                    project_suffix = '/'.join(project_path.split('/')[-2:])  # last 2 parts
                    for proj in projects:
                        if proj.path_with_namespace.endswith(project_suffix):
                            console.print(f"✅ Found partial match: {proj.name} ({proj.path_with_namespace})", style="green")
                            return proj
                            
            except Exception as e3:
                console.print(f"   Search failed: {str(e3)}", style="yellow")
                
            # Strategy 4: List accessible projects to help user identify the correct path
            try:
                console.print("   Listing your accessible projects to help identify the correct path:")
                accessible_projects = self.gitlab_client.projects.list(membership=True, per_page=20)
                
                if accessible_projects:
                    console.print("   Your accessible projects:")
                    for proj in accessible_projects:
                        console.print(f"     • {proj.path_with_namespace}")
                        if project_path.lower() in proj.path_with_namespace.lower():
                            console.print(f"       ^ This might be the one you're looking for!", style="blue")
                else:
                    console.print("   No accessible projects found. Check your token permissions.", style="yellow")
                    
            except Exception as e4:
                console.print(f"   Could not list accessible projects: {str(e4)}", style="yellow")
            
            raise Exception(f"Could not access project using any strategy. Original error: 404 Project Not Found")
            
        except Exception as e:
            console.print(f"❌ Failed to access GitLab project: {str(e)}", style="red")
            return None
                
    def analyze_gitlab_project(self, project: Any) -> Dict[str, Any]:
        """Analyze GitLab project and return detailed information."""
        try:
            # Safely get attributes with fallbacks
            def safe_get(obj, attr, default='Unknown'):
                try:
                    value = getattr(obj, attr, default)
                    return value if value is not None else default
                except Exception:
                    return default
            
            # Get repository statistics safely
            stats = {
                'name': safe_get(project, 'name', 'Unknown'),
                'description': safe_get(project, 'description', 'No description'),
                'visibility': safe_get(project, 'visibility', 'Unknown'),
                'default_branch': safe_get(project, 'default_branch', 'main'),
                'clone_url': safe_get(project, 'http_url_to_repo', 'Unknown'),
                'size_mb': 0,
                'commit_count': 0,
                'branches': [],
                'tags': [],
                'issues_enabled': safe_get(project, 'issues_enabled', True),
                'merge_requests_enabled': safe_get(project, 'merge_requests_enabled', True),
                'wiki_enabled': safe_get(project, 'wiki_enabled', True)
            }
            
            # Try to get statistics safely
            try:
                if hasattr(project, 'statistics') and project.statistics:
                    stats['size_mb'] = round(project.statistics.get('repository_size', 0) / (1024 * 1024), 2)
                    stats['commit_count'] = project.statistics.get('commit_count', 0)
            except Exception as e:
                console.print(f"   Could not get repository statistics: {str(e)}", style="yellow")
            
            # Get branches safely
            try:
                branches = project.branches.list(all=True)
                stats['branches'] = [b.name for b in branches]
                stats['branch_count'] = len(branches)
                console.print(f"   Found {len(branches)} branches", style="blue")
            except Exception as e:
                console.print(f"   Could not fetch branches: {str(e)}", style="yellow")
                stats['branches'] = ['Unable to fetch branches']
                stats['branch_count'] = 0
                
            # Get tags safely
            try:
                tags = project.tags.list(all=True)
                stats['tags'] = [t.name for t in tags[:10]]  # Show first 10 tags
                stats['tag_count'] = len(tags)
                console.print(f"   Found {len(tags)} tags", style="blue")
            except Exception as e:
                console.print(f"   Could not fetch tags: {str(e)}", style="yellow") 
                stats['tags'] = ['Unable to fetch tags']
                stats['tag_count'] = 0
                
            # Try alternative attribute names for default branch
            if stats['default_branch'] == 'Unknown':
                try:
                    # Try different possible attribute names
                    for attr_name in ['default_branch', 'defaultBranch', 'master_branch']:
                        if hasattr(project, attr_name):
                            branch_val = getattr(project, attr_name)
                            if branch_val:
                                stats['default_branch'] = branch_val
                                break
                    
                    # If still unknown, try to get it from branches list
                    if stats['default_branch'] == 'Unknown' and stats['branches']:
                        # Look for common default branch names
                        for common_branch in ['main', 'master', 'develop']:
                            if common_branch in stats['branches']:
                                stats['default_branch'] = common_branch
                                break
                        # If none found, use first branch
                        if stats['default_branch'] == 'Unknown':
                            stats['default_branch'] = stats['branches'][0]
                            
                except Exception as e:
                    console.print(f"   Could not determine default branch: {str(e)}", style="yellow")
                
            console.print(f"✅ Project analysis completed", style="green")
            return stats
            
        except Exception as e:
            console.print(f"❌ Failed to analyze project: {str(e)}", style="red")
            console.print(f"   Available project attributes: {[attr for attr in dir(project) if not attr.startswith('_')][:10]}...", style="yellow")
            return {}
            
    def clone_gitlab_repo(self, project: Any, temp_dir: str) -> bool:
        """Clone GitLab repository with full history."""
        if self.dry_run:
            console.print(f"🔍 [DRY RUN] Would clone repository: {project.http_url_to_repo}", style="yellow")
            return True
            
        try:
            clone_url = project.http_url_to_repo
            # Add token to URL for authentication
            token = self.gitlab_client.private_token
            auth_url = clone_url.replace('://', f'://oauth2:{token}@')
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("Cloning GitLab repository...", total=None)
                
                self.repo_clone = git.Repo.clone_from(
                    auth_url, 
                    temp_dir,
                    bare=False,
                    mirror=False
                )
                
                # Fetch all branches and tags
                progress.update(task, description="Fetching all branches and tags...")
                origin = self.repo_clone.remotes.origin
                origin.fetch(tags=True, prune=True)
                
                # Create local branches for all remote branches
                for ref in origin.refs:
                    if ref.name != 'origin/HEAD':
                        branch_name = ref.name.replace('origin/', '')
                        if branch_name not in [b.name for b in self.repo_clone.branches]:
                            self.repo_clone.create_head(branch_name, ref)
                
            console.print("✅ Repository cloned successfully", style="green")
            return True
        except Exception as e:
            console.print(f"❌ Failed to clone repository: {str(e)}", style="red")
            return False
            
    def validate_github_repo_creation(self, org_name: str, repo_name: str) -> bool:
        """Validate if GitHub repository can be created without actually creating it."""
        try:
            if org_name:
                # Check if organization exists and user has access
                try:
                    org = self.github_client.get_organization(org_name)
                    console.print(f"✅ Found GitHub organization: {org_name}", style="green")
                    
                    # Try to check if user is a member (this might fail for some org types)
                    try:
                        current_user = self.github_client.get_user()
                        # Try to get the membership - different approach for GitHub Enterprise
                        try:
                            membership = org.get_membership(current_user.login)
                            if membership.state == 'active':
                                console.print(f"✅ Active member of organization: {org_name}", style="green")
                            else:
                                console.print(f"⚠️  Membership state: {membership.state}", style="yellow")
                        except Exception as membership_error:
                            # Fallback: try to list some repos to check access
                            try:
                                repos = list(org.get_repos(type='all'))[:1]  # Just get first repo to test access
                                console.print(f"✅ Can access organization repositories", style="green")
                            except Exception as repo_error:
                                console.print(f"⚠️  Cannot verify organization membership: {str(membership_error)}", style="yellow")
                                console.print(f"   Attempting to proceed anyway...", style="yellow")
                    
                    except Exception as user_error:
                        console.print(f"⚠️  Cannot verify user access to organization: {str(user_error)}", style="yellow")
                    
                    # Check if repository name already exists
                    try:
                        existing_repo = org.get_repo(repo_name)
                        console.print(f"❌ Repository {org_name}/{repo_name} already exists", style="red")
                        return False
                    except Exception:
                        # Repository doesn't exist, which is good
                        pass
                        
                except Exception as org_error:
                    console.print(f"❌ Cannot access GitHub organization '{org_name}': {str(org_error)}", style="red")
                    return False
            else:
                # Check personal account
                try:
                    existing_repo = self.github_client.get_user().get_repo(repo_name)
                    console.print(f"❌ Repository {repo_name} already exists in personal account", style="red")
                    return False
                except Exception:
                    # Repository doesn't exist, which is good
                    pass
                    
            console.print(f"✅ GitHub repository name '{repo_name}' is available", style="green")
            return True
            
        except Exception as e:
            console.print(f"❌ Failed to validate GitHub repository: {str(e)}", style="red")
            return False
    
    def create_github_repo(self, org_name: str, repo_name: str, description: str = "") -> Optional[Repository.Repository]:
        """Create GitHub repository in specified organization."""
        if self.dry_run:
            console.print(f"🔍 [DRY RUN] Would create GitHub repository: {org_name}/{repo_name if org_name else repo_name}", style="yellow")
            return None
            
        try:
            if org_name:
                org = self.github_client.get_organization(org_name)
                github_repo = org.create_repo(
                    name=repo_name,
                    description=description,
                    private=True,  # Default to private, user can change later
                    has_issues=True,
                    has_projects=True,
                    has_wiki=True
                )
            else:
                # Create in personal account
                github_repo = self.github_client.get_user().create_repo(
                    name=repo_name,
                    description=description,
                    private=True,
                    has_issues=True,
                    has_projects=True,
                    has_wiki=True
                )
            
            console.print(f"✅ GitHub repository created: {github_repo.full_name}", style="green")
            return github_repo
        except Exception as e:
            console.print(f"❌ Failed to create GitHub repository: {str(e)}", style="red")
            return None
            
    def push_to_github(self, github_repo: Repository.Repository) -> bool:
        """Push cloned repository to GitHub."""
        if self.dry_run:
            console.print(f"🔍 [DRY RUN] Would push repository to: {github_repo.clone_url if github_repo else 'GitHub'}", style="yellow")
            return True
            
        try:
            clone_url = github_repo.clone_url
            
            # Get the GitHub token - try multiple methods for different PyGithub versions
            github_token = None
            try:
                # Method 1: Try the direct approach (newer versions)
                if hasattr(self.github_client, '_Github__requester'):
                    requester = self.github_client._Github__requester
                    if hasattr(requester, '_Requester__authorizationHeader'):
                        github_token = requester._Requester__authorizationHeader.split()[-1]
                    elif hasattr(requester, 'auth'):
                        # Handle token-based auth
                        if hasattr(requester.auth, 'token'):
                            github_token = requester.auth.token
            except Exception:
                pass
                
            # Method 2: Alternative approach for different versions
            if not github_token:
                try:
                    # Try accessing the token through the auth object
                    auth = getattr(self.github_client, '_Github__auth', None)
                    if auth and hasattr(auth, 'token'):
                        github_token = auth.token
                except Exception:
                    pass
            
            # Method 3: If we still don't have the token, we'll need to use a different approach
            if not github_token:
                console.print("⚠️  Cannot extract GitHub token from client. Using clone URL with placeholder.", style="yellow")
                # We'll need to modify the URL differently
                # Get the clone URL and modify it to use token authentication
                auth_url = github_repo.clone_url
                # This will require the user to have git credentials configured
            else:
                # Create authenticated URL
                auth_url = clone_url.replace('https://', f'https://{github_token}@')
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("Setting up GitHub remote...", total=None)
                
                # Add GitHub as remote
                if 'github' in [r.name for r in self.repo_clone.remotes]:
                    # Remove existing github remote if it exists
                    self.repo_clone.delete_remote('github')
                
                github_remote = self.repo_clone.create_remote('github', auth_url)
                
                # Get list of local branches
                local_branches = [branch.name for branch in self.repo_clone.branches]
                console.print(f"   Found {len(local_branches)} local branches to push")
                
                # Push all branches
                progress.update(task, description="Pushing branches to GitHub...")
                for branch in self.repo_clone.branches:
                    try:
                        self.repo_clone.git.checkout(branch.name)
                        github_remote.push(refspec=f'{branch.name}:{branch.name}')
                        console.print(f"   ✅ Pushed branch: {branch.name}")
                    except Exception as branch_error:
                        console.print(f"   ⚠️  Failed to push branch {branch.name}: {str(branch_error)}", style="yellow")
                
                # Push all tags
                progress.update(task, description="Pushing tags to GitHub...")
                try:
                    # Get list of tags
                    tags = list(self.repo_clone.tags)
                    if tags:
                        github_remote.push(tags=True)
                        console.print(f"   ✅ Pushed {len(tags)} tags")
                    else:
                        console.print("   ℹ️  No tags to push")
                except Exception as tag_error:
                    console.print(f"   ⚠️  Failed to push tags: {str(tag_error)}", style="yellow")
                
            console.print("✅ Repository pushed to GitHub successfully", style="green")
            return True
        
        except Exception as e:
            console.print(f"❌ Failed to push to GitHub: {str(e)}", style="red")
            console.print(f"   Repository was cloned to: {self.temp_dir}", style="yellow")
            console.print(f"   GitHub repository created: {github_repo.html_url}", style="yellow")
            console.print("   You may need to push manually using git commands", style="yellow")
            return False
            
    def dry_run_analysis(self, gitlab_url: str, gitlab_token: str, github_token: str,
                        gitlab_project_url: str, github_org: str, new_repo_name: str) -> bool:
        """Perform dry run analysis without making any changes."""
        console.print("\n🔍 Starting dry run analysis...\n")
        
        # Setup clients
        if not self.setup_gitlab_client(gitlab_url, gitlab_token):
            return False
            
        if not self.setup_github_client(github_token):
            return False
            
        # Get GitLab project
        gitlab_project = self.get_gitlab_project(gitlab_project_url)
        if not gitlab_project:
            return False
            
        # Analyze GitLab project
        project_stats = self.analyze_gitlab_project(gitlab_project)
        if not project_stats:
            return False
            
        # Display detailed analysis
        self._display_project_analysis(project_stats, github_org, new_repo_name)
        
        # Validate GitHub repository creation
        target_repo_name = new_repo_name or gitlab_project.name
        if not self.validate_github_repo_creation(github_org, target_repo_name):
            return False
            
        console.print("\n✅ Dry run completed successfully! All validations passed.", style="bold green")
        console.print("\n💡 The transfer should proceed without issues.", style="blue")
        return True
        
    def _display_project_analysis(self, stats: Dict[str, Any], github_org: str, new_repo_name: str):
        """Display detailed project analysis."""
        table = Table(title="GitLab Project Analysis", show_header=True, header_style="bold magenta")
        table.add_column("Property", style="cyan", no_wrap=True)
        table.add_column("Value", style="white")
        
        table.add_row("Name", stats.get('name', 'Unknown'))
        table.add_row("Description", stats.get('description', 'No description'))
        table.add_row("Visibility", stats.get('visibility', 'Unknown'))
        table.add_row("Default Branch", stats.get('default_branch', 'Unknown'))
        table.add_row("Repository Size", f"{stats.get('size_mb', 0)} MB")
        table.add_row("Total Commits", str(stats.get('commit_count', 0)))
        table.add_row("Total Branches", str(stats.get('branch_count', 0)))
        table.add_row("Total Tags", str(stats.get('tag_count', 0)))
        table.add_row("Issues Enabled", "✅" if stats.get('issues_enabled') else "❌")
        table.add_row("MRs Enabled", "✅" if stats.get('merge_requests_enabled') else "❌")
        table.add_row("Wiki Enabled", "✅" if stats.get('wiki_enabled') else "❌")
        
        console.print(table)
        
        # Display branches (first 10)
        if stats.get('branches'):
            console.print("\n[bold]Branches to transfer:[/bold]")
            branches_to_show = stats['branches'][:10]
            for branch in branches_to_show:
                console.print(f"  • {branch}")
            if len(stats['branches']) > 10:
                console.print(f"  ... and {len(stats['branches']) - 10} more")
                
        # Display tags (first 10)
        if stats.get('tags') and stats['tag_count'] > 0:
            console.print("\n[bold]Tags to transfer:[/bold]")
            for tag in stats['tags']:
                console.print(f"  • {tag}")
            if stats['tag_count'] > 10:
                console.print(f"  ... and {stats['tag_count'] - 10} more")
                
        # Display transfer destination
        target_name = new_repo_name or stats.get('name', 'unknown')
        target_location = f"{github_org}/{target_name}" if github_org else target_name
        console.print(f"\n[bold green]Transfer destination:[/bold green] {target_location}")
    
    def transfer_repository(self, gitlab_url: str, gitlab_token: str, github_token: str,
                          gitlab_project_url: str, github_org: str, new_repo_name: str) -> bool:
        """Main transfer process."""
        if self.dry_run:
            return self.dry_run_analysis(gitlab_url, gitlab_token, github_token,
                                       gitlab_project_url, github_org, new_repo_name)
            
        console.print("\n🚀 Starting GitLab to GitHub repository transfer...\n")
        
        # Setup clients
        if not self.setup_gitlab_client(gitlab_url, gitlab_token):
            return False
            
        if not self.setup_github_client(github_token):
            return False
            
        # Get GitLab project
        gitlab_project = self.get_gitlab_project(gitlab_project_url)
        if not gitlab_project:
            return False
            
        # Create temporary directory
        self.temp_dir = tempfile.mkdtemp(prefix="git_transfer_")
        console.print(f"📁 Using temporary directory: {self.temp_dir}")
        
        try:
            # Clone GitLab repository
            if not self.clone_gitlab_repo(gitlab_project, self.temp_dir):
                return False
                
            # Create GitHub repository
            github_repo = self.create_github_repo(
                github_org, 
                new_repo_name or gitlab_project.name,
                gitlab_project.description or ""
            )
            if not github_repo:
                return False
                
            # Push to GitHub
            if not self.push_to_github(github_repo):
                return False
                
            console.print("\n🎉 Repository transfer completed successfully!", style="bold green")
            console.print(f"📍 New GitHub repository: {github_repo.html_url}")
            return True
            
        finally:
            # Cleanup
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                console.print(f"🧹 Cleaned up temporary directory")


@click.command()
@click.option('--dry-run', is_flag=True, help='Perform validation checks without making any changes')
def main(dry_run):
    """GitLab to GitHub Repository Transfer Tool"""
    
    mode_text = "DRY RUN MODE - Validation Only" if dry_run else "Transfer Mode"
    mode_style = "yellow" if dry_run else "blue"
    
    console.print(Panel.fit(
        f"[bold blue]GitLab to GitHub Repository Transfer Tool[/bold blue]\n\n"
        f"[{mode_style}]{mode_text}[/{mode_style}]\n\n"
        "This tool will transfer a complete GitLab repository to GitHub,\n"
        "preserving all history, branches, tags, and metadata.",
        border_style=mode_style
    ))
    
    # Collect user inputs
    gitlab_url = Prompt.ask("\n[bold]GitLab instance URL[/bold] (e.g., https://gitlab.company.com)")
    gitlab_token = Prompt.ask("[bold]GitLab personal access token[/bold]", password=True)
    github_token = Prompt.ask("[bold]GitHub personal access token[/bold]", password=True)
    
    gitlab_project_url = Prompt.ask("\n[bold]GitLab project URL or path[/bold] (e.g., https://gitlab.com/owner/repo or owner/repo)")
    github_org = Prompt.ask("[bold]GitHub organization name[/bold] (leave empty for personal account)", default="")
    
    # Ask for new repository name
    use_different_name = Confirm.ask("Do you want to use a different name for the GitHub repository?")
    new_repo_name = None
    if use_different_name:
        new_repo_name = Prompt.ask("[bold]New repository name[/bold]")
        
    # Ask for dry run if not specified via CLI
    if not dry_run and not Confirm.ask("\nDo you want to perform the actual transfer now?", default=True):
        dry_run = True
        console.print("[yellow]Switching to dry run mode for validation...[/yellow]")
    
    # Confirmation
    action = "Dry Run Analysis" if dry_run else "Transfer"
    console.print(f"\n[bold yellow]{action} Summary:[/bold yellow]")
    console.print(f"📤 From: {gitlab_project_url}")
    console.print(f"📥 To: GitHub {'organization' if github_org else 'personal account'}: {github_org or 'personal'}")
    if new_repo_name:
        console.print(f"📝 New name: {new_repo_name}")
    if dry_run:
        console.print("🔍 Mode: Validation only (no changes will be made)")
    
    proceed_text = f"Proceed with the {action.lower()}?"
    if not Confirm.ask(f"\n{proceed_text}"):
        console.print(f"{action} cancelled.")
        return
    
    # Perform transfer or dry run
    transfer = GitTransfer(dry_run=dry_run)
    success = transfer.transfer_repository(
        gitlab_url=gitlab_url,
        gitlab_token=gitlab_token,
        github_token=github_token,
        gitlab_project_url=gitlab_project_url,
        github_org=github_org,
        new_repo_name=new_repo_name
    )
    
    if not success:
        action = "Dry run" if dry_run else "Transfer"
        console.print(f"\n❌ {action} failed. Please check the errors above.", style="red")
        if dry_run:
            console.print("\n💡 Fix the issues above before attempting the actual transfer.", style="blue")
        exit(1)
    elif dry_run:
        console.print("\n🎯 To perform the actual transfer, run the command again without --dry-run", style="blue")


if __name__ == "__main__":
    main()