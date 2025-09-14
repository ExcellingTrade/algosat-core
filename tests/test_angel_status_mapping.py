#!/usr/bin/env python3
"""
Test Angel status code mapping in OrderMonitor.
"""

import sys
import os

# Add the project root to the path
sys.path.insert(0, '/opt/algosat')

def test_angel_status_code_mapping():
    """Test Angel status code mapping in OrderMonitor."""
    try:
        print("🧪 Testing Angel Status Code Mapping")
        print("=" * 60)
        
        # Import required modules
        from algosat.core.order_manager import ANGEL_STATUS_CODE_MAP
        from algosat.core.order_request import OrderStatus
        
        print("📊 Angel Status Code Mapping:")
        print("-" * 40)
        
        # Test all Angel status codes from the attachment
        test_status_codes = [
            ("AB00", "after-successful connection"),
            ("AB01", "open"),
            ("AB02", "cancelled"),
            ("AB03", "rejected"),
            ("AB04", "modified"),
            ("AB05", "complete"),
            ("AB06", "after market order req received"),
            ("AB07", "cancelled after market order"),
            ("AB08", "modify after market order req received"),
            ("AB09", "open pending"),
            ("AB10", "trigger pending"),
            ("AB11", "modify pending"),
            ("XYZ123", "unknown status code")  # Test fallback
        ]
        
        for status_code, description in test_status_codes:
            normalized_status = ANGEL_STATUS_CODE_MAP.get(status_code, status_code)
            print(f"  {status_code:6} ({description:35}) → {normalized_status}")
        
        print(f"\n🔄 Testing OrderMonitor Logic Simulation:")
        print("-" * 40)
        
        # Simulate the OrderMonitor normalization logic
        def simulate_angel_status_normalization(broker_status, broker_name):
            """Simulate the Angel status normalization logic from OrderMonitor."""
            original_status = broker_status
            
            # Apply Angel status code mapping
            if broker_status and isinstance(broker_status, str) and broker_name == "angel" and broker_status.startswith("AB"):
                broker_status = ANGEL_STATUS_CODE_MAP.get(broker_status, broker_status)
            
            # Normalize broker_status (simulate the next lines in OrderMonitor)
            if broker_status and isinstance(broker_status, str) and broker_status.startswith("OrderStatus."):
                broker_status = broker_status.split(".")[-1]
            elif hasattr(broker_status, 'value'):  # OrderStatus enum
                broker_status = broker_status.value
            
            return original_status, broker_status
        
        # Test Angel status normalization
        test_scenarios = [
            ("AB01", "angel"),      # Angel open status
            ("AB02", "angel"),      # Angel cancelled status
            ("AB05", "angel"),      # Angel complete status
            ("AB10", "angel"),      # Angel trigger pending
            ("OPEN", "angel"),      # Non-code status
            ("AB01", "fyers"),      # Angel code but different broker
            ("2", "fyers"),         # Fyers status code
        ]
        
        for status, broker in test_scenarios:
            original, normalized = simulate_angel_status_normalization(status, broker)
            print(f"  Broker: {broker:6}, Status: '{original:8}' → '{normalized}'")
        
        print(f"\n✅ Angel status code mapping test completed!")
        
        # Test specific Angel status codes that would be commonly used
        print(f"\n📋 Common Angel Status Codes:")
        print("-" * 30)
        common_codes = ["AB01", "AB02", "AB03", "AB05", "AB10"]
        for code in common_codes:
            status = ANGEL_STATUS_CODE_MAP.get(code)
            print(f"  {code}: {status}")
        
    except Exception as e:
        print(f"❌ Error during Angel status mapping test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_angel_status_code_mapping()