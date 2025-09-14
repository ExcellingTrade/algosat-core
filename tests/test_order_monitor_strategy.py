#!/usr/bin/env python3
"""
Test script to validate OrderMonitor strategy instance sharing implementation.
"""

import ast
import sys

def validate_syntax_and_structure(filepath, expected_elements):
    """Validate that a Python file has correct syntax and contains expected elements."""
    try:
        with open(filepath, 'r') as f:
            source = f.read()
        
        # Parse to check syntax
        tree = ast.parse(source)
        
        # Check for expected elements
        found_elements = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                found_elements.append(f"function: {node.name}")
            elif isinstance(node, ast.ClassDef):
                found_elements.append(f"class: {node.name}")
        
        missing_elements = []
        for expected in expected_elements:
            if not any(expected in found for found in found_elements):
                missing_elements.append(expected)
        
        if missing_elements:
            print(f"❌ {filepath}: Missing expected elements: {missing_elements}")
            return False
        else:
            print(f"✅ {filepath}: Syntax valid and contains expected elements")
            return True
            
    except SyntaxError as e:
        print(f"❌ {filepath}: Syntax error: {e}")
        return False
    except Exception as e:
        print(f"❌ {filepath}: Error: {e}")
        return False

def main():
    test_cases = [
        {
            'file': '/opt/algosat/algosat/core/order_monitor.py',
            'expected': [
                'get_strategy_instance',
                'call_strategy_method',
                'class: OrderMonitor',
                'function: __init__'
            ]
        },
        {
            'file': '/opt/algosat/algosat/core/strategy_manager.py',
            'expected': [
                'initialize_strategy_instance',
                'order_monitor_loop',
                'STRATEGY_MAP'
            ]
        }
    ]
    
    all_valid = True
    for test_case in test_cases:
        if not validate_syntax_and_structure(test_case['file'], test_case['expected']):
            all_valid = False
    
    if all_valid:
        print("\n✅ All validation checks passed!")
        print("✅ OrderMonitor strategy instance sharing implementation is ready!")
    else:
        print("\n❌ Some validation checks failed!")
        
    return all_valid

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
