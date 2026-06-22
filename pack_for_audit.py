import os
import argparse
from pathlib import Path

# Directories and files to exclude from the bundle
EXCLUDE_DIRS = {
    'node_modules', '.git', '__pycache__', 'venv', '.venv', 'dist', 'build', 
    'dist-electron', 'coverage', '.pytest_cache', 'database_backups', 'logs', 
    'test-results', 'Upload files'
}

# Extensions to include. If empty, includes everything not excluded by extension
INCLUDE_EXTENSIONS = {
    '.py', '.js', '.jsx', '.ts', '.tsx', '.css', '.html', '.md', 
    '.json', '.toml', '.env.example', '.bat', '.ps1', '.sql'
}

# Specific exact files to exclude
EXCLUDE_FILES = {
    '.env', '.env.development.local', 'stock_forecast.db', 'test_enhanced.db', 
    'test_reconcile.db', 'error.log', 'python_debug.log', 'package-lock.json',
    'stock-backend.spec'
}

def is_text_file(filepath):
    """Check if file is likely text by reading first chunk."""
    try:
        with open(filepath, 'tr') as check_file:
            check_file.read(1024)
            return True
    except:
        return False

def should_include_file(file_path):
    """Determine if a file should be included based on rules."""
    path = Path(file_path)
    
    # Check exact file exclusions and bundle files
    if path.name in EXCLUDE_FILES or path.name.startswith('stock_audit_bundle'):
        return False
        
    # Check extension
    if INCLUDE_EXTENSIONS and path.suffix not in INCLUDE_EXTENSIONS:
        # Check files without extensions like 'Dockerfile' but exclude binary files
        if not path.suffix and is_text_file(file_path):
             return True
        return False
        
    return True

def pack_directory(start_dir, output_file_base, max_lines_per_file=5000):
    """Recursively walks directory and concatenates files into multiple output files."""
    start_path = Path(start_dir).resolve()
    
    total_files = 0
    total_lines_all = 0
    current_file_index = 1
    current_out_f = None
    current_lines = 0
    
    def open_new_file():
        nonlocal current_out_f, current_lines
        if current_out_f:
            current_out_f.close()
        
        # Split base name to insert index
        base_path = Path(output_file_base)
        new_filename = f"{base_path.stem}_part{current_file_index}{base_path.suffix}"
        
        current_out_f = open(new_filename, 'w', encoding='utf-8')
        current_out_f.write(f"# Codebase Audit Bundle: {start_path.name} (Part {current_file_index})\n\n")
        current_out_f.write("This file is an automated concatenation of the codebase for AI auditing.\n\n")
        current_out_f.write("---\n\n")
        current_lines = 5
        return new_filename
        
    generated_files = []
    generated_files.append(open_new_file())
    
    for root, dirs, files in os.walk(start_dir):
        # Modify dirs in-place to skip excluded directories
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith('.')]
        
        for file in files:
            file_path = os.path.join(root, file)
            
            if should_include_file(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as in_f:
                        content = in_f.read()
                    
                    lines_in_file = content.count('\n') + 1
                    
                    # check if we need a new file
                    if current_lines + lines_in_file > max_lines_per_file and current_lines > 0:
                        current_file_index += 1
                        generated_files.append(open_new_file())
                    
                    # Get path relative to start_dir for cleaner output
                    rel_path = os.path.relpath(file_path, start_dir)
                    
                    content_to_write = f"\n## File: `{rel_path}`\n\n```"
                    
                    # Add language hint for markdown if possible
                    _, ext = os.path.splitext(file_path)
                    if ext:
                        lang = ext[1:]
                        if lang in ['js', 'jsx', 'ts', 'tsx']:
                            content_to_write += "javascript" if lang in ['js', 'jsx'] else "typescript"
                        elif lang == 'py':
                            content_to_write += "python"
                        elif lang == 'css':
                            content_to_write += "css"
                        elif lang == 'html':
                            content_to_write += "html"
                        elif lang == 'json':
                            content_to_write += "json"
                            
                    content_to_write += "\n"
                    content_to_write += content
                        
                    # ensure ends with newline inside block
                    if not content.endswith('\n'):
                        content_to_write += '\n'
                        
                    content_to_write += "```\n\n"
                    
                    current_out_f.write(content_to_write)
                    current_lines += content_to_write.count('\n')
                    
                    total_files += 1
                    total_lines_all += lines_in_file
                    print(f"Added: {rel_path} ({lines_in_file} lines) to part {current_file_index}")
                    
                except UnicodeDecodeError:
                    print(f"Skipped (Binary/Encoding Issue): {file_path}")
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")

    if current_out_f:
        current_out_f.close()

    print("\n" + "="*50)
    print(f"Audit Bundle Created Successfully!")
    print(f"Output Files: {', '.join(generated_files)}")
    print(f"Total Files Included: {total_files}")
    print(f"Total Lines of Code: {total_lines_all}")
    print("="*50 + "\n")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Pack codebase for AI Audit.')
    parser.add_argument('--dir', default='.', help='Directory to pack (default: current)')
    parser.add_argument('--out', default='stock_audit_bundle.md', help='Output file name')
    
    args = parser.parse_args()
    
    target_dir = args.dir
    output_filepath = args.out
    
    print(f"Starting to pack directory: {target_dir}")
    pack_directory(target_dir, output_filepath)
