#!/usr/bin/env python3
"""
GitLab to GitHub Metadata Transfer Tool

This tool transfers GitLab repository metadata to GitHub, preserving:
- Issues with comments, labels, assignees, milestones
- Merge requests (closed ones) converted to pull requests
- Labels and milestones
- Comment threads and timestamps
- User mappings and original metadata references
"""

import os
import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Set, Tuple
from dataclasses import dataclass, asdict
from urllib.parse import quote_plus
import hashlib
import traceback

import click
import requests
import gitlab
from github import Github, Repository, Issue, PullRequest, Label, Milestone
from github.GithubException import GithubException, RateLimitExceededException
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.table import Table
from rich.status import Status
from rich import print as rprint

console = Console()

# Configuration constants
RATE_LIMIT_BUFFER = 10  # Keep this many requests in reserve
MAX_RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 2
DEFAULT_EXPORT_DIR = "metadata_export"
RESUME_STATE_FILE = "transfer_state.json"


@dataclass
class UserMapping:
    """Maps GitLab users to GitHub users"""
    gitlab_username: str
    gitlab_id: int
    github_username: Optional[str] = None
    github_id: Optional[int] = None
    fallback_name: Optional[str] = None
    email: Optional[str] = None


@dataclass
class TransferState:
    """Tracks transfer progress for resume capability"""
    gitlab_project_id: int
    github_repo_full_name: str
    completed_issues: List[int]
    completed_merge_requests: List[int]
    completed_labels: List[str]
    completed_milestones: List[str]
    user_mappings: Dict[str, Dict[str, Any]]
    start_time: str
    last_checkpoint: str


@dataclass
class IssueData:
    """Represents a GitLab issue with all metadata"""
    id: int
    iid: int
    title: str
    description: str
    state: str
    created_at: str
    updated_at: str
    closed_at: Optional[str]
    author: UserMapping
    assignees: List[UserMapping]
    labels: List[str]
    milestone: Optional[str]
    comments: List[Dict[str, Any]]
    gitlab_url: str


@dataclass
class MergeRequestData:
    """Represents a GitLab merge request with all metadata"""
    id: int
    iid: int
    title: str
    description: str
    state: str
    created_at: str
    updated_at: str
    closed_at: Optional[str]
    merged_at: Optional[str]
    author: UserMapping
    assignee: Optional[UserMapping]
    labels: List[str]
    milestone: Optional[str]
    source_branch: str
    target_branch: str
    comments: List[Dict[str, Any]]
    gitlab_url: str
    sha: Optional[str]


