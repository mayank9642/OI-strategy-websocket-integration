"""
Update scripts to use the centralized logging utility

This script finds all Python files using direct logging calls
and updates them to use the new log_setup.py utility.
"""
import os
import re
import sys

def update_file(file_path):
    """Update a single file to use the centralized logger"""
    print(f"Processing {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if file already imports our logger
    if 'from src.log_setup import logger' in content:
        print(f"File {file_path} already uses the logger, skipping")
        return False
    
    # Check if file uses logging
    if 'import logging' not in content:
        print(f"File {file_path} doesn't use logging, skipping")
        return False
    
    changes_made = False
    
    # Add import and remove logging imports
    content = re.sub(r'import logging(?:.handlers)?(?:\n|$)', '', content)
    content = re.sub(r'from logging import .*?\n', '', content)
    
    # Find the last import statement to add our import after it
    import_match = re.search(r'^((?:from|import) .*?)$', content, re.MULTILINE)
    if import_match:
        last_import = import_match.group(1)
        last_import_pos = content.rfind(last_import) + len(last_import)
        content = content[:last_import_pos] + '\nfrom src.log_setup import logger  # Import centralized logging' + content[last_import_pos:]
        changes_made = True
    
    # Replace logging.basicConfig with a comment
    content = re.sub(r'logging\.basicConfig\(.*?\)', '# Logging configuration handled by log_setup.py', content, flags=re.DOTALL)
    
    # Replace logging.XXX calls with logger.XXX
    content = re.sub(r'logging\.debug\(', 'logger.debug(', content)
    content = re.sub(r'logging\.info\(', 'logger.info(', content)
    content = re.sub(r'logging\.warning\(', 'logger.warning(', content)
    content = re.sub(r'logging\.error\(', 'logger.error(', content)
    content = re.sub(r'logging\.critical\(', 'logger.critical(', content)
    content = re.sub(r'logging\.exception\(', 'logger.exception(', content)
    
    # Replace logging.getLogger with comments
    content = re.sub(r'(?:root_)?logger\s*=\s*logging\.getLogger\(\)', '# logger is now imported from log_setup', content)
    content = re.sub(r'logging\.getLogger\(\)\.addFilter\((.*?)\)', 'logger.addFilter(\\1)', content)
    
    # Write the updated content back to the file
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return changes_made

def main():
    """Update all Python files in the project to use the centralized logger"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    exclude_files = ['src/log_setup.py', 'update_logging.py']
    
    files_updated = 0
    
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, base_dir)
                
                # Skip files in exclude list
                if rel_path in exclude_files:
                    continue
                
                if update_file(file_path):
                    files_updated += 1
                    print(f"Updated {rel_path}")
    
    print(f"\nDone! Updated {files_updated} files to use the centralized logger.")

if __name__ == "__main__":
    main()
