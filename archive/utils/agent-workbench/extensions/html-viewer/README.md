# HTML Viewer Extension

An extension for the Agent Workbench that renders HTML content in a sandboxed iframe.

## Features

- **Secure Rendering**: HTML content is rendered in a sandboxed iframe for security
- **Interactive Controls**: Refresh and open in new window buttons
- **Auto-detection**: Automatically detects HTML content even without .html extension
- **Preview & Full View**: Supports both compact preview and expanded full view modes
- **Context Menu**: Right-click options for viewing source and opening in new window

## Supported File Types

- `.html`
- `.htm`
- Any file containing HTML markup (auto-detected)

## Security

The extension uses iframe sandboxing with the following restrictions:
- `allow-scripts`: Allows JavaScript execution within the HTML
- `allow-forms`: Allows form submission
- `allow-modals`: Allows modal dialogs (alert, confirm, prompt)
- `allow-popups`: Allows opening new windows

Note: The sandbox does NOT include `allow-same-origin`, which prevents the embedded content from accessing the parent page's origin and DOM.

## Usage

### In Agent Workbench

When an agent returns HTML content in a file with `.html` or `.htm` extension, or when the content is detected as HTML, the HTML Viewer will automatically render it.

### Controls

- **🔄 Reload**: Refresh the HTML content
- **🗗 Open in New Window**: Opens the HTML in a separate browser window
- **View Source**: (Context menu) View the raw HTML source code

## Examples

### Agent Output

An agent can save HTML output like this:

```python
html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>Data Visualization</title>
    <style>
        body { font-family: Arial, sans-serif; padding: 20px; }
        .chart { border: 1px solid #ccc; margin: 10px 0; }
    </style>
</head>
<body>
    <h1>Results</h1>
    <div class="chart">Chart content here</div>
</body>
</html>
"""

with open('/app/outputs/results.html', 'w') as f:
    f.write(html_content)
```

### Use Cases

- Data visualizations and charts
- Formatted reports
- Interactive dashboards
- Documentation rendering
- Rich text content with styling

## API

The extension follows the standard Extension API:

```javascript
class HtmlExtension extends BaseExtension {
    async canHandle(filename, content)
    async renderPreview(container, filename, content, options)
    async renderFullView(container, filename, content, options)
    getMenuItems(filename, content)
}
```

## Configuration

No additional configuration required. The extension registers itself automatically when loaded.