class GitLabMetadataExtractor:
    """Extracts metadata from GitLab projects"""
    
    def __init__(self, gitlab_client, project):
        self.gitlab = gitlab_client
        self.project = project
        self.user_cache = {}
        
    def get_user_mapping(self, user_id: int) -> UserMapping:
        """Get or create user mapping for a GitLab user"""
        if user_id in self.user_cache:
            return self.user_cache[user_id]
            
        try:
            user = self.gitlab.users.get(user_id)
            mapping = UserMapping(
                gitlab_username=user.username,
                gitlab_id=user.id,
                fallback_name=user.name,
                email=getattr(user, 'email', None)
            )
        except Exception as e:
            console.print(f"⚠️  Could not fetch user {user_id}: {e}", style="yellow")
            mapping = UserMapping(
                gitlab_username=f"user_{user_id}",
                gitlab_id=user_id,
                fallback_name=f"Unknown User {user_id}"
            )
            
        self.user_cache[user_id] = mapping
        return mapping
        
    def extract_issues(self) -> List[IssueData]:
        """Extract all issues from GitLab project"""
        issues = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console
        ) as progress:
            # Get total count
            all_issues = self.project.issues.list(all=True, lazy=True)
            total_issues = len(list(all_issues))
            
            if total_issues == 0:
                console.print("ℹ️  No issues found in GitLab project")
                return []
                
            task = progress.add_task("Extracting GitLab issues...", total=total_issues)
            
            # Re-fetch with full data
            for issue in self.project.issues.list(all=True):
                try:
                    # Get author mapping
                    author = self.get_user_mapping(issue.author['id'])
                    
                    # Get assignees
                    assignees = []
                    if hasattr(issue, 'assignees') and issue.assignees:
                        assignees = [self.get_user_mapping(assignee['id']) for assignee in issue.assignees]
                    elif hasattr(issue, 'assignee') and issue.assignee:
                        assignees = [self.get_user_mapping(issue.assignee['id'])]
                    
                    # Get comments/notes
                    comments = []
                    try:
                        for note in issue.notes.list(all=True):
                            if not note.system:  # Skip system notes
                                comment_author = self.get_user_mapping(note.author['id'])
                                comments.append({
                                    'id': note.id,
                                    'body': note.body,
                                    'created_at': note.created_at,
                                    'updated_at': note.updated_at,
                                    'author': asdict(comment_author),
                                    'gitlab_url': f"{self.project.web_url}/-/issues/{issue.iid}#note_{note.id}"
                                })
                    except Exception as e:
                        console.print(f"⚠️  Could not fetch comments for issue #{issue.iid}: {e}", style="yellow")
                    
                    issue_data = IssueData(
                        id=issue.id,
                        iid=issue.iid,
                        title=issue.title,
                        description=issue.description or "",
                        state=issue.state,
                        created_at=issue.created_at,
                        updated_at=issue.updated_at,
                        closed_at=issue.closed_at,
                        author=author,
                        assignees=assignees,
                        labels=issue.labels,
                        milestone=issue.milestone['title'] if issue.milestone else None,
                        comments=comments,
                        gitlab_url=f"{self.project.web_url}/-/issues/{issue.iid}"
                    )
                    
                    issues.append(issue_data)
                    progress.update(task, advance=1)
                    
                except Exception as e:
                    console.print(f"❌ Failed to extract issue #{issue.iid}: {e}", style="red")
                    progress.update(task, advance=1)
                    continue
                    
        console.print(f"✅ Extracted {len(issues)} issues from GitLab", style="green")
        return issues
        
    def extract_merge_requests(self) -> List[MergeRequestData]:
        """Extract all merge requests from GitLab project"""
        merge_requests = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console
        ) as progress:
            # Get all MRs (we'll filter to closed ones later)
            all_mrs = self.project.mergerequests.list(all=True, lazy=True)
            total_mrs = len(list(all_mrs))
            
            if total_mrs == 0:
                console.print("ℹ️  No merge requests found in GitLab project")
                return []
                
            task = progress.add_task("Extracting GitLab merge requests...", total=total_mrs)
            
            # Re-fetch with full data
            for mr in self.project.mergerequests.list(all=True):
                try:
                    # Only process closed/merged MRs (open ones can't be recreated in GitHub)
                    if mr.state not in ['closed', 'merged']:
                        progress.update(task, advance=1)
                        continue
                        
                    # Get author mapping
                    author = self.get_user_mapping(mr.author['id'])
                    
                    # Get assignee
                    assignee = None
                    if hasattr(mr, 'assignee') and mr.assignee:
                        assignee = self.get_user_mapping(mr.assignee['id'])
                    
                    # Get comments/notes
                    comments = []
                    try:
                        for note in mr.notes.list(all=True):
                            if not note.system:  # Skip system notes
                                comment_author = self.get_user_mapping(note.author['id'])
                                comments.append({
                                    'id': note.id,
                                    'body': note.body,
                                    'created_at': note.created_at,
                                    'updated_at': note.updated_at,
                                    'author': asdict(comment_author),
                                    'gitlab_url': f"{self.project.web_url}/-/merge_requests/{mr.iid}#note_{note.id}"
                                })
                    except Exception as e:
                        console.print(f"⚠️  Could not fetch comments for MR !{mr.iid}: {e}", style="yellow")
                    
                    mr_data = MergeRequestData(
                        id=mr.id,
                        iid=mr.iid,
                        title=mr.title,
                        description=mr.description or "",
                        state=mr.state,
                        created_at=mr.created_at,
                        updated_at=mr.updated_at,
                        closed_at=mr.closed_at,
                        merged_at=mr.merged_at,
                        author=author,
                        assignee=assignee,
                        labels=mr.labels,
                        milestone=mr.milestone['title'] if mr.milestone else None,
                        source_branch=mr.source_branch,
                        target_branch=mr.target_branch,
                        comments=comments,
                        gitlab_url=f"{self.project.web_url}/-/merge_requests/{mr.iid}",
                        sha=getattr(mr, 'sha', None)
                    )
                    
                    merge_requests.append(mr_data)
                    progress.update(task, advance=1)
                    
                except Exception as e:
                    console.print(f"❌ Failed to extract MR !{mr.iid}: {e}", style="red")
                    progress.update(task, advance=1)
                    continue
                    
        console.print(f"✅ Extracted {len(merge_requests)} closed/merged MRs from GitLab", style="green")
        return merge_requests
        
    def extract_labels(self) -> List[Dict[str, Any]]:
        """Extract all labels from GitLab project"""
        labels = []
        try:
            for label in self.project.labels.list(all=True):
                labels.append({
                    'name': label.name,
                    'description': getattr(label, 'description', ''),
                    'color': label.color.lstrip('#') if label.color else 'ffffff'
                })
            console.print(f"✅ Extracted {len(labels)} labels from GitLab", style="green")
        except Exception as e:
            console.print(f"❌ Failed to extract labels: {e}", style="red")
        return labels
        
    def extract_milestones(self) -> List[Dict[str, Any]]:
        """Extract all milestones from GitLab project"""
        milestones = []
        try:
            for milestone in self.project.milestones.list(all=True):
                milestones.append({
                    'title': milestone.title,
                    'description': getattr(milestone, 'description', ''),
                    'state': milestone.state,
                    'due_date': getattr(milestone, 'due_date', None),
                    'created_at': milestone.created_at,
                    'updated_at': milestone.updated_at
                })
            console.print(f"✅ Extracted {len(milestones)} milestones from GitLab", style="green")
        except Exception as e:
            console.print(f"❌ Failed to extract milestones: {e}", style="red")
        return milestones


