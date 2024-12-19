#!/usr/bin/env python3

import logging
import asyncio
from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.stdio import stdio_server
import json
import traceback
import difflib
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from enum import Enum
import subprocess
import os
import tempfile
import sys
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("codesavant.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("codesavant-server")

class CodeSavantError(Exception):
    pass

class CodeValidationError(CodeSavantError):
    pass

class CodeExecutionError(CodeSavantError):
    pass

class CodeFileError(CodeSavantError):
    pass

@dataclass
class CodeDiff:
    """Represents changes made to a code file"""
    original: str
    modified: str
    changes: List[Tuple[str, int, int, int, int]]  # (type, old_start, old_end, new_start, new_end)
    timestamp: float

class CodeDiffDetail:
    line_number: int
    original_line: str
    modified_line: str
    change_type: str  # 'insert', 'delete', 'replace'

class CodeExecutionState(Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"

@dataclass
class CodeExecutionResult:
    """Represents the result of code execution"""
    state: CodeExecutionState
    output: str
    error: Optional[str]
    runtime: float
    exit_code: int

class CodeFileManager:
    """Manages code file operations and tracks changes"""
    
    def __init__(self, base_path: str = "workspaces"):
        self.base_path = base_path
        self.projects: Dict[str, Dict[str, List[CodeDiff]]] = {}
        self._ensure_base_path()
        self.projects = self._load_projects() 

    def _ensure_base_path(self):
        """Create base workspaces directory if it doesn't exist"""
        os.makedirs(self.base_path, exist_ok=True)

    def _get_project_path(self, project: str) -> str:
        """Get full path for a project workspace"""
        return os.path.join(self.base_path, project)

    def _ensure_project(self, project: str):
        """Create project directory and history if it doesn't exist"""
        project_path = self._get_project_path(project)
        os.makedirs(project_path, exist_ok=True)
        if project not in self.projects:
            self.projects[project] = {}
            self._save_project_history(project)

    def read_code_file(self, project: str, path: str, search: Optional[str] = None) -> Dict[str, Any]:
        """Read code file content from project, optionally finding specific sections
        
        Args:
            project: Project name
            path: Path to file relative to project
            search: Optional text to search for code blocks
            
        Returns:
            Dict containing:
            - content: The file or block content
            - start_line: Starting line number (if search used)
            - end_line: Ending line number (if search used)
        """
        self._ensure_project(project)
        full_path = os.path.join(self._get_project_path(project), path)
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                if not search:
                    return {"content": f.read()}
                    
                lines = f.readlines()
                # Find the target section
                start_line = None
                for i, line in enumerate(lines):
                    if search in line:
                        start_line = i
                        break
                        
                if start_line is None:
                    raise CodeFileError(f"Search text '{search}' not found in file")
                    
                # Find where the block ends (by checking indentation)
                base_indent = len(lines[start_line]) - len(lines[start_line].lstrip())
                end_line = start_line
                
                for i in range(start_line + 1, len(lines)):
                    # Skip empty lines
                    if not lines[i].strip():
                        continue
                    # If we find a line with same/less indentation, we've left the block
                    current_indent = len(lines[i]) - len(lines[i].lstrip())
                    if current_indent <= base_indent:
                        end_line = i - 1
                        break
                    end_line = i
                        
                return {
                    "content": ''.join(lines[start_line:end_line + 1]),
                    "start_line": start_line,
                    "end_line": end_line
                }
                    
        except Exception as e:
            raise CodeFileError(f"Failed to read file {path} in project {project}: {str(e)}")

    def write_code_file(self, project: str, path: str, content: str, start_line: int, end_line: Optional[int] = None) -> CodeDiff:
        """Write specific content changes to a code file in project"""
        self._ensure_project(project)
        full_path = os.path.join(self._get_project_path(project), path)
        
        try:
            # Read existing file content
            current_content = self.read_code_file(project, path) if os.path.exists(full_path) else ""
            current_lines = current_content.splitlines()
            
            # If end_line not specified, assume single line insertion
            if end_line is None:
                end_line = start_line
                
            # Create new content by replacing specified lines
            new_lines = current_lines.copy()
            new_lines[start_line:end_line+1] = content.splitlines()
            new_content = "\n".join(new_lines)
            
            # Calculate diff of just the changed section
            differ = difflib.SequenceMatcher(None, 
                current_lines[start_line:end_line+1],
                content.splitlines())
            changes = [(tag, i1+start_line, i2+start_line, j1+start_line, j2+start_line) 
                    for tag, i1, i2, j1, j2 in differ.get_opcodes() 
                    if tag != 'equal']
            
            # Write the complete file
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
                
            diff = CodeDiff(
                original="\n".join(current_lines[start_line:end_line+1]),
                modified=content,
                changes=changes,
                timestamp=datetime.now().timestamp()
            )
            
            # Update project history
            if path not in self.projects[project]:
                self.projects[project][path] = []
            self.projects[project][path].append(diff)
            self._save_project_history(project)
            
            return diff
                
        except Exception as e:
            raise CodeFileError(f"Failed to write file {path}: {str(e)}")

    def get_code_history(self, project: str, path: str) -> List[CodeDiff]:
        """Get change history for a code file in project"""
        self._ensure_project(project)
        return self.projects[project].get(path, [])
    
    def format_diff(self, diff: CodeDiff) -> str:
        """Generate human-readable diff output"""
        output = []
        for change in diff.changes:
            tag, i1, i2, j1, j2 = change
            if tag == 'insert':
                lines = diff.modified.splitlines()[j1:j2]
                for line in lines:
                    output.append(f"+ {line}")
            elif tag == 'delete':
                lines = diff.original.splitlines()[i1:i2]
                for line in lines:
                    output.append(f"- {line}")
            elif tag == 'replace':
                old_lines = diff.original.splitlines()[i1:i2]
                new_lines = diff.modified.splitlines()[j1:j2]
                for line in old_lines:
                    output.append(f"- {line}")
                for line in new_lines:
                    output.append(f"+ {line}")
        return "\n".join(output)

    def revert_to_version(self, project: str, path: str, timestamp: float) -> CodeDiff:
        self._ensure_project(project)
        history = self.get_code_history(project, path)
        target_version = None
        for diff in history:
            if diff.timestamp == timestamp:
                target_version = diff
                break
        if not target_version:
            raise CodeFileError(f"No version found at timestamp {timestamp}")
        return self.write_code_file(project, path, target_version.original)  # Use original content
    
    def _load_history(self):
        history_path = os.path.join(self.base_path, '.code_history.json')
        if os.path.exists(history_path):
            try:
                with open(history_path, 'r') as f:
                    history_data = json.load(f)
                    # Convert loaded data back to CodeDiff objects
                    self.history = {
                        path: [CodeDiff(**diff) for diff in diffs]
                        for path, diffs in history_data.items()
                    }
            except Exception as e:
                logger.error(f"Failed to load history: {str(e)}")
                self.history = {}
        else:
            self.history = {}

    def _save_history(self):
        history_path = os.path.join(self.base_path, '.code_history.json')
        try:
            # Convert CodeDiff objects to dicts for JSON serialization
            history_data = {
                path: [{"original": d.original, "modified": d.modified, 
                    "changes": d.changes, "timestamp": d.timestamp}
                    for d in diffs]
                for path, diffs in self.history.items()
            }
            with open(history_path, 'w') as f:
                json.dump(history_data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save history: {str(e)}")
        
    def _load_projects(self):
        """Load all project histories on startup"""
        projects = {}
        if os.path.exists(self.base_path):
            for project in os.listdir(self.base_path):
                project_path = self._get_project_path(project)
                if os.path.isdir(project_path):
                    history_file = os.path.join(project_path, '.code_history.json')
                    if os.path.exists(history_file):
                        try:
                            with open(history_file, 'r') as f:
                                history_data = json.load(f)
                                projects[project] = {
                                    path: [CodeDiff(**diff) for diff in diffs]
                                    for path, diffs in history_data.items()
                                }
                        except Exception as e:
                            logger.error(f"Failed to load history for project {project}: {str(e)}")
                            projects[project] = {}
        return projects
    
    def _save_project_history(self, project: str):
        """Save history for a specific project with backup"""
        history_file = os.path.join(self._get_project_path(project), '.code_history.json')
        backup_file = f"{history_file}.{int(datetime.now().timestamp())}.bak"
        
        try:
            # Create backup of existing history if it exists
            if os.path.exists(history_file):
                shutil.copy2(history_file, backup_file)
                
            history_data = {
                path: [{"original": d.original, "modified": d.modified, 
                    "changes": d.changes, "timestamp": d.timestamp}
                    for d in diffs]
                for path, diffs in self.projects[project].items()
            }
            with open(history_file, 'w') as f:
                json.dump(history_data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save history for project {project}: {str(e)}")

    def read_code_file_lines(self, project: str, path: str, start_line: int, end_line: Optional[int] = None) -> str:
        """Read specific lines from a code file"""
        content = self.read_code_file(project, path)
        lines = content.splitlines()
        if end_line is None:
            end_line = start_line
        return "\n".join(lines[start_line:end_line + 1])

class CodeCommandExecutor:
    """Handles code-related shell command execution and output capture"""
    
    def __init__(self, workspace: str):
        self.workspace = workspace
        self.history: List[Dict] = []

    async def execute_command(self, command: str, timeout: int = 30) -> CodeExecutionResult:
        """Execute shell command and capture output"""
        start_time = datetime.now().timestamp()
        
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workspace
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
                state = CodeExecutionState.SUCCESS if process.returncode == 0 else CodeExecutionState.ERROR
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except:
                    pass
                state = CodeExecutionState.TIMEOUT
                stdout, stderr = b'', b'Command timed out'
            
            runtime = datetime.now().timestamp() - start_time
            
            result = CodeExecutionResult(
                state=state,
                output=stdout.decode() if stdout else '',
                error=stderr.decode() if stderr else None,
                runtime=runtime,
                exit_code=process.returncode if state != CodeExecutionState.TIMEOUT else -1
            )
            
            # Log to history
            self.history.append({
                'command': command,
                'result': result,
                'timestamp': start_time
            })
            
            return result
            
        except Exception as e:
            raise CodeExecutionError(f"Command execution failed: {str(e)}")

class CodeRunner:
    """Handles code execution in different languages"""
    
    SUPPORTED_LANGUAGES = {
        'python': {
            'extension': '.py',
            'command': sys.executable
        },
        'node': {
            'extension': '.js',
            'command': 'node'
        }
        # Add more languages as needed
    }
    
    def __init__(self, workspace: str):
        self.workspace = workspace
        self.history: List[Dict] = []
        self._running_processes: Dict[str, asyncio.subprocess.Process] = {}  # Add this line

    async def execute_code(self, code: str, language: str, timeout: int = 30) -> CodeExecutionResult:
        """Execute code in specified language"""
        if language not in self.SUPPORTED_LANGUAGES:
            raise CodeValidationError(f"Unsupported language: {language}")
            
        lang_config = self.SUPPORTED_LANGUAGES[language]
        start_time = datetime.now().timestamp()
        
        with tempfile.NamedTemporaryFile(
            suffix=lang_config['extension'],
            mode='w',
            encoding='utf-8',
            dir=self.workspace,
            delete=False
        ) as tf:
            try:
                # Write code to temp file
                tf.write(code)
                tf.flush()
                
                # Build command
                command = f"{lang_config['command']} {tf.name}"
                
                # Execute
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.workspace
                )
                
                code_id = str(hash(f"{code}_{start_time}"))

                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
                    state = CodeExecutionState.SUCCESS if process.returncode == 0 else CodeExecutionState.ERROR
                except asyncio.TimeoutError:
                    try:
                        process.kill()
                    except:
                        pass
                    state = CodeExecutionState.TIMEOUT
                    stdout, stderr = b'', b'Execution timed out'
                except asyncio.CancelledError:  # Add this block
                    try:
                        process.kill()
                    except:
                        pass
                    state = CodeExecutionState.CANCELLED
                    stdout, stderr = b'', b'Execution cancelled'
                finally:
                    if code_id in self._running_processes:
                        del self._running_processes[code_id]
                                
                runtime = datetime.now().timestamp() - start_time
                
                result = CodeExecutionResult(
                    state=state,
                    output=stdout.decode() if stdout else '',
                    error=stderr.decode() if stderr else None,
                    runtime=runtime,
                    exit_code=process.returncode if state != CodeExecutionState.TIMEOUT else -1
                )
                
                # Log to history
                self.history.append({
                    'language': language,
                    'code_hash': hash(code),
                    'result': result,
                    'timestamp': start_time
                })
                
                return result
                
            finally:
                try:
                    os.unlink(tf.name)
                except:
                    pass

def format_code_response(data: Any, error: Optional[str] = None) -> List[TextContent]:
    """Format consistent API response for code operations"""
    response = {
        "success": error is None,
        "timestamp": datetime.now().timestamp(),
        "data": data if error is None else None,
        "error": error
    }
    
    return [TextContent(
        type="text",
        text=json.dumps(response, indent=2)
    )]

# Initialize server and managers
app = Server("codesavant-server")
code_file_manager = CodeFileManager()
code_command_executor = CodeCommandExecutor(code_file_manager.base_path)
code_runner = CodeRunner(code_file_manager.base_path)

@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="read_code_file",
            description="Read contents of a code file",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project name"
                    },
                    "path": {
                        "type": "string",
                        "description": "Path to file relative to project workspace"
                    },
                    "search": {  # Add this parameter
                        "type": "string",
                        "description": "Text/pattern to search for in file (optional)",
                        "optional": True
                    }
                },
                "required": ["project", "path"]
            }
        ),
        Tool(
            name="write_code_file",
            description="Write or update specific lines in a code file",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to file relative to workspace"
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write (just the lines being changed)"
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Starting line number for the change"
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Ending line number for the change (optional)",
                        "optional": True
                    },
                    "project": {
                        "type": "string",
                        "description": "Project name"
                    }
                },
                "required": ["path", "content", "start_line", "project"]
            }
        ),
        Tool(
            name="get_code_history",
            description="Get change history for a code file",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to file relative to workspace"
                    }
                },
                "required": ["path"]
            }
        ),
        Tool(
            name="execute_code_command",
            description="Execute a code-related shell command",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Command timeout in seconds",
                        "default": 30
                    }
                },
                "required": ["command"]
            }
        ),
        Tool(
            name="execute_code",
            description="Execute code in specified language",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Code to execute"
                    },
                    "language": {
                        "type": "string",
                        "description": "Programming language",
                        "enum": list(CodeRunner.SUPPORTED_LANGUAGES.keys())
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Execution timeout in seconds",
                        "default": 30
                    }
                },
                "required": ["code", "language"]
            }
        ),
        Tool(
            name="revert_to_version",
            description="Revert a code file to a specific version",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to file relative to workspace"
                    },
                    "timestamp": {
                        "type": "number",
                        "description": "Timestamp of version to revert to"
                    }
                },
                "required": ["path", "timestamp"]
            }
        ),
        Tool(
            name="read_code_file_lines",
            description="Read specific lines from a code file",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project name"
                    },
                    "path": {
                        "type": "string",
                        "description": "Path to file relative to project workspace"
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Starting line number to read"
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Ending line number to read (optional)",
                        "optional": True
                    }
                },
                "required": ["project", "path", "start_line"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    try:
        if name == "read_code_file":
            result = code_file_manager.read_code_file(
                arguments['project'],
                arguments['path'],
                arguments.get('search')  # Optional parameter
            )
            # Format response to include all fields from result
            return format_code_response({
                "content": result["content"],
                "start_line": result.get("start_line"),  # Only present if search was used
                "end_line": result.get("end_line")       # Only present if search was used
            })
                    
        elif name == "read_code_file_lines":  # Add this new handler
            content = code_file_manager.read_code_file_lines(
                arguments['project'],
                arguments['path'],
                arguments['start_line'],
                arguments.get('end_line')  # Optional parameter
            )
            return format_code_response({"content": content})

        elif name == "write_code_file":
            diff = code_file_manager.write_code_file(
                arguments['project'],
                arguments['path'],
                arguments['content'],
                arguments['start_line'],
                arguments.get('end_line')  # Optional parameter
            )
            return format_code_response({
                "diff": {
                    "changes": diff.changes,
                    "timestamp": diff.timestamp
                }
            })
            
        elif name == "get_code_history":
            history = code_file_manager.get_code_history(
                arguments['project'],
                arguments['path']
            )
            return format_code_response({
                "history": [
                    {
                        "changes": diff.changes,
                        "timestamp": diff.timestamp
                    }
                    for diff in history
                ]
            })
            
        elif name == "execute_code_command":
            result = await code_command_executor.execute_command(
                arguments['command'],
                timeout=arguments.get('timeout', 30)
            )
            return format_code_response({
                "state": result.state.value,
                "output": result.output,
                "error": result.error,
                "runtime": result.runtime,
                "exit_code": result.exit_code
            })
            
        elif name == "execute_code":
            result = await code_runner.execute_code(
                arguments['code'],
                arguments['language'],
                timeout=arguments.get('timeout', 30)
            )
            return format_code_response({
                "state": result.state.value,
                "output": result.output,
                "error": result.error,
                "runtime": result.runtime,
                "exit_code": result.exit_code
            })
        
        elif name == "revert_to_version":
            diff = code_file_manager.revert_to_version(
                arguments['project'],
                arguments['path'],
                arguments['timestamp']
            )
            return format_code_response({
                "diff": {
                    "changes": diff.changes,
                    "timestamp": diff.timestamp
                }
            })
            
    except CodeValidationError as e:
        logger.error(f"Validation error in {name}: {str(e)}")
        return format_code_response(None, f"Validation error: {str(e)}")
        
    except (CodeFileError, CodeExecutionError) as e:
        logger.error(f"Operation error in {name}: {str(e)}")
        return format_code_response(None, str(e))
        
    except Exception as e:
        logger.error(f"Unexpected error in {name}: {str(e)}\n{traceback.format_exc()}")
        return format_code_response(None, f"Internal error: {str(e)}")

async def main():
    logger.info("Starting Codesavant server...")
    try:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options()
            )
    except Exception as e:
        logger.error(f"Server error: {str(e)}\n{traceback.format_exc()}")
        raise

if __name__ == "__main__":
    asyncio.run(main())