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
            console.print("✅ GitLab authentication successful", style="green")
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
        """Get GitLab project from URL."""
        try:
            # Extract project path from URL
            if project_url.startswith('http'):
                # Remove protocol and domain, get path
                path_parts = project_url.split('/')
                project_path = '/'.join(path_parts[-2:])  # owner/repo
            else:
                project_path = project_url
                
            project = self.gitlab_client.projects.get(project_path, lazy=True)
            project.get()  # Force load to check if exists
            console.print(f"✅ Found GitLab project: {project.name}", style="green")
            return project
        except Exception as e:
            console.print(f"❌ Failed to access GitLab project: {str(e)}", style="red")
            return None
            
    def analyze_gitlab_project(self, project: Any) -> Dict[str, Any]:
        """Analyze GitLab project and return detailed information."""
        try:
            # Get repository statistics
            stats = {
                'name': project.name,
                'description': project.description or 'No description',
                'visibility': project.visibility,
                'default_branch': project.default_branch,
                'clone_url': project.http_url_to_repo,
                'size_mb': round(project.statistics.get('repository_size', 0) / (1024 * 1024), 2),
                'commit_count': project.statistics.get('commit_count', 0),
                'branches': [],
                'tags': [],
                'issues_enabled': project.issues_enabled,
                'merge_requests_enabled': project.merge_requests_enabled,
                'wiki_enabled': project.wiki_enabled
            }
            
            # Get branches
            try:
                branches = project.branches.list(all=True)
                stats['branches'] = [b.name for b in branches]
                stats['branch_count'] = len(branches)
            except Exception:
                stats['branches'] = ['Unable to fetch branches']
                stats['branch_count'] = 0
                
            # Get tags
            try:
                tags = project.tags.list(all=True)
                stats['tags'] = [t.name for t in tags[:10]]  # Show first 10 tags
                stats['tag_count'] = len(tags)
            except Exception:
                stats['tags'] = ['Unable to fetch tags']
                stats['tag_count'] = 0
                
            return stats
        except Exception as e:
            console.print(f"❌ Failed to analyze project: {str(e)}", style="red")
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
                org = self.github_client.get_organization(org_name)
                # Check if user has write access to organization
                member = org.get_membership(self.github_client.get_user().login)
                if member.state != 'active':
                    console.print(f"❌ Not an active member of organization: {org_name}", style="red")
                    return False
                    
                # Check if repository name already exists
                try:
                    existing_repo = org.get_repo(repo_name)
                    console.print(f"❌ Repository {org_name}/{repo_name} already exists", style="red")
                    return False
                except:
                    pass  # Repository doesn't exist, which is good
            else:
                # Check personal account
                try:
                    existing_repo = self.github_client.get_user().get_repo(repo_name)
                    console.print(f"❌ Repository {repo_name} already exists in personal account", style="red")
                    return False
                except:
                    pass  # Repository doesn't exist, which is good
                    
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
            # Add token to URL for authentication
            token = self.github_client._Github__requester._Requester__authorizationHeader.split()[-1]
            auth_url = clone_url.replace('://', f'://oauth2:{token}@')
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("Pushing to GitHub...", total=None)
                
                # Add GitHub as remote
                github_remote = self.repo_clone.create_remote('github', auth_url)
                
                # Push all branches
                progress.update(task, description="Pushing all branches...")
                for branch in self.repo_clone.branches:
                    self.repo_clone.git.checkout(branch.name)
                    github_remote.push(refspec=f'{branch.name}:{branch.name}', force=True)
                
                # Push all tags
                progress.update(task, description="Pushing all tags...")
                github_remote.push(tags=True)
                
            console.print("✅ Repository pushed to GitHub successfully", style="green")
            return True
        except Exception as e:
            console.print(f"❌ Failed to push to GitHub: {str(e)}", style="red")
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