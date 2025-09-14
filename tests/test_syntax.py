#!/usr/bin/env python3
"""
Simple syntax validation test for the strategy manager refactoring.
"""

import ast
import sys

def validate_syntax(filepath):
    """Validate that a Python file has correct syntax."""
    try:
        with open(filepath, 'r') as f:
            source = f.read()
        ast.parse(source)
        print(f"✅ {filepath}: Syntax is valid")
        return True
    except SyntaxError as e:
        print(f"❌ {filepath}: Syntax error: {e}")
        return False
    except Exception as e:
        print(f"❌ {filepath}: Error: {e}")
        return False

def main():
    files_to_check = [
        '/opt/algosat/algosat/core/strategy_manager.py',
        '/opt/algosat/algosat/core/strategy_runner.py'
    ]
    
    all_valid = True
    for filepath in files_to_check:
        if not validate_syntax(filepath):
            all_valid = False
    
    if all_valid:
        print("\n✅ All files have valid syntax!")
        print("✅ Strategy manager refactoring syntax validation passed!")
    else:
        print("\n❌ Some files have syntax errors!")
        
    return all_valid

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