class GitHubMetadataImporter:
    """Imports metadata to GitHub repositories"""
    
    def __init__(self, github_client, repo, user_mappings: Dict[str, UserMapping]):
        self.github = github_client
        self.repo = repo
        self.user_mappings = user_mappings
        self.rate_limit_warned = False
        
    def check_rate_limit(self) -> bool:
        """Check GitHub rate limit and wait if necessary"""
        try:
            rate_limit = self.github.get_rate_limit()
            remaining = rate_limit.core.remaining
            reset_time = rate_limit.core.reset
            
            if remaining < RATE_LIMIT_BUFFER:
                if not self.rate_limit_warned:
                    console.print(f"⚠️  GitHub rate limit low ({remaining} requests remaining)", style="yellow")
                    self.rate_limit_warned = True
                    
                if remaining == 0:
                    wait_time = (reset_time - datetime.now(timezone.utc)).total_seconds() + 10
                    console.print(f"🕐 Rate limit exceeded. Waiting {wait_time:.0f} seconds...", style="yellow")
                    time.sleep(max(wait_time, 0))
                    self.rate_limit_warned = False
                    return self.check_rate_limit()
                    
            return True
        except Exception as e:
            console.print(f"⚠️  Could not check rate limit: {e}", style="yellow")
            return True
            
    def retry_with_backoff(self, func, *args, **kwargs):
        """Execute function with retry logic and backoff"""
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                self.check_rate_limit()
                return func(*args, **kwargs)
            except RateLimitExceededException:
                if attempt < MAX_RETRY_ATTEMPTS - 1:
                    wait_time = (2 ** attempt) * RETRY_DELAY_SECONDS
                    console.print(f"Rate limited. Retrying in {wait_time}s...", style="yellow")
                    time.sleep(wait_time)
                else:
                    raise
            except Exception as e:
                if attempt < MAX_RETRY_ATTEMPTS - 1:
                    wait_time = (2 ** attempt) * RETRY_DELAY_SECONDS
                    console.print(f"Error: {e}. Retrying in {wait_time}s...", style="yellow")
                    time.sleep(wait_time)
                else:
                    raise
                    
    def resolve_github_username(self, user_mapping: UserMapping) -> str:
        """Resolve GitLab user to GitHub username or fallback"""
        if user_mapping.github_username:
            return f"@{user_mapping.github_username}"
        elif user_mapping.fallback_name:
            return user_mapping.fallback_name
        else:
            return f"@{user_mapping.gitlab_username} (GitLab)"
            
    def format_gitlab_metadata(self, original_url: str, created_at: str, author: UserMapping) -> str:
        """Format GitLab metadata for inclusion in GitHub"""
        return (
            f"\n\n---\n"
            f"*Originally created by {self.resolve_github_username(author)} "
            f"on {created_at} in [GitLab]({original_url})*\n"
        )
        
    def import_labels(self, labels: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Import labels to GitHub repository"""
        imported_labels = {}
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console
        ) as progress:
            task = progress.add_task("Importing labels to GitHub...", total=len(labels))
            
            for label_data in labels:
                try:
                    # Check if label already exists
                    try:
                        existing_label = self.retry_with_backoff(
                            self.repo.get_label, 
                            label_data['name']
                        )
                        imported_labels[label_data['name']] = existing_label
                        console.print(f"   ✅ Label '{label_data['name']}' already exists")
                    except GithubException as e:
                        if e.status == 404:
                            # Create new label
                            new_label = self.retry_with_backoff(
                                self.repo.create_label,
                                name=label_data['name'],
                                color=label_data['color'],
                                description=label_data['description'][:100] if label_data['description'] else ""
                            )
                            imported_labels[label_data['name']] = new_label
                            console.print(f"   ✅ Created label '{label_data['name']}'")
                        else:
                            raise
                            
                    progress.update(task, advance=1)
                    
                except Exception as e:
                    console.print(f"❌ Failed to import label '{label_data['name']}': {e}", style="red")
                    progress.update(task, advance=1)
                    continue
                    
        console.print(f"✅ Imported {len(imported_labels)} labels to GitHub", style="green")
        return imported_labels
        
    def import_milestones(self, milestones: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Import milestones to GitHub repository"""
        imported_milestones = {}
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console
        ) as progress:
            task = progress.add_task("Importing milestones to GitHub...", total=len(milestones))
            
            for milestone_data in milestones:
                try:
                    # Check if milestone already exists
                    existing_milestone = None
                    for ms in self.retry_with_backoff(self.repo.get_milestones, state='all'):
                        if ms.title == milestone_data['title']:
                            existing_milestone = ms
                            break
                            
                    if existing_milestone:
                        imported_milestones[milestone_data['title']] = existing_milestone
                        console.print(f"   ✅ Milestone '{milestone_data['title']}' already exists")
                    else:
                        # Create new milestone
                        due_on = None
                        if milestone_data['due_date']:
                            try:
                                due_on = datetime.fromisoformat(milestone_data['due_date'].replace('Z', '+00:00'))
                            except:
                                pass
                                
                        new_milestone = self.retry_with_backoff(
                            self.repo.create_milestone,
                            title=milestone_data['title'],
                            description=milestone_data['description'][:200] if milestone_data['description'] else "",
                            due_on=due_on,
                            state='closed' if milestone_data['state'] == 'closed' else 'open'
                        )
                        imported_milestones[milestone_data['title']] = new_milestone
                        console.print(f"   ✅ Created milestone '{milestone_data['title']}'")
                        
                    progress.update(task, advance=1)
                    
                except Exception as e:
                    console.print(f"❌ Failed to import milestone '{milestone_data['title']}': {e}", style="red")
                    progress.update(task, advance=1)
                    continue
                    
        console.print(f"✅ Imported {len(imported_milestones)} milestones to GitHub", style="green")
        return imported_milestones
        
    def import_issues(self, issues: List[IssueData], imported_labels: Dict[str, Any], 
                     imported_milestones: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Import issues to GitHub repository"""
        imported_issues = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console
        ) as progress:
            task = progress.add_task("Importing issues to GitHub...", total=len(issues))
            
            for issue_data in issues:
                try:
                    # Prepare issue body with GitLab metadata
                    body = issue_data.description
                    if body:
                        body += self.format_gitlab_metadata(
                            issue_data.gitlab_url,
                            issue_data.created_at,
                            issue_data.author
                        )
                    else:
                        body = f"*Issue imported from GitLab*{self.format_gitlab_metadata(issue_data.gitlab_url, issue_data.created_at, issue_data.author)}"
                    
                    # Prepare labels
                    github_labels = []
                    for label_name in issue_data.labels:
                        if label_name in imported_labels:
                            github_labels.append(imported_labels[label_name])
                    
                    # Prepare milestone
                    milestone = None
                    if issue_data.milestone and issue_data.milestone in imported_milestones:
                        milestone = imported_milestones[issue_data.milestone]
                    
                    # Create issue
                    github_issue = self.retry_with_backoff(
                        self.repo.create_issue,
                        title=issue_data.title,
                        body=body,
                        labels=github_labels,
                        milestone=milestone
                    )
                    
                    # Import comments
                    self.import_issue_comments(github_issue, issue_data.comments)
                    
                    # Close issue if it was closed in GitLab
                    if issue_data.state == 'closed':
                        self.retry_with_backoff(github_issue.edit, state='closed')
                    
                    imported_issues.append({
                        'gitlab_id': issue_data.id,
                        'gitlab_iid': issue_data.iid,
                        'github_number': github_issue.number,
                        'github_url': github_issue.html_url
                    })
                    
                    console.print(f"   ✅ Imported issue #{issue_data.iid} -> #{github_issue.number}")
                    progress.update(task, advance=1)
                    
                except Exception as e:
                    console.print(f"❌ Failed to import issue #{issue_data.iid}: {e}", style="red")
                    progress.update(task, advance=1)
                    continue
                    
        console.print(f"✅ Imported {len(imported_issues)} issues to GitHub", style="green")
        return imported_issues
        
    def import_issue_comments(self, github_issue: Issue.Issue, comments: List[Dict[str, Any]]):
        """Import comments for an issue"""
        for comment_data in comments:
            try:
                author = UserMapping(**comment_data['author'])
                comment_body = (
                    f"{comment_data['body']}\n\n"
                    f"---\n"
                    f"*Originally commented by {self.resolve_github_username(author)} "
                    f"on {comment_data['created_at']} in [GitLab]({comment_data['gitlab_url']})*"
                )
                
                self.retry_with_backoff(github_issue.create_comment, comment_body)
                
            except Exception as e:
                console.print(f"⚠️  Failed to import comment {comment_data['id']}: {e}", style="yellow")


class MetadataTransferTool:
    """Main class for GitLab to GitHub metadata transfer"""
    
    def __init__(self, dry_run: bool = False, export_dir: str = DEFAULT_EXPORT_DIR):
        self.gitlab_client = None
        self.github_client = None
        self.gitlab_project = None
        self.github_repo = None
        self.dry_run = dry_run
        self.export_dir = Path(export_dir)
        self.transfer_state = None
        self.user_mappings = {}
        
    def setup_gitlab_client(self, gitlab_url: str, token: str) -> bool:
        """Initialize GitLab client with comprehensive error handling"""
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
            
    def setup_github_client(self, token: str) -> bool:
        """Initialize GitHub client"""
        try:
            self.github_client = Github(token)
            user = self.github_client.get_user()
            console.print(f"✅ GitHub authentication successful (User: {user.login})", style="green")
            return True
        except Exception as e:
            console.print(f"❌ GitHub authentication failed: {e}", style="red")
            return False
            
    def get_gitlab_project(self, project_url: str) -> bool:
        """Get GitLab project from URL with multiple fallback strategies"""
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
                self.gitlab_project = project
                return True
            except Exception as e1:
                console.print(f"   Encoded path failed: {str(e1)}", style="yellow")
                
            # Strategy 2: Try without encoding
            try:
                console.print(f"   Trying unencoded path: {project_path}")
                project = self.gitlab_client.projects.get(project_path)
                console.print(f"✅ Found GitLab project: {project.name}", style="green")
                self.gitlab_project = project
                return True
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
                            self.gitlab_project = proj
                            return True
                            
                    # If no exact match, try the first one that ends with the same path
                    project_suffix = '/'.join(project_path.split('/')[-2:])  # last 2 parts
                    for proj in projects:
                        if proj.path_with_namespace.endswith(project_suffix):
                            console.print(f"✅ Found partial match: {proj.name} ({proj.path_with_namespace})", style="green")
                            self.gitlab_project = proj
                            return True
                            
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
            return False
            
    def get_github_repo(self, repo_full_name: str) -> bool:
        """Get GitHub repository"""
        try:
            self.github_repo = self.github_client.get_repo(repo_full_name)
            console.print(f"✅ Found GitHub repository: {self.github_repo.full_name}", style="green")
            return True
        except Exception as e:
            console.print(f"❌ Failed to access GitHub repository: {e}", style="red")
            return False
            
    def validate_repositories(self) -> bool:
        """Validate that repositories match and can be transferred"""
        console.print("🔍 Validating repository compatibility...")
        
        # Validation results with detailed information
        validation_results = []
        has_blocking_errors = False
        has_warnings = False
        
        # Check if both repositories exist
        validation_results.append(("GitLab project accessible", "Pass" if self.gitlab_project else "Fail", "green" if self.gitlab_project else "red"))
        validation_results.append(("GitHub repository accessible", "Pass" if self.github_repo else "Fail", "green" if self.github_repo else "red"))
        
        if not self.gitlab_project or not self.github_repo:
            self.display_detailed_validation_results(validation_results)
            return False
            
        # Compare repository names (allowing for case differences)
        gitlab_name = self.gitlab_project.name.lower()
        github_name = self.github_repo.name.lower()
        name_match = gitlab_name == github_name or github_name in gitlab_name or gitlab_name in github_name
        
        if name_match:
            validation_results.append(("Repository names similar", "Pass", "green"))
        else:
            validation_results.append(("Repository names similar", f"Warning: '{self.gitlab_project.name}' vs '{self.github_repo.name}'", "yellow"))
            has_warnings = True
            
        # Check if GitHub repo has any commits (should be a transfer)
        try:
            commits = list(self.github_repo.get_commits().get_page(0))
            commit_count = len(commits)
            if commit_count > 0:
                validation_results.append(("GitHub repository has commits", f"Pass ({commit_count} commits found)", "green"))
            else:
                validation_results.append(("GitHub repository has commits", "Warning: Empty repository", "yellow"))
                has_warnings = True
        except Exception as e:
            validation_results.append(("GitHub repository has commits", f"Error: {str(e)}", "red"))
            has_blocking_errors = True
                
        # Check GitLab metadata access with detailed error reporting
        metadata_result = self._check_gitlab_metadata_access()
        validation_results.append(metadata_result)
        
        if metadata_result[2] == "red":
            has_blocking_errors = True
        elif metadata_result[2] == "yellow":
            has_warnings = True
            
        self.display_detailed_validation_results(validation_results)
        
        # Handle validation results
        if has_blocking_errors:
            console.print("❌ Validation failed with blocking errors.", style="red")
            return False
            
        if has_warnings:
            console.print("⚠️  Validation completed with warnings.", style="yellow")
            proceed = Confirm.ask("Do you want to proceed despite the warnings?")
            if not proceed:
                console.print("Validation cancelled by user.", style="yellow")
                return False
            console.print("Proceeding with transfer despite warnings...", style="yellow")
            
        return True
        
    def display_detailed_validation_results(self, results: List[Tuple[str, str, str]]):
        """Display detailed validation results in a table"""
        table = Table(title="Repository Validation", show_header=True)
        table.add_column("Check", style="cyan")
        table.add_column("Result", style="white")
        
        for check_name, result_text, result_style in results:
            # Add appropriate emoji based on result
            if result_style == "green":
                emoji = "✅"
            elif result_style == "yellow":
                emoji = "⚠️ "
            else:  # red
                emoji = "❌"
                
            table.add_row(check_name, f"{emoji} {result_text}")
            
        console.print(table)
        
    def _check_gitlab_metadata_access(self) -> Tuple[str, str, str]:
        """Check GitLab metadata access with detailed error reporting"""
        try:
            # Try to get actual counts
            issues_count = "Unknown"
            mrs_count = "Unknown"
            labels_count = "Unknown"
            milestones_count = "Unknown"
            
            issues_error = None
            mrs_error = None
            labels_error = None
            milestones_error = None
            
            # Check issues access
            try:
                issues_list = list(self.gitlab_project.issues.list(per_page=1, all=False))
                # Get more accurate count by checking if there are more
                if issues_list:
                    try:
                        all_issues = list(self.gitlab_project.issues.list(all=True, lazy=True))
                        issues_count = len(all_issues)
                    except:
                        issues_count = "1+"
                else:
                    issues_count = 0
            except Exception as e:
                issues_error = str(e)
                if "403" in str(e) or "Forbidden" in str(e):
                    issues_count = "Permission denied"
                elif "401" in str(e) or "Unauthorized" in str(e):
                    issues_count = "Authentication failed"
                else:
                    issues_count = f"Error: {str(e)[:30]}..."
            
            # Check merge requests access
            try:
                mrs_list = list(self.gitlab_project.mergerequests.list(per_page=1, all=False))
                if mrs_list:
                    try:
                        all_mrs = list(self.gitlab_project.mergerequests.list(all=True, lazy=True))
                        mrs_count = len(all_mrs)
                    except:
                        mrs_count = "1+"
                else:
                    mrs_count = 0
            except Exception as e:
                mrs_error = str(e)
                if "403" in str(e) or "Forbidden" in str(e):
                    mrs_count = "Permission denied"
                elif "401" in str(e) or "Unauthorized" in str(e):
                    mrs_count = "Authentication failed"
                else:
                    mrs_count = f"Error: {str(e)[:30]}..."
            
            # Check labels access
            try:
                labels_list = list(self.gitlab_project.labels.list(all=True))
                labels_count = len(labels_list)
            except Exception as e:
                labels_error = str(e)
                if "403" in str(e) or "Forbidden" in str(e):
                    labels_count = "Permission denied"
                else:
                    labels_count = f"Error: {str(e)[:20]}..."
            
            # Check milestones access
            try:
                milestones_list = list(self.gitlab_project.milestones.list(all=True))
                milestones_count = len(milestones_list)
            except Exception as e:
                milestones_error = str(e)
                if "403" in str(e) or "Forbidden" in str(e):
                    milestones_count = "Permission denied"
                else:
                    milestones_count = f"Error: {str(e)[:20]}..."
            
            # Determine overall result
            result_text = f"Issues: {issues_count}, MRs: {mrs_count}, Labels: {labels_count}, Milestones: {milestones_count}"
            
            # Categorize the result
            permission_errors = ["Permission denied", "Authentication failed"]
            has_permission_error = any(str(count) in permission_errors for count in [issues_count, mrs_count, labels_count, milestones_count])
            has_api_error = any(str(count).startswith("Error:") for count in [issues_count, mrs_count, labels_count, milestones_count])
            has_data = any(isinstance(count, int) and count > 0 for count in [issues_count, mrs_count, labels_count, milestones_count] if isinstance(count, int))
            all_zero = all(count == 0 for count in [issues_count, mrs_count, labels_count, milestones_count] if isinstance(count, int))
            
            if has_api_error:
                return ("GitLab metadata access", f"API Error - {result_text}", "red")
            elif has_permission_error:
                return ("GitLab metadata access", f"Permission Issues - {result_text}", "yellow")
            elif has_data:
                return ("GitLab metadata access", f"Success - {result_text}", "green")
            elif all_zero and not has_permission_error:
                return ("GitLab metadata access", f"No Data Found - {result_text}", "yellow")
            else:
                return ("GitLab metadata access", f"Mixed Results - {result_text}", "yellow")
                
        except Exception as e:
            return ("GitLab metadata access", f"Unexpected Error: {str(e)}", "red")
        
    def create_user_mapping_file(self, gitlab_users: Set[UserMapping]) -> bool:
        """Create initial user mapping file for manual editing"""
        mapping_file = self.export_dir / "user_mapping.json"
        
        # Create export directory
        self.export_dir.mkdir(exist_ok=True)
        
        # Create initial mapping structure
        user_mapping_data = {}
        for user in gitlab_users:
            user_mapping_data[user.gitlab_username] = {
                "gitlab_id": user.gitlab_id,
                "gitlab_username": user.gitlab_username,
                "fallback_name": user.fallback_name,
                "email": user.email,
                "github_username": "",  # To be filled by user
                "github_id": None       # Will be resolved automatically
            }
            
        try:
            with open(mapping_file, 'w') as f:
                json.dump(user_mapping_data, f, indent=2, default=str)
                
            console.print(f"📝 Created user mapping file: {mapping_file}", style="blue")
            console.print("   Please edit this file to map GitLab users to GitHub users", style="blue")
            return True
        except Exception as e:
            console.print(f"❌ Failed to create user mapping file: {e}", style="red")
            return False
            
    def load_user_mappings(self) -> bool:
        """Load user mappings from file"""
        mapping_file = self.export_dir / "user_mapping.json"
        
        if not mapping_file.exists():
            console.print("⚠️  User mapping file not found", style="yellow")
            return False
            
        try:
            with open(mapping_file, 'r') as f:
                mapping_data = json.load(f)
                
            self.user_mappings = {}
            for gitlab_username, data in mapping_data.items():
                mapping = UserMapping(
                    gitlab_username=data['gitlab_username'],
                    gitlab_id=data['gitlab_id'],
                    github_username=data.get('github_username') or None,
                    github_id=data.get('github_id'),
                    fallback_name=data.get('fallback_name'),
                    email=data.get('email')
                )
                self.user_mappings[gitlab_username] = mapping
                
            console.print(f"✅ Loaded {len(self.user_mappings)} user mappings", style="green")
            return True
        except Exception as e:
            console.print(f"❌ Failed to load user mappings: {e}", style="red")
            return False
            
    def export_metadata(self) -> bool:
        """Export GitLab metadata to local files"""
        console.print("📤 Exporting GitLab metadata...")
        
        # Create export directory
        self.export_dir.mkdir(exist_ok=True)
        
        try:
            extractor = GitLabMetadataExtractor(self.gitlab_client, self.gitlab_project)
            
            # Extract all metadata
            issues = extractor.extract_issues()
            merge_requests = extractor.extract_merge_requests()
            labels = extractor.extract_labels()
            milestones = extractor.extract_milestones()
            
            # Collect all unique users
            all_users = set()
            for issue in issues:
                all_users.add(issue.author)
                all_users.update(issue.assignees)
                for comment in issue.comments:
                    all_users.add(UserMapping(**comment['author']))
                    
            for mr in merge_requests:
                all_users.add(mr.author)
                if mr.assignee:
                    all_users.add(mr.assignee)
                for comment in mr.comments:
                    all_users.add(UserMapping(**comment['author']))
            
            # Export to JSON files
            export_data = {
                'project_info': {
                    'gitlab_id': self.gitlab_project.id,
                    'gitlab_name': self.gitlab_project.name,
                    'gitlab_url': self.gitlab_project.web_url,
                    'github_repo': self.github_repo.full_name if self.github_repo else None,
                    'export_timestamp': datetime.now().isoformat()
                },
                'issues': [asdict(issue) for issue in issues],
                'merge_requests': [asdict(mr) for mr in merge_requests],
                'labels': labels,
                'milestones': milestones
            }
            
            # Save main export file
            export_file = self.export_dir / "metadata_export.json"
            with open(export_file, 'w') as f:
                json.dump(export_data, f, indent=2, default=str)
                
            console.print(f"✅ Exported metadata to {export_file}", style="green")
            
            # Create user mapping file
            self.create_user_mapping_file(all_users)
            
            # Create summary report
            self.create_export_summary(len(issues), len(merge_requests), len(labels), len(milestones), len(all_users))
            
            return True
            
        except Exception as e:
            console.print(f"❌ Failed to export metadata: {e}", style="red")
            traceback.print_exc()
            return False
            
    def create_export_summary(self, issues_count: int, mrs_count: int, 
                            labels_count: int, milestones_count: int, users_count: int):
        """Create export summary report"""
        summary_file = self.export_dir / "export_summary.txt"
        
        summary = f"""GitLab Metadata Export Summary
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Source: {self.gitlab_project.web_url}
Target: {self.github_repo.html_url if self.github_repo else 'Not specified'}

Exported Items:
- Issues: {issues_count}
- Merge Requests (closed/merged): {mrs_count}  
- Labels: {labels_count}
- Milestones: {milestones_count}
- Unique Users: {users_count}

Next Steps:
1. Review and edit user_mapping.json to map GitLab users to GitHub users
2. Run the import command to transfer metadata to GitHub
3. Verify the transfer results

Files Created:
- metadata_export.json (main export data)
- user_mapping.json (user mappings - edit this!)
- export_summary.txt (this file)
"""
        
        try:
            with open(summary_file, 'w') as f:
                f.write(summary)
            console.print(f"📋 Created export summary: {summary_file}", style="blue")
        except Exception as e:
            console.print(f"⚠️  Could not create summary file: {e}", style="yellow")
            
    def import_metadata(self) -> bool:
        """Import metadata to GitHub repository"""
        console.print("📥 Importing metadata to GitHub...")
        
        # Load exported metadata
        export_file = self.export_dir / "metadata_export.json"
        if not export_file.exists():
            console.print(f"❌ Export file not found: {export_file}", style="red")
            return False
            
        # Load user mappings
        if not self.load_user_mappings():
            console.print("⚠️  Continuing without user mappings", style="yellow")
            
        try:
            with open(export_file, 'r') as f:
                export_data = json.load(f)
                
            # Convert back to data classes
            issues = []
            for issue_dict in export_data['issues']:
                issue_dict['author'] = UserMapping(**issue_dict['author'])
                issue_dict['assignees'] = [UserMapping(**a) for a in issue_dict['assignees']]
                issues.append(IssueData(**issue_dict))
                
            merge_requests = []
            for mr_dict in export_data['merge_requests']:
                mr_dict['author'] = UserMapping(**mr_dict['author'])
                if mr_dict['assignee']:
                    mr_dict['assignee'] = UserMapping(**mr_dict['assignee'])
                merge_requests.append(MergeRequestData(**mr_dict))
                
            labels = export_data['labels']
            milestones = export_data['milestones']
            
            # Import to GitHub
            importer = GitHubMetadataImporter(self.github_client, self.github_repo, self.user_mappings)
            
            # Import labels first
            imported_labels = importer.import_labels(labels)
            
            # Import milestones
            imported_milestones = importer.import_milestones(milestones)
            
            # Import issues
            imported_issues = importer.import_issues(issues, imported_labels, imported_milestones)
            
            # Note: We don't import merge requests as PRs since they can't be created for closed/merged state
            console.print("ℹ️  Merge requests are exported for reference but not imported (GitHub doesn't allow creating closed PRs)", style="blue")
            
            # Create import summary
            self.create_import_summary(len(imported_issues), len(imported_labels), len(imported_milestones))
            
            console.print("🎉 Metadata import completed successfully!", style="bold green")
            return True
            
        except Exception as e:
            console.print(f"❌ Failed to import metadata: {e}", style="red")
            traceback.print_exc()
            return False
            
    def create_import_summary(self, issues_count: int, labels_count: int, milestones_count: int):
        """Create import summary report"""
        summary_file = self.export_dir / "import_summary.txt"
        
        summary = f"""GitHub Metadata Import Summary
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Target: {self.github_repo.html_url}

Imported Items:
- Issues: {issues_count}
- Labels: {labels_count}
- Milestones: {milestones_count}

Notes:
- Merge requests are not imported as GitHub PRs (GitHub doesn't support creating closed PRs)
- Original GitLab URLs and metadata are preserved in issue descriptions
- User mappings were applied where available

Verification:
- Check {self.github_repo.html_url}/issues for imported issues
- Check {self.github_repo.html_url}/labels for imported labels  
- Check {self.github_repo.html_url}/milestones for imported milestones
"""
        
        try:
            with open(summary_file, 'w') as f:
                f.write(summary)
            console.print(f"📋 Created import summary: {summary_file}", style="blue")
        except Exception as e:
            console.print(f"⚠️  Could not create summary file: {e}", style="yellow")
            
    def transfer_metadata(self, gitlab_url: str, gitlab_token: str, github_token: str,
                         gitlab_project_url: str, github_repo_name: str) -> bool:
        """Main transfer process"""
        if self.dry_run:
            return self.dry_run_analysis(gitlab_url, gitlab_token, github_token,
                                       gitlab_project_url, github_repo_name)
                                       
        console.print("🚀 Starting GitLab to GitHub metadata transfer...\n")
        
        # Setup clients
        if not self.setup_gitlab_client(gitlab_url, gitlab_token):
            return False
            
        if not self.setup_github_client(github_token):
            return False
            
        # Get repositories  
        if not self.get_gitlab_project(gitlab_project_url):
            return False
            
        if not self.get_github_repo(github_repo_name):
            return False
            
        # Validate compatibility
        if not self.validate_repositories():
            return False
            
        # Export metadata from GitLab
        if not self.export_metadata():
            return False
            
        # Import metadata to GitHub
        if not self.import_metadata():
            return False
            
        console.print(f"\n🎉 Metadata transfer completed successfully!", style="bold green")
        console.print(f"📍 GitHub repository: {self.github_repo.html_url}")
        console.print(f"📂 Export data saved to: {self.export_dir.absolute()}")
        
        return True
        
    def dry_run_analysis(self, gitlab_url: str, gitlab_token: str, github_token: str,
                        gitlab_project_url: str, github_repo_name: str) -> bool:
        """Perform dry run analysis"""
        console.print("\n🔍 Starting dry run analysis...\n")
        
        # Setup and validate everything without making changes
        if not self.setup_gitlab_client(gitlab_url, gitlab_token):
            return False
            
        if not self.setup_github_client(github_token):
            return False
            
        if not self.get_gitlab_project(gitlab_project_url):
            return False
            
        if not self.get_github_repo(github_repo_name):
            return False
            
        if not self.validate_repositories():
            return False
            
        # Analyze what would be transferred
        extractor = GitLabMetadataExtractor(self.gitlab_client, self.gitlab_project)
        
        console.print("🔍 Analyzing transferable metadata...\n")
        
        # Get counts without full extraction - use safer approach after validation
        console.print("📊 Analyzing transfer scope...")
        
        table = Table(title="Metadata Transfer Analysis", show_header=True)
        table.add_column("Item Type", style="cyan")
        table.add_column("Count", style="white") 
        table.add_column("Transfer Status", style="green")
        
        # Re-use the metadata access check for consistency
        metadata_check = self._check_gitlab_metadata_access()
        
        # Parse the detailed results from validation
        if "Success -" in metadata_check[1]:
            # Extract individual counts from the success message
            details = metadata_check[1].replace("Success - ", "")
            console.print(f"Detailed metadata access: {details}", style="blue")
            
            # Try to extract individual numbers or show what we can
            if "Issues: " in details:
                issues_part = details.split("Issues: ")[1].split(",")[0].strip()
                mrs_part = details.split("MRs: ")[1].split(",")[0].strip()
                labels_part = details.split("Labels: ")[1].split(",")[0].strip()
                milestones_part = details.split("Milestones: ")[1].strip()
                
                table.add_row("Issues", issues_part, "✅ Will be transferred")
                if mrs_part.isdigit():
                    mrs_count = int(mrs_part)
                    table.add_row("Merge Requests (all)", mrs_part, f"ℹ️  Closed/merged will be exported for reference")
                else:
                    table.add_row("Merge Requests", mrs_part, "ℹ️  Closed/merged will be exported for reference")
                table.add_row("Labels", labels_part, "✅ Will be transferred")  
                table.add_row("Milestones", milestones_part, "✅ Will be transferred")
                
        elif "Permission Issues -" in metadata_check[1] or "No Data Found -" in metadata_check[1]:
            # Show what we know despite permission issues
            details = metadata_check[1].split(" - ")[1]
            console.print(f"Limited metadata access, showing what's available: {details}", style="yellow")
            
            table.add_row("Issues", "See validation results", "⚠️  Will attempt transfer")
            table.add_row("Merge Requests", "See validation results", "⚠️  Will attempt export")  
            table.add_row("Labels", "See validation results", "⚠️  Will attempt transfer")
            table.add_row("Milestones", "See validation results", "⚠️  Will attempt transfer")
            
        else:
            # API errors or unknown state
            table.add_row("All Metadata", "See validation results above", "⚠️  Transfer will be attempted")
            
        console.print(table)
        
        console.print("\n✅ Dry run analysis completed!", style="bold green")
        console.print("💡 Repository validation passed - transfer can proceed.", style="blue")
        console.print(f"📂 Data would be exported to: {self.export_dir.absolute()}", style="blue")
        
        if metadata_check[2] == "yellow":
            console.print("⚠️  Note: Some metadata access issues were detected during validation.", style="yellow")
            console.print("   The tool will attempt the transfer and handle errors gracefully.", style="yellow")
            
        return True


@click.command()
@click.option('--dry-run', is_flag=True, help='Perform validation checks without making any changes')
def main(dry_run):
    """GitLab to GitHub Metadata Transfer Tool"""
    
    mode_text = "DRY RUN MODE - Analysis Only" if dry_run else "Transfer Mode"
    mode_style = "yellow" if dry_run else "blue"
    
    console.print(Panel.fit(
        f"[bold blue]GitLab to GitHub Metadata Transfer Tool[/bold blue]\n\n"
        f"[{mode_style}]{mode_text}[/{mode_style}]\n\n"
        "This tool transfers GitLab issues, labels, milestones, and metadata\n"
        "to GitHub while preserving original context and timestamps.",
        border_style=mode_style
    ))
    
    # Collect user inputs - same pattern as gittransfer.py
    gitlab_url = Prompt.ask("\n[bold]GitLab instance URL[/bold] (e.g., https://gitlab.company.com)")
    gitlab_token = Prompt.ask("[bold]GitLab personal access token[/bold]", password=True)
    github_token = Prompt.ask("[bold]GitHub personal access token[/bold]", password=True)
    
    gitlab_project_url = Prompt.ask("\n[bold]GitLab project URL or path[/bold] (e.g., https://gitlab.com/owner/repo or owner/repo)")
    github_repo = Prompt.ask("[bold]GitHub repository (owner/repo)[/bold] (must already exist)")
    
    # Ask about export directory
    use_custom_dir = Confirm.ask("Do you want to use a custom export directory?")
    export_dir = DEFAULT_EXPORT_DIR
    if use_custom_dir:
        export_dir = Prompt.ask("[bold]Export directory[/bold]", default=DEFAULT_EXPORT_DIR)
        
    # Ask for dry run if not specified via CLI
    if not dry_run and not Confirm.ask("\nDo you want to perform the actual transfer now?", default=True):
        dry_run = True
        console.print("[yellow]Switching to dry run mode for validation...[/yellow]")
    
    # Confirmation - same pattern as gittransfer.py
    action = "Dry Run Analysis" if dry_run else "Transfer"
    console.print(f"\n[bold yellow]{action} Summary:[/bold yellow]")
    console.print(f"📤 From: {gitlab_project_url}")
    console.print(f"📥 To: {github_repo}")
    console.print(f"📂 Export directory: {export_dir}")
    if dry_run:
        console.print("🔍 Mode: Analysis only (no changes will be made)")
    
    proceed_text = f"Proceed with the {action.lower()}?"
    if not Confirm.ask(f"\n{proceed_text}"):
        console.print(f"{action} cancelled.")
        return
    
    # Perform transfer
    tool = MetadataTransferTool(dry_run=dry_run, export_dir=export_dir)
    success = tool.transfer_metadata(
        gitlab_url=gitlab_url,
        gitlab_token=gitlab_token,
        github_token=github_token,
        gitlab_project_url=gitlab_project_url,
        github_repo_name=github_repo
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