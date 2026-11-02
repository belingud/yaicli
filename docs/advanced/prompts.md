# Prompt Template System

YAICLI features a powerful and flexible prompt template system that allows you to define custom roles and behaviors for your AI assistant. This page explains how to use and customize the prompt system.

## Understanding Roles

In YAICLI, a "role" is a predefined set of instructions, preferences, and behaviors assigned to the AI. Roles help guide how the AI responds to your queries.

### Default Roles

YAICLI ships with three built-in roles: `DEFAULT` (general-purpose assistant),
`Shell Command Generator` (used by `--shell`/execute mode), and `Code Assistant` (used by
`--code`). Built-in role files are seeded into `~/.config/yaicli/roles/` on first run and can be
overridden (a warning is shown unless `ROLE_MODIFY_WARNING=false`).

## Creating Custom Roles

You can create custom roles to tailor the AI's behavior for specific tasks or domains:

```bash
# Create a new role through interactive prompting
ai --create-role "SQL Expert"

# You'll be asked to provide a description for this role
```

When creating a role, you'll be prompted to describe how the AI should behave in that role. For example:

```
Please provide a description for the SQL Expert role:

You are an expert SQL database engineer with deep knowledge of database 
optimization, query design, and best practices across multiple SQL dialects 
including MySQL, PostgreSQL, SQLite, and Microsoft SQL Server. 

When asked about SQL, you should:
1. Consider the specific dialect if mentioned, or clarify which dialect you're using
2. Provide optimized queries with explanations of your optimization choices
3. Consider indexing, query planning, and performance implications
4. Format SQL with proper indentation and capitalization of keywords
```

## Using Custom Roles

Once created, you can use your custom roles:

```bash
# Use in direct query mode
ai --role "SQL Expert" "Optimize this query: SELECT * FROM users WHERE active = true"

# Use in chat mode
ai --chat --role "SQL Expert"
```

Role selection applies to direct queries, `--chat`, and `--code`. `--shell` always uses the
built-in `Shell Command Generator` role (a non-default `--role` is ignored with a warning).

## Managing Roles

YAICLI provides commands to manage your roles:

```bash
# List all available roles
ai --list-roles

# View a specific role's description
ai --show-role "SQL Expert"

# Delete a role
ai --delete-role "SQL Expert"
```

## Role Storage

Custom roles are stored in:
- Linux/macOS: `~/.config/yaicli/roles/`
- Windows: `C:\Users\<username>\.config\yaicli\roles\`

Each role is saved as a JSON file with the role name.

## Setting a Default Role

You can set a default role in your configuration file:

```ini
[core]
DEFAULT_ROLE=SQL Expert
```

Or using an environment variable:

```bash
export YAI_DEFAULT_ROLE="SQL Expert"
```

## Advanced Role Creation

### Role Structure

Roles are defined as JSON files with the following structure:

```json
{
  "name": "Role Name",
  "prompt": "You are a helpful assistant. Reply concisely.",
  "variables": {
    "_os": "macOS",
    "_shell": "zsh"
  }
}
```

`name` and `prompt` are required (the prompt must be a non-empty string and is the
"description" requested by `ai --create-role`). `variables` is optional: if omitted, YAICLI
fills `_os` and `_shell` from auto-detection. The prompt is passed through Python
`str.format()`, so literal braces must be doubled (`{{` and `}}`), and unknown `{name}`
placeholders cause the role to be rejected with a load error.

### Creating Roles Manually

You can create roles manually by adding JSON files to the roles directory:

1. Create a file in `~/.config/yaicli/roles/` (for example `my_role.json`)
2. Add the role structure shown above; the `name` field is what `--role` uses, regardless of the file name
3. Restart YAICLI or run `ai --list-roles` to see your new role

### Role Modification Warning

By default, YAICLI will warn you when attempting to modify built-in roles. To disable this warning:

```ini
[core]
ROLE_MODIFY_WARNING=false
```

## Best Practices for Writing Role Descriptions

For the most effective custom roles:

1. **Be Specific**: Clearly define the expertise and focus area
2. **Set Boundaries**: Specify what the AI should and should not address
3. **Format Guidelines**: Include preferred output formats, styles, or conventions
4. **Examples**: When helpful, include examples of desired responses
5. **Context**: Add relevant domain knowledge or context that might help the AI

## Role Examples

### Technical Writer

```
You are a technical writer specializing in creating clear, concise documentation.

When responding:
1. Use plain language and avoid jargon unless necessary
2. Structure content with logical headings and lists
3. Focus on practical examples and use cases
4. Include both beginner and advanced perspectives
5. Use consistent terminology throughout

For code examples, include comments explaining key concepts.
```

### Data Analyst

```
You are a data analyst with expertise in statistics, data visualization, and data manipulation.

When analyzing data or answering queries:
1. Consider statistical validity and assumptions
2. Suggest appropriate visualization techniques
3. Recommend efficient data processing approaches
4. Highlight potential biases or limitations
5. Provide code examples in Python using pandas, matplotlib, or similar libraries

Always emphasize data integrity and ethical considerations in your analysis.
```

### System Administrator

```
You are a system administrator experienced with Linux, Windows, and cloud environments.

When providing assistance:
1. Prioritize security best practices
2. Consider compatibility across different systems
3. Provide step-by-step instructions with explanations
4. Suggest monitoring and maintenance practices
5. Mention potential pitfalls or issues to watch for

For shell commands, explain what each command does and any flags or options used.
```

## Next Steps

- Learn about [chat history management](history.md)
- Explore [function calling capabilities](../usage/advanced.md#function-calling)
- Check out [debugging and logs](debugging.md)
