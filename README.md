# MCP-CodeSavant

CodeSavant is a WIP project.

CodeSavant is a Model Context Protocol (MCP) server that provides code manipulation, execution, and version control capabilities. It allows AI assistants to read, write, and execute code while maintaining a history of changes.

## Features

- Read and write code files with line-specific operations
- Execute code in multiple programming languages (Python, Node.js)
- Execute shell commands in a controlled environment
- Track and manage code changes with version control
- Search within code files
- Revert to previous versions of code

## Installation

1. Clone the repository:
```bash
git clone https://github.com/twolven/mcp-codesavant.git
cd mcp-codesavant
```

2. Install the required dependencies:
```bash
pip install -r requirements.txt
```

3. Add the server configuration to your Claude Desktop config.json:
```json
{
  "mcpServers": {
    "codesavant": {
      "command": "python",
      "args": ["path/to/codesavant.py"]
    }
  }
}
```

## Directory Structure

The server creates and manages the following directory structure:
```
workspaces/
├── project1/
│   ├── .code_history.json
│   └── [code files]
├── project2/
│   ├── .code_history.json
│   └── [code files]
└── ...
```

## Tool Reference

### Detailed Usage

#### 1. read_code_file
Read contents of a code file, optionally searching for specific sections.

```json
{
    "project": "string",     // Project name
    "path": "string",        // Path to file relative to project workspace
    "search": "string"       // (Optional) Text/pattern to search for in file
}
```

Response:
```json
{
    "success": true,
    "timestamp": 1234567890,
    "data": {
        "content": "string",      // File content
        "start_line": number,     // (Only if search used) Starting line of found section
        "end_line": number       // (Only if search used) Ending line of found section
    }
}
```

#### 2. write_code_file
Write or update specific lines in a code file.

```json
{
    "project": "string",     // Project name
    "path": "string",        // Path to file relative to workspace
    "content": "string",     // Content to write (just the lines being changed)
    "start_line": number,    // Starting line number for the change
    "end_line": number      // (Optional) Ending line number for the change
}
```

Response:
```json
{
    "success": true,
    "timestamp": 1234567890,
    "data": {
        "diff": {
            "changes": [           // List of changes made
                [string, number, number, number, number]  // (type, old_start, old_end, new_start, new_end)
            ],
            "timestamp": number    // When the change was made
        }
    }
}
```

#### 3. get_code_history
Get change history for a code file.

```json
{
    "path": "string"        // Path to file relative to workspace
}
```

Response:
```json
{
    "success": true,
    "timestamp": 1234567890,
    "data": {
        "history": [
            {
                "changes": [       // List of changes made
                    [string, number, number, number, number]
                ],
                "timestamp": number
            }
        ]
    }
}
```

#### 4. execute_code_command
Execute a code-related shell command.

```json
{
    "command": "string",     // Shell command to execute
    "timeout": number       // (Optional) Command timeout in seconds (default: 30)
}
```

Response:
```json
{
    "success": true,
    "timestamp": 1234567890,
    "data": {
        "state": "success|error|timeout|cancelled",
        "output": "string",        // Command output
        "error": "string",         // Error message if any
        "runtime": number,         // Execution time in seconds
        "exit_code": number       // Command exit code
    }
}
```

#### 5. execute_code
Execute code in specified language.

```json
{
    "code": "string",        // Code to execute
    "language": "string",    // Programming language ("python" or "node")
    "timeout": number       // (Optional) Execution timeout in seconds (default: 30)
}
```

Response:
```json
{
    "success": true,
    "timestamp": 1234567890,
    "data": {
        "state": "success|error|timeout|cancelled",
        "output": "string",        // Code execution output
        "error": "string",         // Error message if any
        "runtime": number,         // Execution time in seconds
        "exit_code": number       // Execution exit code
    }
}
```

#### 6. revert_to_version
Revert a code file to a specific version.

```json
{
    "path": "string",        // Path to file relative to workspace
    "timestamp": number     // Timestamp of version to revert to
}
```

Response:
```json
{
    "success": true,
    "timestamp": 1234567890,
    "data": {
        "diff": {
            "changes": [           // List of changes made
                [string, number, number, number, number]
            ],
            "timestamp": number    // When the reversion was made
        }
    }
}
```

#### 7. read_code_file_lines
Read specific lines from a code file.

```json
{
    "project": "string",     // Project name
    "path": "string",        // Path to file relative to project workspace
    "start_line": number,    // Starting line number to read
    "end_line": number      // (Optional) Ending line number to read
}
```

Response:
```json
{
    "success": true,
    "timestamp": 1234567890,
    "data": {
        "content": "string"        // Content of the specified lines
    }
}
```

## Error Handling

The server provides detailed error responses in the following format:
```json
{
    "success": false,
    "timestamp": 1234567890,
    "data": null,
    "error": "Error message"
}
```

Error types include:
- `CodeFileError`: File operation errors
- `CodeValidationError`: Code validation errors
- `CodeExecutionError`: Code execution errors

## Language Support

Currently supported languages for code execution:
- Python (using system Python interpreter)
- Node.js (using node command)

Each language execution creates a temporary file in the workspace directory and executes it with appropriate interpreter.

## Contributing

1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to the branch
5. Create a new Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Author

Todd Wolven - (https://github.com/twolven)

## Acknowledgments

- Built with the Model Context Protocol (MCP) by Anthropic
- Developed for use with Anthropic's Claude
